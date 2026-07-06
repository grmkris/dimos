#!/usr/bin/env python3
# Copyright 2026 Dimensional Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Adaptive bitrate for the camera encoder: a per-topic CRF ladder driven by delivery backpressure.
# The encoder is otherwise blind — it produces the same bitrate whether the viewer's link carries it
# or not, and past that point every transport can only queue (lag) or shed (slideshow). This is the
# missing feedback loop (the trick WebRTC's congestion control and every ABR player use): when
# delivery sheds, compress harder — blurrier but live; when the link stays clean, step back up.
#
# Pure controller, no encoder/transport deps: the media plane reports events and asks for the
# current CRF. Asymmetric hysteresis (fast down, slow up) like all congestion control.
from __future__ import annotations

import os

from dimos.utils.logging_config import setup_logger

logger = setup_logger()

ABR_ON = os.environ.get("VIDEO_ABR", "1") == "1"


def _default_ladder(base: int) -> tuple[int, ...]:
    """x264 CRF rungs from the deployment's base quality, best→worst; each +5 ≈ half the bits."""
    return tuple(min(51, base + 5 * i) for i in range(4))


def _ladder_from_env(base: int = 23) -> tuple[int, ...]:
    raw = os.environ.get("VIDEO_ABR_LADDER", "")
    if raw:
        try:
            rungs = tuple(int(v) for v in raw.split(",") if v.strip())
            if rungs and all(0 <= v <= 51 for v in rungs):
                return rungs
        except ValueError:
            pass
        logger.warning("bad VIDEO_ABR_LADDER — using default", raw=raw)
    return _default_ladder(base)


class AbrController:
    """Per-topic ladder state. Callers report `on_shed` (a frame was dropped / a viewer stalled —
    the link can't keep up) and `on_delivered` (a frame went out cleanly); both return True when the
    rung changed, meaning the caller must recreate its encoder at `crf()` and force an IDR."""

    def __init__(
        self,
        ladder: tuple[int, ...] | None = None,
        base_crf: int = 23,  # rung 0 — the deployment's normal quality (MEDIA_H264_CRF)
        hold_s: float = 3.0,  # min time between down-steps — one shed burst must not spiral
        clean_s: float = 15.0,  # sustained quiet before stepping quality back up
    ) -> None:
        self.ladder = ladder or _ladder_from_env(base_crf)
        self.hold_s = hold_s
        self.clean_s = clean_s
        self._level: dict[str, int] = {}
        self._last_step: dict[str, float] = {}
        self._last_shed: dict[str, float] = {}

    def crf(self, topic: str) -> int:
        return self.ladder[self._level.get(topic, 0)]

    def level(self, topic: str) -> int:
        return self._level.get(topic, 0)

    def on_shed(self, topic: str, now: float) -> bool:
        """Delivery pressure (queue shed / viewer stall). Steps down at most once per hold_s."""
        self._last_shed[topic] = now
        lvl = self._level.get(topic, 0)
        if lvl >= len(self.ladder) - 1:
            return False  # already at the floor
        if now - self._last_step.get(topic, -1e18) < self.hold_s:
            return False  # inside the hold-off — the previous step hasn't had a chance to bite
        self._level[topic] = lvl + 1
        self._last_step[topic] = now
        logger.info("video quality down", topic=topic, crf=self.ladder[lvl + 1])
        return True

    def on_delivered(self, topic: str, now: float) -> bool:
        """A clean delivery. Steps back up after clean_s with no sheds and no recent step."""
        lvl = self._level.get(topic, 0)
        if lvl == 0:
            return False
        quiet_since = max(self._last_shed.get(topic, 0.0), self._last_step.get(topic, 0.0))
        if now - quiet_since < self.clean_s:
            return False
        self._level[topic] = lvl - 1
        self._last_step[topic] = now
        logger.info("video quality up", topic=topic, crf=self.ladder[lvl - 1])
        return True

    def forget(self, topic: str) -> None:
        """Viewer(s) gone — next session starts at full quality."""
        self._level.pop(topic, None)
        self._last_step.pop(topic, None)
        self._last_shed.pop(topic, None)
