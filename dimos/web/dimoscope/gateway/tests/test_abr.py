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

# Unit tests for the ABR ladder controller (gateway/abr.py) — pure logic, no encoder/loop.
# Run: uv run pytest dimos/web/dimoscope/gateway/tests/test_abr.py -q
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent))  # dimoscope root → gateway pkg

from gateway.abr import AbrController

LADDER = (23, 28, 33, 38)


def make() -> AbrController:
    return AbrController(ladder=LADDER, hold_s=3.0, clean_s=15.0)


def test_starts_at_best_quality():
    abr = make()
    assert abr.crf("/cam") == 23
    assert abr.level("/cam") == 0


def test_shed_steps_down_once_then_holds_off():
    abr = make()
    assert abr.on_shed("/cam", 100.0) is True
    assert abr.crf("/cam") == 28
    # a burst of sheds inside hold_s must not spiral down the whole ladder
    assert abr.on_shed("/cam", 100.5) is False
    assert abr.on_shed("/cam", 102.9) is False
    assert abr.crf("/cam") == 28
    # after the hold-off, continued pressure steps again
    assert abr.on_shed("/cam", 103.1) is True
    assert abr.crf("/cam") == 33


def test_floor_is_clamped():
    abr = make()
    t = 100.0
    for _ in range(10):
        abr.on_shed("/cam", t)
        t += 4.0
    assert abr.crf("/cam") == 38  # worst rung, never past the end
    assert abr.on_shed("/cam", t) is False


def test_clean_window_steps_back_up():
    abr = make()
    abr.on_shed("/cam", 100.0)
    assert abr.crf("/cam") == 28
    # deliveries during the clean window don't step yet
    assert abr.on_delivered("/cam", 110.0) is False
    # after clean_s of quiet since the last shed/step, quality recovers one rung
    assert abr.on_delivered("/cam", 115.1) is True
    assert abr.crf("/cam") == 23
    # and never past the top
    assert abr.on_delivered("/cam", 200.0) is False


def test_shed_resets_the_clean_window():
    abr = make()
    abr.on_shed("/cam", 100.0)
    abr.on_shed("/cam", 104.0)  # → level 2
    assert abr.crf("/cam") == 33
    # a shed at t=114 (inside hold-off → no step) still counts as pressure...
    assert abr.on_shed("/cam", 106.0) is False
    # ...so quiet is measured from 106, not 104: no up-step at 120
    assert abr.on_delivered("/cam", 120.0) is False
    assert abr.on_delivered("/cam", 121.1) is True
    assert abr.crf("/cam") == 28


def test_topics_are_independent():
    abr = make()
    abr.on_shed("/cam_a", 100.0)
    assert abr.crf("/cam_a") == 28
    assert abr.crf("/cam_b") == 23


def test_forget_resets_to_full_quality():
    abr = make()
    abr.on_shed("/cam", 100.0)
    abr.forget("/cam")
    assert abr.crf("/cam") == 23
    assert abr.level("/cam") == 0


def test_env_ladder_parsing(monkeypatch):
    from gateway.abr import _ladder_from_env

    monkeypatch.setenv("VIDEO_ABR_LADDER", "20,30,40")
    assert _ladder_from_env() == (20, 30, 40)
    monkeypatch.setenv("VIDEO_ABR_LADDER", "garbage")
    assert _ladder_from_env(base=23) == (23, 28, 33, 38)  # falls back to base-derived
    monkeypatch.setenv("VIDEO_ABR_LADDER", "23,99")  # out of CRF range
    assert _ladder_from_env(base=23) == (23, 28, 33, 38)
    monkeypatch.delenv("VIDEO_ABR_LADDER")
    assert _ladder_from_env(base=20) == (20, 25, 30, 35)  # MEDIA_H264_CRF is rung 0
    assert _ladder_from_env(base=48) == (48, 51, 51, 51)  # clamped at the CRF ceiling
