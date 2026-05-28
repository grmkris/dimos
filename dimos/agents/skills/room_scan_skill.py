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

"""LiDAR-splat capture skill — feeds robomoo's `mode=lidar` ingest path.

The existing `TakePictureSkill.room_scan` already walks the robot through
the space and uploads RGB frames with 2D pose. That drives the
COLMAP-based reconstruction. The Tier-A LiDAR-splat path
([direction-c/07 §2](https://github.com/grmkris/robohack/blob/master/direction-c/07-lidar-splat-plan.md))
needs more on the same scan:

  * full 6-DoF camera pose per frame (poseZ + qx/qy/qz/qw + tsNs) so the
    consumer (gs-pot `mode=lidar`) can skip pycolmap SfM
  * the accumulated LiDAR voxel cloud at scan end as a dense init seed

`RoomScanSkill` is a sibling of `TakePictureSkill` that does **only the
ingest** (no motion). The agent (or an operator) drives motion via
`TakePictureSkill.room_scan` / `relative_move` / teleop; this module
observes the streams and POSTs the richer data to the robomoo endpoints
that ship in robohack PR #20:

  * `POST /api/robot/frame`       — per-frame 6-DoF + tsNs (same endpoint
    TakePictureSkill uses; the existing 2D-pose ingest still works)
  * `POST /api/robot/pointcloud`  — accumulated LiDAR cloud at stop
  * `POST /api/robot/poses`       — batched 6-DoF re-emission at stop
    (idempotent; lets a later PGO refinement overwrite the per-frame
    pose with a drift-corrected value)

Env contract mirrors `TakePictureSkill` / `MapUploader`:

    ROBOMOO_URL=https://gateway-...up.railway.app
    ROBOT_INGEST_TOKEN=<secret matching robomoo's server>

Subscribes to:
  * `color_image: In[Image]`           — RGB stream (per-frame upload trigger)
  * `odom: In[PoseStamped]`            — full 6-DoF pose (FastLio2-fed when
                                          the blueprint includes FastLio2)
  * `global_map: In[PointCloud2]`      — accumulated voxel cloud (FastLio2
                                          emits this with map_freq>0)

Skills exposed:
  * `start_scan(scene_name)`  — open a logical run window; returns the run id
  * `stop_scan()`             — POST cloud + poses batch; close the run
  * `scan_status()`           — JSON status of the active run

No motion: the caller's responsibility. Compose with
`TakePictureSkill.room_scan` for autonomous-walk demos, or with
`relative_move` / teleop for operator-driven scans.
"""

from __future__ import annotations

import io
import json
import math
import os
import struct
import threading
import time
from dataclasses import dataclass, field

import cv2
import httpx
import numpy as np

from dimos.agents.annotation import skill
from dimos.agents.skill_result import SkillResult
from dimos.core.core import rpc
from dimos.core.module import Module, ModuleConfig
from dimos.core.stream import In
from dimos.msgs.geometry_msgs.PoseStamped import PoseStamped
from dimos.msgs.sensor_msgs.Image import Image
from dimos.msgs.sensor_msgs.PointCloud2 import PointCloud2
from dimos.utils.logging_config import setup_logger

logger = setup_logger()


class RoomScanSkillConfig(ModuleConfig):
    robomoo_url: str = os.getenv("ROBOMOO_URL", "")
    ingest_token: str = os.getenv("ROBOT_INGEST_TOKEN", "")
    # Voxel-grid downsample edge length (m) applied to the accumulated cloud
    # before upload. 5 cm matches the seed-init voxel size used by
    # `gs_pot.lidar_poses.write_colmap_workspace`.
    voxel_size_m: float = 0.05
    # Hard cap on cloud size (post-downsample) we'll upload. 5M points is
    # ~50 MB binary PLY; well under robohack's 100 MB pointcloud limit.
    max_cloud_points: int = 5_000_000
    # Background HTTP timeout (s). Cloud uploads on slow links can take a
    # while; 5 min is conservative.
    upload_timeout_s: float = 300.0


@dataclass
class _FramePose:
    """One captured frame's pose entry, batched for the stop-scan POST."""

    frame_id: str
    tx: float
    ty: float
    tz: float
    qx: float
    qy: float
    qz: float
    qw: float
    ts_ns: int

    def to_payload(self) -> dict[str, object]:
        return {
            "frameId": self.frame_id,
            "tx": self.tx, "ty": self.ty, "tz": self.tz,
            "qx": self.qx, "qy": self.qy, "qz": self.qz, "qw": self.qw,
            "ts_ns": str(self.ts_ns),
        }


@dataclass
class _RunState:
    """Per-run state. Lives only while a scan is active."""

    run_id: str
    scene_name: str
    t0_monotonic: float
    frame_count: int = 0
    poses: list[_FramePose] = field(default_factory=list)


class RoomScanSkill(Module):
    """LiDAR-splat ingest companion to TakePictureSkill.

    Composes with FastLio2 (for the 6-DoF pose + voxel cloud streams) and
    robomoo's `/api/robot/{frame,pointcloud,poses}` ingest. The skill does
    not drive motion; pair with another skill that does (TakePictureSkill's
    `room_scan` / `explore_and_capture`, or `relative_move`, or teleop).
    """

    config: RoomScanSkillConfig
    color_image: In[Image]
    odom: In[PoseStamped]
    global_map: In[PointCloud2]

    @rpc
    def start(self) -> None:
        super().start()
        self._latest_pose: PoseStamped | None = None
        self._latest_cloud: PointCloud2 | None = None
        self._run: _RunState | None = None
        self._run_lock = threading.Lock()
        self._uploads: list[threading.Thread] = []
        self._uploads_lock = threading.Lock()
        self.odom.subscribe(self._on_odom)
        self.global_map.subscribe(self._on_global_map)
        # color_image is the per-frame upload trigger; subscribe last so the
        # other caches are ready when the first frame fires.
        self.color_image.subscribe(self._on_image)

    @rpc
    def stop(self) -> None:
        # If a scan is still running, close it best-effort before the
        # module worker dies (so partial scans don't lose their cloud).
        with self._run_lock:
            run = self._run
            self._run = None
        if run is not None:
            try:
                self._finalize(run)
            except Exception:  # noqa: BLE001 — best effort on module shutdown
                logger.exception("scan finalize failed on stop()")
        with self._uploads_lock:
            uploads = list(self._uploads)
        for t in uploads:
            if t.is_alive():
                t.join(timeout=10.0)
        super().stop()

    # ── stream handlers ────────────────────────────────────────────────────

    def _on_odom(self, pose: PoseStamped) -> None:
        self._latest_pose = pose

    def _on_global_map(self, cloud: PointCloud2) -> None:
        self._latest_cloud = cloud

    def _on_image(self, image: Image) -> None:
        # No active run → ignore (this skill is opt-in per scan).
        run = self._run
        if run is None:
            return
        if not self._configured():
            return
        pose = self._latest_pose
        if pose is None:
            # No pose yet — skip rather than upload a frame with garbage 6-DoF.
            return

        # Snapshot frame + pose + tsNs into a background uploader so the
        # subscriber thread doesn't stall on HTTP.
        frame_id = f"frame_{run.run_id}_{run.frame_count:05d}"
        ts_ns = self._ts_ns_from_pose(pose)
        # Capture all the values we need NOW; pose object may mutate later.
        fpose = _FramePose(
            frame_id=frame_id,
            tx=float(pose.position.x), ty=float(pose.position.y), tz=float(pose.position.z),
            qx=float(pose.orientation.x), qy=float(pose.orientation.y),
            qz=float(pose.orientation.z), qw=float(pose.orientation.w),
            ts_ns=ts_ns,
        )
        run.poses.append(fpose)
        run.frame_count += 1

        # Daemon background upload — fire and forget.
        t = threading.Thread(
            target=self._upload_frame_bg,
            args=(image, run.run_id, run.frame_count - 1, fpose),
            daemon=True,
            name="room-scan-frame-upload",
        )
        with self._uploads_lock:
            self._uploads = [u for u in self._uploads if u.is_alive()]
            self._uploads.append(t)
        t.start()

    # ── @skill surface ─────────────────────────────────────────────────────

    @skill
    def start_scan(self, scene_name: str = "room") -> SkillResult:
        """Begin a LiDAR-aware 3D scan. The robot should already be moving (or
        about to) via another skill (TakePictureSkill.room_scan,
        relative_move, or teleop); this just opens the ingest window so each
        frame's full 6-DoF pose lands in robomoo and the LiDAR cloud is
        uploaded at stop_scan.

        Args:
            scene_name: Human-readable label (e.g. "apt_3f_living_room").
        """
        if not self._configured():
            return SkillResult.fail(
                "NOT_CONFIGURED",
                "ROBOMOO_URL / ROBOT_INGEST_TOKEN not set",
            )
        run_id = f"scan-{int(time.time())}"
        with self._run_lock:
            if self._run is not None:
                return SkillResult.fail(
                    "ALREADY_RUNNING",
                    f"Already scanning (run={self._run.run_id}). Call stop_scan first.",
                )
            self._run = _RunState(
                run_id=run_id,
                scene_name=scene_name,
                t0_monotonic=time.monotonic(),
            )
        logger.info("room_scan start: run=%s scene=%s", run_id, scene_name)
        return SkillResult.ok(
            f"Scan started (run={run_id}, scene={scene_name}). Walk the robot now; "
            "call stop_scan when done."
        )

    @skill
    def stop_scan(self) -> SkillResult:
        """Finish the active scan: POST the accumulated LiDAR cloud + the
        per-frame 6-DoF pose batch to robomoo, then close the run. Returns
        a summary of the upload (frame count, point count, cloud size)."""
        with self._run_lock:
            run = self._run
            self._run = None
        if run is None:
            return SkillResult.fail("NO_ACTIVE_SCAN", "Call start_scan first.")
        if not self._configured():
            return SkillResult.fail(
                "NOT_CONFIGURED",
                "ROBOMOO_URL / ROBOT_INGEST_TOKEN not set",
            )

        summary = self._finalize(run)
        return SkillResult.ok(
            f"Scan {run.run_id} stopped. {summary}"
        )

    @skill
    def scan_status(self) -> SkillResult:
        """Return the status of the active scan (or 'idle' if none)."""
        run = self._run
        if run is None:
            return SkillResult.ok(json.dumps({"status": "idle"}))
        return SkillResult.ok(json.dumps({
            "status": "scanning",
            "run_id": run.run_id,
            "scene_name": run.scene_name,
            "elapsed_s": round(time.monotonic() - run.t0_monotonic, 1),
            "frame_count": run.frame_count,
            "has_cloud": self._latest_cloud is not None,
        }))

    # ── internals ──────────────────────────────────────────────────────────

    def _configured(self) -> bool:
        return bool(self.config.robomoo_url and self.config.ingest_token)

    @staticmethod
    def _ts_ns_from_pose(pose: PoseStamped) -> int:
        """PoseStamped.ts is a float seconds; widen to ns for robomoo's
        bigint tsNs column. Falls back to wall-clock if ts is missing."""
        ts = getattr(pose, "ts", None)
        if ts is None or ts == 0.0:
            return time.time_ns()
        return int(float(ts) * 1_000_000_000)

    def _upload_frame_bg(
        self, image: Image, run_id: str, image_index: int, fpose: _FramePose
    ) -> None:
        """Encode + POST a single frame to /api/robot/frame with full 6-DoF."""
        try:
            ok, buf = cv2.imencode(".jpg", image.data)
            if not ok:
                logger.warning("frame %s: encode failed", fpose.frame_id)
                return
            # Position grouping: integer-meter buckets along the walk so the
            # scans UI groups frames sensibly even without exact panorama
            # semantics (matches TakePictureSkill.room_scan's heuristic).
            position = int(math.hypot(fpose.tx, fpose.ty))
            angle = round(
                math.degrees(2 * math.atan2(fpose.qz, fpose.qw))
            ) % 360
            label = f"{run_id}/pos{position:02d}/{angle:03d}"

            data = {
                "run": run_id,
                "position": str(position),
                "angle": str(angle),
                "imageIndex": str(image_index),
                "label": label,
                "note": "lidar_scan",
                "poseX": str(fpose.tx),
                "poseY": str(fpose.ty),
                "poseZ": str(fpose.tz),
                "qx": str(fpose.qx), "qy": str(fpose.qy),
                "qz": str(fpose.qz), "qw": str(fpose.qw),
                "tsNs": str(fpose.ts_ns),
            }
            r = httpx.post(
                f"{self.config.robomoo_url.rstrip('/')}/api/robot/frame",
                headers={"Authorization": f"Bearer {self.config.ingest_token}"},
                files={"file": ("frame.jpg", buf.tobytes(), "image/jpeg")},
                data=data,
                timeout=self.config.upload_timeout_s,
            )
            r.raise_for_status()
        except Exception:  # noqa: BLE001 — fire-and-forget; failures only logged
            logger.exception("frame upload failed (run=%s idx=%d)", run_id, image_index)

    def _finalize(self, run: _RunState) -> str:
        """Run at stop_scan: serialize cloud → POST; batch-POST poses."""
        cloud_summary = "no cloud"
        pose_summary = f"{len(run.poses)} poses"

        # Cloud upload — sample the latest accumulated map.
        cloud = self._latest_cloud
        if cloud is not None:
            try:
                ply_bytes, n_pts = self._cloud_to_ply_bytes(cloud)
                if n_pts > 0:
                    self._upload_cloud(run.run_id, ply_bytes, n_pts)
                    cloud_summary = f"{n_pts} points ({len(ply_bytes) // 1024} KB)"
                else:
                    cloud_summary = "empty cloud"
            except Exception:  # noqa: BLE001 — best effort
                logger.exception("cloud upload failed for run %s", run.run_id)
                cloud_summary = "cloud upload failed (see logs)"
        else:
            logger.warning("no global_map cloud cached for run %s", run.run_id)

        # Poses batch — overwrites whatever per-frame pose was on the
        # /frame ingest (the robomoo handler is idempotent on (runId, frameId)).
        try:
            self._upload_poses(run.run_id, run.poses)
        except Exception:  # noqa: BLE001 — best effort
            logger.exception("poses batch upload failed for run %s", run.run_id)
            pose_summary += " (batch POST failed; per-frame pose still landed)"

        logger.info(
            "room_scan stop: run=%s frames=%d cloud=%s",
            run.run_id, run.frame_count, cloud_summary,
        )
        return f"{run.frame_count} frames, {pose_summary}, {cloud_summary}."

    def _cloud_to_ply_bytes(self, cloud: PointCloud2) -> tuple[bytes, int]:
        """Voxel-downsample the accumulated PointCloud2 and serialize as
        binary little-endian PLY (xyz float32). Returns (bytes, point_count).
        """
        pts = cloud.points_f32()  # (N, 3) float32
        if pts.size == 0:
            return b"", 0
        if self.config.voxel_size_m > 0:
            pts = _voxel_downsample(pts, float(self.config.voxel_size_m))
        if pts.shape[0] > self.config.max_cloud_points:
            # Uniform stride downsample to the cap (preserves spatial coverage
            # better than head() since voxel hits are not spatially sorted).
            stride = int(np.ceil(pts.shape[0] / self.config.max_cloud_points))
            pts = pts[::stride]
        n = int(pts.shape[0])
        header = (
            "ply\n"
            "format binary_little_endian 1.0\n"
            f"element vertex {n}\n"
            "property float x\n"
            "property float y\n"
            "property float z\n"
            "end_header\n"
        ).encode("ascii")
        body = pts.astype(np.float32, copy=False).tobytes()
        return header + body, n

    def _upload_cloud(self, run_id: str, ply_bytes: bytes, n_points: int) -> None:
        r = httpx.post(
            f"{self.config.robomoo_url.rstrip('/')}/api/robot/pointcloud",
            headers={"Authorization": f"Bearer {self.config.ingest_token}"},
            files={"file": (f"{run_id}.ply", ply_bytes, "application/octet-stream")},
            data={"runId": run_id, "format": "ply", "pointCount": str(n_points)},
            timeout=self.config.upload_timeout_s,
        )
        r.raise_for_status()

    def _upload_poses(self, run_id: str, poses: list[_FramePose]) -> None:
        if not poses:
            return
        body = {
            "runId": run_id,
            "frames": [p.to_payload() for p in poses],
        }
        r = httpx.post(
            f"{self.config.robomoo_url.rstrip('/')}/api/robot/poses",
            headers={
                "Authorization": f"Bearer {self.config.ingest_token}",
                "Content-Type": "application/json",
            },
            content=json.dumps(body).encode("utf-8"),
            timeout=self.config.upload_timeout_s,
        )
        r.raise_for_status()


def _voxel_downsample(points: np.ndarray, voxel_size: float) -> np.ndarray:
    """numpy-only voxel-grid downsample: one representative point per cell.

    Mirrors the helper in gs-pot/gs_pot/lidar_poses.py so the cloud the
    robot uploads has the same shape gs-pot would have voxel-downsampled
    to anyway. Deterministic for a given input.
    """
    if points.size == 0 or voxel_size <= 0:
        return points
    keys = np.floor(points / voxel_size).astype(np.int64)
    _, uniq_idx = np.unique(keys, axis=0, return_index=True)
    uniq_idx.sort()
    return points[uniq_idx]


__all__ = ["RoomScanSkill", "RoomScanSkillConfig"]
