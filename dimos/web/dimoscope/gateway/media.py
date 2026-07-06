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

# dimoscope media plane: camera Image → WebRTC / WebCodecs / JPEG, served on /media from the shared Bus.
# Encoding is CPU-heavy (PyAV/libx264, aiortc) so it runs in a single-worker executor (never two encoders
# at once). Both paths encode once and fan out to N viewers:
#   WebRTC (aiortc): recvonly offer/answer; browser HW-decodes a <video>.
#   WebCodecs (libx264 Annex-B): {video-config} JSON then binary
#     [u8 flags(bit0=keyframe)][u64 ts_us BE][u16 topic_len BE][topic utf8][H.264 Annex-B NAL]
# JPEG floor: decoded in the browser off the data plane, needs nothing here.
from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
import json
import os
import struct
import time
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from .abr import ABR_ON, AbrController
from .bus import Bus, ConflatedIngest, Sample

# WebRTC (optional): re-encode the camera Image as a video track via aiortc.
try:
    from aiortc import RTCPeerConnection, RTCSessionDescription

    from dimos.msgs.sensor_msgs.Image import Image
    from dimos.teleop.quest_hosted.video_track import CameraVideoTrack

    HAS_WEBRTC = True
except Exception:  # pragma: no cover - depends on optional aiortc/av install
    HAS_WEBRTC = False

# WebCodecs (optional): encode the camera Image to raw H.264 (Annex-B) with PyAV.
try:
    from fractions import Fraction

    import av

    from dimos.msgs.sensor_msgs.Image import Image

    try:
        from dimos.teleop.quest_hosted.video_track import _AV_FORMAT_MAP as _AV_FMT
    except Exception:
        _AV_FMT = {}
    HAS_WEBCODECS = True
except Exception:  # pragma: no cover - depends on optional av install
    HAS_WEBCODECS = False

MEDIA_KINDS = (
    (["webcodecs"] if HAS_WEBCODECS else []) + (["webrtc"] if HAS_WEBRTC else []) + ["jpeg"]
)
MEDIA_H264_CRF = os.environ.get("MEDIA_H264_CRF", "20")
MEDIA_H264_PRESET = os.environ.get("MEDIA_H264_PRESET", "veryfast")
MEDIA_H264_GOP_SECONDS = float(os.environ.get("MEDIA_H264_GOP_SECONDS", "2"))


class MediaPlane:
    def __init__(self, bus: Bus) -> None:
        self.bus = bus
        # WebRTC: camera topic -> CameraVideoTracks wanting its frames; ws -> live PCs.
        self.webrtc_tracks: dict[str, set[CameraVideoTrack]] = {}
        self.webrtc_pcs: dict[WebSocket, list[tuple[RTCPeerConnection, CameraVideoTrack, str]]] = {}
        # WebCodecs: camera topic -> set of ws wanting H.264 chunks; one encoder per topic.
        self.webcodecs_subs: dict[str, set[WebSocket]] = {}
        self.wt_webcodecs_subs: set[str] = set()
        self.wt_sink: Callable[[bytes], None] | None = None
        self.encoders: dict[str, av.VideoCodecContext] = {}
        self.force_key: set[str] = set()
        self._in = ConflatedIngest()  # freshest-wins: a slow encoder lowers fps, never adds lag
        self._arrivals: dict[
            str, deque[float]
        ] = {}  # topic → recent arrival times (measures real fps)
        # Encoded NAL → fanout. Bounded for the same reason ingest conflates: a slow viewer must
        # shed frames, not grow a backlog every viewer then waits behind.
        self._video_q: asyncio.Queue[tuple[str, bytes, bool, int]] = asyncio.Queue(maxsize=64)
        self._exec = ThreadPoolExecutor(
            max_workers=1
        )  # serialise encode → encoders stay single-thread
        # Adaptive bitrate: fanout sheds (the link can't keep up) step the CRF ladder down —
        # blurrier but live beats sharp but frozen; sustained clean delivery steps back up.
        self._abr = AbrController(base_crf=int(MEDIA_H264_CRF)) if ABR_ON else None
        bus.subscribe(self._on_sample)

    def set_wt_sink(self, sink: Callable[[bytes], None]) -> None:
        self.wt_sink = sink

    def set_wt_subs(self, topics: set[str]) -> None:
        new_topics = set(topics)
        for topic in new_topics - self.wt_webcodecs_subs:
            self.force_key.add(topic)
        gone = self.wt_webcodecs_subs - new_topics
        self.wt_webcodecs_subs = new_topics
        for topic in gone:
            self._maybe_forget(topic)

    def _maybe_forget(self, topic: str) -> None:
        """Last viewer of a topic left (any path) → the next session starts at full quality."""
        if self._abr and not self.webcodecs_subs.get(topic) and topic not in self.wt_webcodecs_subs:
            self._abr.forget(topic)

    def on_wt_pressure(self, topic: str) -> None:
        """WT sidecar shed queued H.264 for this topic; rebuild lower-bitrate and resync."""
        if not topic:
            return
        self.force_key.add(topic)
        if self._abr and self._abr.on_shed(topic, time.monotonic()):
            self.encoders.pop(topic, None)

    # bus tap (loop thread, cheap): only camera topics with live viewers
    def _on_sample(self, s: Sample) -> None:
        if "Image" not in (s.type or ""):  # camera frames are sensor_msgs.Image
            return
        trs = self.webrtc_tracks.get(s.topic) if HAS_WEBRTC else None
        wc = self.webcodecs_subs.get(s.topic) if HAS_WEBCODECS else None
        wt = s.topic in self.wt_webcodecs_subs if HAS_WEBCODECS else False
        if not (trs or wc or wt):
            return
        self._arrivals.setdefault(s.topic, deque(maxlen=8)).append(time.monotonic())
        self._in.put(s.topic, s.payload)

    def _measured_fps(self, topic: str) -> int | None:
        """Real camera rate from recent inter-arrival times, clamped [5, 60]; None until enough
        samples (the encoder waits — locking in a guessed rate would mistune rate control and the
        IDR cadence for the whole session)."""
        t = self._arrivals.get(topic)
        if not t or len(t) < 5 or t[-1] <= t[0]:
            return None
        return max(5, min(60, round((len(t) - 1) / (t[-1] - t[0]))))

    # background tasks (started in app.py's lifespan)
    async def run_encoder(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            topic, payload = await self._in.get()
            await loop.run_in_executor(self._exec, self._process, topic, payload, loop)

    def _process(self, topic: str, payload: bytes, loop: asyncio.AbstractEventLoop) -> None:
        """Executor thread: decode the Image once, feed WebRTC tracks + the WebCodecs encoder."""
        try:
            img = Image.lcm_decode(payload)
        except Exception:
            return
        trs = self.webrtc_tracks.get(topic)
        if trs:
            for tr in list(trs):
                tr.set_latest(img)
        if self.webcodecs_subs.get(topic) or topic in self.wt_webcodecs_subs:
            self._encode_webcodecs(topic, img, loop)

    def _encode_webcodecs(self, topic: str, img: Image, loop: asyncio.AbstractEventLoop) -> None:
        try:
            data = img.data
            h, w = int(data.shape[0]), int(data.shape[1])
            enc = self.encoders.get(topic)
            if enc is not None and (enc.width, enc.height) != (w, h):
                self.encoders.pop(topic, None)  # resolution changed → stale context would raise
                self.force_key.add(topic)  # viewers must resync on an IDR at the new size
                enc = None
            if enc is None:
                fps = self._measured_fps(topic)
                if fps is None:
                    return  # a few frames of warmup — measure before locking in rate control
                enc = av.CodecContext.create("libx264", "w")
                enc.width, enc.height, enc.pix_fmt = w, h, "yuv420p"
                enc.framerate = Fraction(
                    fps, 1
                )  # real fps → correct rate control (else blocky garbage)
                enc.time_base = Fraction(1, 1_000_000)  # pts in µs
                enc.options = {
                    "tune": "zerolatency",
                    "preset": MEDIA_H264_PRESET,
                    "profile": "baseline",  # avc1.42e0 — universal hardware decode
                    "crf": str(self._abr.crf(topic)) if self._abr else MEDIA_H264_CRF,
                    "g": str(max(1, round(MEDIA_H264_GOP_SECONDS * fps))),
                    "bf": "0",  # no B-frames → lower latency
                    "x264-params": "repeat-headers=1",  # SPS/PPS before every IDR → late joiners decode
                }
                self.encoders[topic] = enc
            fmt: Any = getattr(img, "format", None)
            frame = av.VideoFrame.from_ndarray(data, format=_AV_FMT.get(fmt, "bgr24"))
            frame.pts = int(time.time() * 1_000_000)
            frame.time_base = Fraction(1, 1_000_000)
            if topic in self.force_key:
                try:
                    frame.pict_type = av.video.frame.PictureType.I
                except Exception:
                    pass
                self.force_key.discard(topic)
            for pkt in enc.encode(frame):
                buf = bytes(pkt)
                if buf:
                    ts = int(pkt.pts) if pkt.pts is not None else int(time.time() * 1_000_000)
                    loop.call_soon_threadsafe(self._q_put, (topic, buf, bool(pkt.is_keyframe), ts))
            # Sustained clean delivery → recover one quality rung (fresh encoder at the new CRF).
            if self._abr and self._abr.on_delivered(topic, time.monotonic()):
                self.encoders.pop(topic, None)
                self.force_key.add(topic)
        except Exception:
            pass  # an encode hiccup must never disturb other viewers

    def _q_put(self, item: tuple[str, bytes, bool, int]) -> None:
        """Loop thread: enqueue an encoded chunk, shedding the oldest when full. A dropped delta
        breaks that topic's GOP for viewers, so force an IDR to resync within a frame or two."""
        if self._video_q.full():
            try:
                dropped = self._video_q.get_nowait()
                self.force_key.add(dropped[0])
                # A shed means the link can't carry the current bitrate — step the ladder down
                # (the fresh encoder at higher CRF starts on the forced IDR).
                if self._abr and self._abr.on_shed(dropped[0], time.monotonic()):
                    self.encoders.pop(dropped[0], None)
            except asyncio.QueueEmpty:
                pass
        self._video_q.put_nowait(item)

    async def run_fanout(self) -> None:
        # WebCodecs chunk wire: [u8 flags(bit0=key)][u64 ts_us BE][u16 topic_len BE][topic][NAL]
        # Per-viewer sends are non-blocking (one in-flight task each): a slow viewer gets frames
        # SKIPPED — never queued (bufferbloat) and never a stall for other viewers. Each skip is
        # the ABR down-signal (the link can't carry this bitrate); a viewer that finishes draining
        # after skips gets a forced IDR to rejoin the GOP. Eviction only on a dead socket.
        inflight: dict[WebSocket, asyncio.Task[None]] = {}
        stalled: set[WebSocket] = set()
        while True:
            topic, buf, is_key, ts_us = await self._video_q.get()
            subs = self.webcodecs_subs.get(topic) or set()
            wt_wants = topic in self.wt_webcodecs_subs
            if not subs and not wt_wants:
                continue
            tb = topic.encode()
            head = struct.pack(">BQH", 1 if is_key else 0, ts_us & 0xFFFFFFFFFFFFFFFF, len(tb))
            frame = head + tb + buf
            if wt_wants and self.wt_sink is not None:
                self.wt_sink(frame)
            for ws in list(subs):
                prev = inflight.get(ws)
                if prev is not None:
                    if not prev.done():
                        stalled.add(ws)  # still draining the last chunk — shed this one
                        if self._abr and self._abr.on_shed(topic, time.monotonic()):
                            self.encoders.pop(topic, None)  # rebuild at the lower rung
                        continue
                    inflight.pop(ws, None)
                    if prev.exception() is not None:
                        subs.discard(ws)
                        stalled.discard(ws)
                        continue
                    if ws in stalled:
                        stalled.discard(ws)
                        self.force_key.add(topic)  # rejoin mid-GOP → needs an IDR
                inflight[ws] = asyncio.create_task(ws.send_bytes(frame))
            # Entries for viewers that unsubscribed drop out on their next completed send; cap
            # the map against pathological churn.
            if len(inflight) > 4 * (len(subs) + 1):
                for ws in [w for w, t in inflight.items() if t.done()]:
                    inflight.pop(ws, None)

    def _add_track(self, topic: str, track: CameraVideoTrack) -> None:
        self.webrtc_tracks.setdefault(topic, set()).add(track)

    def _drop_track(self, topic: str, track: CameraVideoTrack) -> None:
        s = self.webrtc_tracks.get(topic)
        if s is not None:
            s.discard(track)
            if not s:
                self.webrtc_tracks.pop(topic, None)

    async def _close_pcs(self, ws: WebSocket) -> None:
        for pc, track, topic in self.webrtc_pcs.pop(ws, []):
            self._drop_track(topic, track)
            try:
                await pc.close()
            except Exception:
                pass

    async def _handle_webrtc_offer(self, ws: WebSocket, m: dict[str, Any]) -> None:
        topic, sdp = m.get("topic"), m.get("sdp")
        if not topic or not sdp:
            return
        await self._close_pcs(ws)
        track = CameraVideoTrack()
        pc = RTCPeerConnection()
        self._add_track(topic, track)
        self.webrtc_pcs.setdefault(ws, []).append((pc, track, topic))
        pc.addTrack(track)

        @pc.on("connectionstatechange")
        async def _on_state() -> None:
            if pc.connectionState == "connected":
                track.arm()  # start the operator's video at "now", not robot boot
            elif pc.connectionState in ("failed", "closed"):
                self._drop_track(topic, track)

        await pc.setRemoteDescription(RTCSessionDescription(sdp=sdp, type="offer"))
        await pc.setLocalDescription(await pc.createAnswer())
        if pc.iceGatheringState != "complete":
            fut = asyncio.get_running_loop().create_future()

            @pc.on("icegatheringstatechange")
            def _on_gathering() -> None:
                if pc.iceGatheringState == "complete" and not fut.done():
                    fut.set_result(None)

            await fut
        await ws.send_text(json.dumps({"op": "webrtc-answer", "sdp": pc.localDescription.sdp}))

    async def handle(self, ws: WebSocket) -> None:
        await ws.accept()
        await ws.send_text(json.dumps({"op": "hello", "label": "media", "media": MEDIA_KINDS}))
        try:
            while True:
                m = json.loads(await ws.receive_text())
                op = m.get("op")
                if op == "webrtc-offer" and HAS_WEBRTC:
                    await self._handle_webrtc_offer(ws, m)
                elif op == "webrtc-stop":
                    await self._close_pcs(ws)
                elif op == "webcodecs-start" and HAS_WEBCODECS:
                    t = m.get("topic")
                    if t:
                        self.webcodecs_subs.setdefault(t, set()).add(ws)
                        self.force_key.add(t)  # emit an IDR so this viewer starts fast
                        await ws.send_text(
                            json.dumps({"op": "video-config", "topic": t, "codec": "avc1.42E01F"})
                        )
                elif op == "webcodecs-stop":
                    t = m.get("topic")
                    s = self.webcodecs_subs.get(t)
                    if s is not None:
                        s.discard(ws)
                        self._maybe_forget(t)
        except (WebSocketDisconnect, json.JSONDecodeError, RuntimeError):
            pass
        finally:
            await self._close_pcs(ws)
            for t, s in self.webcodecs_subs.items():
                s.discard(ws)
                self._maybe_forget(t)
