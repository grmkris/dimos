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

# The bench delivery transports: SSE (sse.py) and HTTP long-poll (poll.py) tap the shared Bus and
# re-emit the same [f64 gateway-send-ms][LC02] frames as the default WS data plane, so the browser
# decodes every path through the identical frameToSample. Both are read-only benchmark baselines;
# WebTransport AND WebRTC live in the native sidecar (gateway/wt-sidecar), fed by gateway/pipe.py —
# /rtc (webrtc.py) is only the SDP signaling relay. This module holds the shared framing helpers
# plus subscription matching + the ?topics= query parse.
from __future__ import annotations

import struct
import time

from ..bus import Sample


def frame(s: Sample) -> bytes:
    return struct.pack(">d", time.time() * 1000.0) + s.lc02  # [f64 gateway-send-ms][LC02]


def wants(subs: set[str], topic: str) -> bool:
    return "*" in subs or topic in subs


def subs_from_query(tp: str | None) -> set[str]:
    if tp is None or tp == "*":
        return {"*"}
    return {t for t in tp.split(",") if t}
