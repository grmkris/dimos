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

# HTTP long-poll bench transport — a ring buffer + since-cursor; a request blocks up to POLL_WAIT_S for
# new frames, then returns [u32 cursor][u32 count]{[u32 len][frame]}…. READ-ONLY. Mounts at /poll.
from __future__ import annotations

import asyncio
from collections import deque
import struct

from starlette.requests import Request
from starlette.responses import Response

from ..bus import Bus, Sample
from ._common import frame, subs_from_query, wants

POLL_RING_MAX = 8192
POLL_WAIT_S = 10.0


class PollPlane:
    def __init__(self, bus: Bus) -> None:
        self.bus = bus
        self.ring: deque[tuple[int, str, bytes]] = deque(maxlen=POLL_RING_MAX)  # (id, topic, frame)
        self.seq = 0
        self._waiters: set[asyncio.Future[None]] = set()
        bus.subscribe(self._on_sample)

    def _on_sample(self, s: Sample) -> None:
        self.seq += 1
        self.ring.append((self.seq, s.topic, frame(s)))
        for f in self._waiters:
            if not f.done():
                f.set_result(None)
        self._waiters.clear()

    def _collect(self, since: int, subs: set[str], max_n: int) -> list[tuple[int, bytes]]:
        out: list[tuple[int, bytes]] = []
        for eid, topic, fr in self.ring:
            if eid <= since or not wants(subs, topic):
                continue
            out.append((eid, fr))
            if len(out) >= max_n:
                break
        return out

    async def handle(self, request: Request) -> Response:
        since = int(request.query_params.get("since", 0))
        subs = subs_from_query(request.query_params.get("topics"))
        max_n = int(request.query_params.get("max", 512))
        hdr = {"content-type": "application/octet-stream", "access-control-allow-origin": "*"}
        # since < 0 → "start from head": skip history so a live client only gets new frames.
        if since < 0:
            head = self.ring[-1][0] if self.ring else 0
            return Response(struct.pack(">II", head, 0), headers=hdr)
        batch = self._collect(since, subs, max_n)
        if not batch:
            fut = asyncio.get_running_loop().create_future()
            self._waiters.add(fut)
            try:
                await asyncio.wait_for(fut, POLL_WAIT_S)
            except asyncio.TimeoutError:
                pass
            finally:
                self._waiters.discard(fut)
            batch = self._collect(since, subs, max_n)
        new_cursor = batch[-1][0] if batch else since
        body = bytearray(struct.pack(">II", new_cursor, len(batch)))
        for _eid, fr in batch:
            body += struct.pack(">I", len(fr)) + fr
        return Response(bytes(body), headers=hdr)
