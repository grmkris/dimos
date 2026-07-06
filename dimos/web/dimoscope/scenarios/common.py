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

# Shared scaffolding for the 3 "real-world" scenario blueprints (nav / arm / cam). Each scenario is a
# standalone dimos Module publishing a distinct topic namespace at a distinct data profile, so the browser
# SDK can discover → visualize → type → benchmark it; run one, Ctrl-C, run another (the gateway taps the
# bus, so the topic set just swaps). Twin of scenarios/bench.py's scaffolding, factored out so
# nav/arm/cam.py stay to just their topic definitions.
#
# Per-message stamping: ts (publish wall-clock, seconds) → one-way latency; frame_id (per-topic monotonic
# seq) → exact drop/gap detection in the bench.
#
# Launch (from dimos/web/dimoscope): DIMOS_TRANSPORT=zenoh uv run python scenarios/nav.py
import math as math
import os
import time as time

import numpy as np

from dimos.core.core import rpc as rpc
from dimos.core.module import Module as Module, ModuleConfig as ModuleConfig
from dimos.core.stream import Out as Out
from dimos.msgs.geometry_msgs.Pose import Pose as Pose
from dimos.msgs.geometry_msgs.PoseStamped import PoseStamped as PoseStamped
from dimos.msgs.geometry_msgs.Quaternion import Quaternion as Quaternion
from dimos.msgs.geometry_msgs.Vector3 import Vector3 as Vector3
from dimos.msgs.nav_msgs.OccupancyGrid import OccupancyGrid as OccupancyGrid
from dimos.msgs.nav_msgs.Path import Path as Path
from dimos.msgs.sensor_msgs.Image import Image as Image, ImageFormat as ImageFormat
from dimos.msgs.sensor_msgs.Imu import Imu as Imu
from dimos.msgs.sensor_msgs.JointState import JointState as JointState
from dimos.msgs.sensor_msgs.PointCloud2 import PointCloud2 as PointCloud2
from dimos.msgs.std_msgs.Header import Header as Header
from dimos.msgs.trajectory_msgs.JointTrajectory import JointTrajectory as JointTrajectory
from dimos.msgs.trajectory_msgs.TrajectoryPoint import TrajectoryPoint as TrajectoryPoint
from dimos.msgs.vision_msgs.Detection2DArray import Detection2DArray as Detection2DArray

TRANSPORT = os.environ.get("DIMOS_TRANSPORT", "lcm")
IDENT = Quaternion.from_euler(Vector3(0.0, 0.0, 0.0))


def env_f(key: str, default: float) -> float:
    return float(os.environ.get(key, default))


def env_i(key: str, default: int) -> int:
    return int(os.environ.get(key, default))


def tn(topic: str) -> str:
    # Zenoh key-exprs cannot start with "/"; LCM channels keep it. The Zenoh gateway re-adds the leading
    # "/" so the browser sees "/nav/pose" either way.
    return topic[1:] if (TRANSPORT == "zenoh" and topic.startswith("/")) else topic


def mk(topic: str, typ: type):  # type: ignore[no-untyped-def]
    if TRANSPORT == "zenoh":
        from dimos.core.transport import ZenohTransport

        return ZenohTransport(topic, typ)
    from dimos.core.transport import LCMTransport

    return LCMTransport(topic, typ)


class Seq:
    """Per-topic monotonic counter → frame_id=str(seq) for exact drop/gap detection."""

    def __init__(self) -> None:
        self._d: dict[str, int] = {}

    def __call__(self, topic: str) -> str:
        n = self._d.get(topic, 0)
        self._d[topic] = n + 1
        return str(n)


def make_image(nbytes: int, fmt: ImageFormat = ImageFormat.RGB) -> Image:
    """An Image of ~nbytes bytes (RGB=3ch, GRAY=1ch). Built once then restamped per publish so generation
    cost never dominates the send loop. RANDOM bytes, not a ramp: WS permessage-deflate compresses regular
    payloads ~1000:1 and fakes every throughput number (random ≈ real sensor entropy)."""
    ch = 1 if fmt in (ImageFormat.GRAY, ImageFormat.GRAY16) else 3
    px = max(1, nbytes // ch)
    h = max(1, int(px**0.5))
    w = max(1, px // h)
    shape = (h, w) if ch == 1 else (h, w, ch)
    data = np.random.default_rng(0).integers(0, 256, shape, dtype=np.uint8)
    return Image(data=data, format=fmt)


def stamp_header(seq_val: str) -> Header:
    """A Header stamped with wall-clock now + frame_id=seq — for messages whose `.ts` is a
    read-only property off header.stamp (e.g. Detection2DArray)."""
    now = time.time()
    h = Header()
    h.stamp.sec = int(now)
    h.stamp.nsec = int((now % 1.0) * 1e9)
    h.frame_id = seq_val
    return h


def run_standalone(mod: Module, ports: list[tuple[str, str, type]], label: str) -> None:
    """Wire each Out port to a transport, start the module, and idle until Ctrl-C — the __main__
    body every scenario shares. `ports` = [(attr_name, topic, MsgType), ...]."""
    for attr, topic, typ in ports:
        getattr(mod, attr).transport = mk(tn(topic), typ)
    mod.start()
    print(
        f"{label}: publishing {', '.join(t for _, t, _ in ports)} over {TRANSPORT}"
        " — Ctrl-C to stop, then run another scenario.",
        flush=True,
    )
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        mod.stop()
