#!/usr/bin/env python3
# dimoscope image plane: server-side JPEG transcode, so the browser sees a ~100 KB JPEG instead of
# the raw ~2.8 MB rgb8 firehose (a 720p camera is ~40 MB/s raw — more than a fast LAN delivers).
# A Bus consumer (like cloud.py) that, for every source sensor_msgs.Image, republishes
#   <topic>_jpeg — same wire type, encoding="jpeg", source header/ts preserved → the existing
#                  @dimos/msgs decode + the browser's native jpeg path render it unchanged.
# Encode-once-fan-out: one TurboJPEG encode per frame regardless of viewer count; per-viewer
# shedding stays in qos.py (Image → LANE_BULK, conflated). Ingest is freshest-wins per topic —
# a slow encoder raises staleness of nothing: it just skips to the newest frame.
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import os

from dimos.utils.logging_config import setup_logger

from .bus import Bus, ConflatedIngest, Sample

logger = setup_logger()

# TurboJPEG is a native dep (+ numpy for the pixel view). A build without it → no image plane.
try:
    from dimos_lcm.sensor_msgs.Image import Image as LCMImage
    import numpy as np
    from turbojpeg import TJPF_BGR, TJPF_GRAY, TJPF_RGB, TJSAMP_GRAY, TurboJPEG

    HAS_TURBOJPEG = True
except Exception:  # pragma: no cover - optional native dep
    HAS_TURBOJPEG = False

JPEG_ON = os.environ.get("IMAGE_JPEG", "1") == "1"
JPEG_QUALITY = int(os.environ.get("IMAGE_JPEG_QUALITY", "75"))


class ImagePlane:
    def __init__(self, bus: Bus) -> None:
        self.bus = bus
        self._in = ConflatedIngest()  # freshest-wins: a slow encoder skips frames, never adds lag
        self._exec = ThreadPoolExecutor(max_workers=1)  # serialise: one encode at a time
        self._failed: set[str] = set()  # topics already warned about (log once, not per frame)
        self.enabled = HAS_TURBOJPEG and JPEG_ON
        if self.enabled:
            self._tj = TurboJPEG()  # one instance — construction is not free
            # encoding → (channels, TJPF pixel format); defined here so a TurboJPEG-less build
            # never touches the TJPF_* names.
            self._pixfmt = {
                "rgb8": (3, TJPF_RGB),
                "bgr8": (3, TJPF_BGR),
                "mono8": (1, TJPF_GRAY),
                "8uc1": (1, TJPF_GRAY),
            }
            bus.subscribe(self._on_sample)
            logger.info("image plane on", quality=JPEG_QUALITY)
        elif JPEG_ON:
            logger.warning("image plane off — TurboJPEG unavailable")

    # bus tap (loop thread, cheap): only source Image topics; skip our own derived outputs.
    def _on_sample(self, s: Sample) -> None:
        if (s.type or "") != "sensor_msgs.Image":
            return
        if s.topic.endswith("_jpeg"):
            return  # feedback guard — never transcode a derived image
        self._in.put(s.topic, s.payload)

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            topic, payload = await self._in.get()
            await loop.run_in_executor(self._exec, self._process, topic, payload)

    def _process(self, topic: str, payload: bytes) -> None:
        """Executor thread: struct-decode, JPEG the pixels, re-emit with the source header intact."""
        try:
            msg = LCMImage.lcm_decode(payload)
            fmt = self._pixfmt.get((msg.encoding or "").lower())
            if fmt is None:
                return  # already jpeg, or an encoding we don't transcode (depth/16-bit)
            ch, pixfmt = fmt
            h, w = int(msg.height), int(msg.width)
            arr = np.frombuffer(msg.data, dtype=np.uint8)
            if msg.step and msg.step > w * ch:  # row-padded stride → slice the padding off
                arr = arr.reshape(h, int(msg.step))[:, : w * ch]
            shape = (h, w) if ch == 1 else (h, w, ch)
            kw = (
                {"jpeg_subsample": TJSAMP_GRAY} if ch == 1 else {}
            )  # gray needs its own subsampling
            jpeg = self._tj.encode(
                np.ascontiguousarray(arr.reshape(shape)),
                quality=JPEG_QUALITY,
                pixel_format=pixfmt,
                **kw,
            )
            # Reuse the decoded struct: keep header (ts + frame_id → latency/seq continuity), swap data.
            msg.encoding = "jpeg"
            msg.step = 0  # n/a for compressed
            msg.data = jpeg
            msg.data_length = len(jpeg)
            out = msg.lcm_encode()
        except Exception as e:
            # A transcode hiccup must never disturb the source topic — but say so once, or a
            # malformed camera silently never gets its _jpeg sibling.
            if topic not in self._failed:
                self._failed.add(topic)
                logger.warning(
                    "image transcode failed — topic stays raw", topic=topic, error=str(e)
                )
            return
        self._failed.discard(topic)
        self.bus.republish(topic + "_jpeg", "sensor_msgs.Image", out)
