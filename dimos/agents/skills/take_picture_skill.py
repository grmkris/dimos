# Copyright 2025-2026 Dimensional Inc.
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

"""Capture robot camera frames and upload them to the robomoo app.

Skills:
  - take_picture: one-shot capture of the current frame.
  - explore_and_capture: start autonomous exploration and take a photo every few
    seconds as the robot moves (deterministic — drives the cadence itself rather
    than relying on the agent to keep calling take_picture).

Each frame is JPEG-encoded and POSTed (with the robot's odom pose) to robomoo's
`/api/robot/frame` (shared-secret bearer token). Configure via env:

    ROBOMOO_URL=https://gateway-...up.railway.app
    ROBOT_INGEST_TOKEN=<secret matching the server>
"""

import math
import os
import threading
import time

import cv2
import httpx
from dimos_lcm.std_msgs import Bool

from dimos.agents.annotation import skill
from dimos.agents.skill_result import SkillResult
from dimos.core.core import rpc
from dimos.core.module import Module, ModuleConfig
from dimos.core.stream import In, Out
from dimos.msgs.geometry_msgs.PoseStamped import PoseStamped
from dimos.msgs.geometry_msgs.Twist import Twist
from dimos.msgs.sensor_msgs.Image import Image
from dimos.navigation.frontier_exploration.frontier_explorer_spec import (
    FrontierExplorerSpec,
)
from dimos.robot.unitree.move_spec import MoveSpec
from dimos.robot.unitree.tilt_spec import TiltSpec
from dimos.utils.logging_config import setup_logger

logger = setup_logger()


class TakePictureSkillConfig(ModuleConfig):
    robomoo_url: str = os.getenv("ROBOMOO_URL", "")
    ingest_token: str = os.getenv("ROBOT_INGEST_TOKEN", "")


class TakePictureSkill(Module):
    config: TakePictureSkillConfig
    color_image: In[Image]
    odom: In[PoseStamped]
    # Drive frontier exploration (consumed by WavefrontFrontierExplorer).
    explore_cmd: Out[Bool]
    stop_explore_cmd: Out[Bool]
    # Auto-wired (structurally) to WavefrontFrontierExplorer — lets us gate the
    # capture loop on whether exploration is still running.
    _explorer: FrontierExplorerSpec
    # Auto-wired (structurally) to UnitreeSkillContainer.tilt_body — lets
    # tilt_and_capture aim the body-fixed camera without owning the connection.
    _tilt: TiltSpec
    # Auto-wired (structurally) to UnitreeSkillContainer.relative_move — lets
    # room_scan translate the robot (real-distance moves) without owning the
    # navigation stack.
    _move: MoveSpec
    # Direct base velocity (same stream person_follow drives). room_scan rotates
    # in place via cmd_vel because the global planner can't handle a heading-only
    # goal (it sees the goal at the current XY and aborts as "already arrived").
    cmd_vel: Out[Twist]

    @rpc
    def start(self) -> None:
        super().start()
        self._latest: Image | None = None
        self._pose: PoseStamped | None = None
        self._capture_thread: threading.Thread | None = None
        self._capture_stop = threading.Event()
        # Outstanding fire-and-forget upload threads from take_picture().
        self._uploads: list[threading.Thread] = []
        self._uploads_lock = threading.Lock()
        self.color_image.subscribe(self._on_image)
        self.odom.subscribe(self._on_odom)

    @rpc
    def stop(self) -> None:
        self._capture_stop.set()
        # Leave the base still if a scan was mid-rotation.
        try:
            self.cmd_vel.publish(Twist.zero())
        except Exception:  # noqa: BLE001 — best effort on shutdown
            pass
        thread = getattr(self, "_capture_thread", None)
        if thread is not None and thread.is_alive():
            thread.join(timeout=5.0)
        with self._uploads_lock:
            uploads = list(self._uploads)
        for t in uploads:
            if t.is_alive():
                t.join(timeout=5.0)
        super().stop()

    def _on_image(self, image: Image) -> None:
        self._latest = image

    def _on_odom(self, pose: PoseStamped) -> None:
        self._pose = pose

    def _configured(self) -> bool:
        return bool(self.config.robomoo_url and self.config.ingest_token)

    # Encode a given frame and POST it (with pose) to robomoo. Returns the stored
    # key, or None if there's no frame / encode failed. Raises on HTTP error.
    def _upload_frame(
        self,
        frame: Image | None,
        pose: PoseStamped | None,
        note: str = "",
        label: str = "",
        extra: dict[str, str] | None = None,
    ) -> str | None:
        if frame is None:
            return None
        ok, buf = cv2.imencode(".jpg", frame.data)
        if not ok:
            return None

        data: dict[str, str] = {}
        if note:
            data["note"] = note
        if label:
            data["label"] = label
        if pose is not None:
            data["poseX"] = str(pose.position.x)
            data["poseY"] = str(pose.position.y)
        # Extra grouping tags (e.g. run / position / angle for room_scan).
        if extra:
            data.update(extra)

        resp = httpx.post(
            f"{self.config.robomoo_url.rstrip('/')}/api/robot/frame",
            headers={"Authorization": f"Bearer {self.config.ingest_token}"},
            files={"file": ("frame.jpg", buf.tobytes(), "image/jpeg")},
            data=data,
            timeout=30.0,
        )
        resp.raise_for_status()
        return resp.json().get("key", "")

    # Thin wrapper used by the explore capture loop: upload the latest frame/pose.
    def _upload_current(
        self, note: str = "", label: str = "", extra: dict[str, str] | None = None
    ) -> str | None:
        return self._upload_frame(
            getattr(self, "_latest", None),
            getattr(self, "_pose", None),
            note=note,
            label=label,
            extra=extra,
        )

    @skill
    def take_picture(self, note: str = "") -> SkillResult:
        """Capture a photo from the robot's camera and upload it.

        Use whenever the user asks the robot to take or capture a single picture
        or photo of what it currently sees. `note` is an optional short caption
        to tag the image with (e.g. "kitchen", "plant"). Returns immediately; the
        encode + upload happen in the background.
        """
        frame = getattr(self, "_latest", None)
        if frame is None:
            return SkillResult.fail("NO_FRAME", "No camera frame received yet")
        if not self._configured():
            return SkillResult.fail(
                "NOT_CONFIGURED", "ROBOMOO_URL / ROBOT_INGEST_TOKEN not set"
            )

        # Snapshot the frame + pose now so the background upload sends exactly what
        # the robot saw at call time, not a later frame.
        pose = getattr(self, "_pose", None)

        def _bg() -> None:
            try:
                key = self._upload_frame(frame, pose, note=note, label=note)
                logger.info("take_picture uploaded frame key=%s", key)
            except Exception:  # noqa: BLE001 — fire-and-forget: failures only logged
                logger.exception("take_picture upload failed")

        t = threading.Thread(target=_bg, daemon=True, name="take-picture-upload")
        with self._uploads_lock:
            # Drop finished threads so the list doesn't grow unbounded.
            self._uploads = [u for u in self._uploads if u.is_alive()]
            self._uploads.append(t)
        t.start()
        return SkillResult.ok("Picture captured; uploading in the background.")

    @skill
    def tilt_and_capture(
        self,
        pitch_deg: float = -20.0,
        note: str = "",
        settle_s: float = 1.0,
    ) -> SkillResult:
        """Tilt the body to aim the camera, photograph that view, then re-level.

        Use to photograph things above or below the robot's straight-ahead view
        (the camera is body-fixed). NEGATIVE pitch_deg looks UP, positive looks
        DOWN. Runs in the background: tilts, waits `settle_s` for the body to
        settle, captures + uploads the tilted view, then returns the body to
        level. Returns immediately. The robot should be standing first.
        """
        if getattr(self, "_latest", None) is None:
            return SkillResult.fail("NO_FRAME", "No camera frame received yet")
        if not self._configured():
            return SkillResult.fail(
                "NOT_CONFIGURED", "ROBOMOO_URL / ROBOT_INGEST_TOKEN not set"
            )

        def _bg() -> None:
            try:
                self._tilt.tilt_body(pitch_deg=pitch_deg)
                # Wait for the body to physically reach the pose and a fresh
                # camera frame to arrive before snapshotting.
                time.sleep(settle_s)
                key = self._upload_frame(
                    getattr(self, "_latest", None),
                    getattr(self, "_pose", None),
                    note=note,
                    label=note,
                )
                logger.info("tilt_and_capture uploaded frame key=%s", key)
            except Exception:  # noqa: BLE001 — fire-and-forget: failures only logged
                logger.exception("tilt_and_capture failed")
            finally:
                # Always return the body to level, even if capture failed.
                try:
                    self._tilt.tilt_body()
                except Exception:  # noqa: BLE001 — best effort
                    logger.exception("tilt_and_capture re-level failed")

        t = threading.Thread(target=_bg, daemon=True, name="tilt-and-capture")
        with self._uploads_lock:
            self._uploads = [u for u in self._uploads if u.is_alive()]
            self._uploads.append(t)
        t.start()
        return SkillResult.ok(
            f"Tilting to pitch={pitch_deg} deg, capturing, then re-leveling (background)."
        )

    @skill
    def explore_and_capture(
        self,
        interval_s: float = 4.0,
        max_duration_s: float = 600.0,
        note: str = "exploring",
    ) -> SkillResult:
        """Explore the room and keep taking photos until exploration is complete.

        Use when the user asks the robot to explore / wander / look around AND
        take pictures (or capture/photograph) as it goes. Starts autonomous
        frontier exploration, then captures and uploads a frame every
        `interval_s` seconds for as long as the robot is still exploring — it
        stops on its own once the room is fully explored. `max_duration_s` is
        only a safety cap. Returns immediately; capturing runs in the background.
        """
        if not self._configured():
            return SkillResult.fail(
                "NOT_CONFIGURED", "ROBOMOO_URL / ROBOT_INGEST_TOKEN not set"
            )

        # Cancel any in-flight run before starting a new one.
        self._capture_stop.set()
        if self._capture_thread is not None and self._capture_thread.is_alive():
            self._capture_thread.join(timeout=5.0)
        self._capture_stop = threading.Event()

        self.explore_cmd.publish(Bool(data=True))
        self._capture_thread = threading.Thread(
            target=self._capture_loop,
            args=(interval_s, max_duration_s, note),
            daemon=True,
            name="explore-and-capture",
        )
        self._capture_thread.start()

        return SkillResult.ok(
            f"Exploring and capturing a photo every {interval_s:.0f}s until the "
            "room is fully explored."
        )

    def _exploring(self) -> bool:
        try:
            return bool(self._explorer.is_exploration_active())
        except Exception as e:  # noqa: BLE001 — if the ref errors, keep capturing
            logger.warning("is_exploration_active() failed: %s", e)
            return True

    def _capture_loop(self, interval_s: float, max_duration_s: float, note: str) -> None:
        start = time.monotonic()
        grace_s = 6.0  # let exploration spin up before trusting the active flag
        count = 0
        try:
            while not self._capture_stop.is_set():
                elapsed = time.monotonic() - start
                if elapsed > max_duration_s:
                    logger.info("explore_and_capture hit max_duration_s cap")
                    break
                if elapsed > grace_s and not self._exploring():
                    logger.info("exploration finished — stopping capture loop")
                    break
                try:
                    if self._upload_current(note=note, label=note):
                        count += 1
                except Exception as e:  # noqa: BLE001 — keep going on transient errors
                    logger.warning("explore_and_capture upload failed: %s", e)
                self._capture_stop.wait(interval_s)
        finally:
            try:
                self.stop_explore_cmd.publish(Bool(data=True))
            except Exception:  # noqa: BLE001 — best effort on shutdown
                pass
            logger.info("explore_and_capture finished: uploaded %d photos", count)

    @skill
    def room_scan(
        self,
        run_id: str = "",
        positions: int = 3,
        forward_step_m: float = 1.0,
        turn_between_deg: float = 60.0,
        angle_step_deg: float = 10.0,
        settle_s: float = 0.8,
        note: str = "vr_scan",
    ) -> SkillResult:
        """Capture image data to reconstruct the room in VR / 3D.

        At each stop the robot does a full 360-degree sweep, taking one photo
        every `angle_step_deg` degrees (10 -> 36 photos), then moves
        `forward_step_m` meters forward and turns `turn_between_deg` degrees so it
        fans out across the room (rather than walking a straight line), and
        repeats for up to `positions` stops. It stops early if it can't move
        forward (obstacle / navigation failure). Every photo is tagged with the
        run id, the position index and the angle so they can be grouped
        server-side (one panorama per position). Runs in the background and
        returns immediately. The robot should be standing first.
        """
        if getattr(self, "_latest", None) is None:
            return SkillResult.fail("NO_FRAME", "No camera frame received yet")
        if not self._configured():
            return SkillResult.fail(
                "NOT_CONFIGURED", "ROBOMOO_URL / ROBOT_INGEST_TOKEN not set"
            )

        run = run_id or f"scan-{int(time.time())}"

        # Cancel any in-flight scan/explore capture before starting a new one.
        self._capture_stop.set()
        if self._capture_thread is not None and self._capture_thread.is_alive():
            self._capture_thread.join(timeout=5.0)
        self._capture_stop = threading.Event()

        self._capture_thread = threading.Thread(
            target=self._room_scan_loop,
            args=(run, positions, forward_step_m, turn_between_deg, angle_step_deg,
                  settle_s, note),
            daemon=True,
            name="room-scan",
        )
        self._capture_thread.start()

        return SkillResult.ok(
            f"Scanning the room for VR (run={run}): up to {positions} stops, "
            f"{round(360 / angle_step_deg)} photos per stop. Running in the background."
        )

    def _room_scan_loop(
        self,
        run: str,
        positions: int,
        forward_step_m: float,
        turn_between_deg: float,
        angle_step_deg: float,
        settle_s: float,
        note: str,
    ) -> None:
        steps = round(360 / angle_step_deg)
        count = 0
        try:
            for pos in range(positions):
                if self._capture_stop.is_set():
                    break
                for i in range(steps):
                    if self._capture_stop.is_set():
                        return
                    # Hold still so the frame isn't motion-blurred.
                    self._capture_stop.wait(settle_s)
                    angle = i * angle_step_deg
                    try:
                        if self._upload_current(
                            note=note,
                            label=f"{run}/pos{pos:02d}/{int(angle):03d}",
                            extra={
                                "run": run,
                                "position": str(pos),
                                "angle": str(angle),
                                "imageIndex": str(pos * steps + i),
                            },
                        ):
                            count += 1
                    except Exception as e:  # noqa: BLE001 — keep sweeping on transient errors
                        logger.warning("room_scan upload failed: %s", e)
                    # Rotate in place to the next angle (via cmd_vel — the global
                    # planner can't do a heading-only goal). The final increment of
                    # the final stop is skipped (we close the 360 only to continue).
                    if i < steps - 1 or pos < positions - 1:
                        self._rotate_in_place(angle_step_deg)
                # Move to the next stop, then turn to fan out. Translation goes
                # through the planner (real distance); the turn uses cmd_vel. Stop
                # early if the forward move couldn't complete.
                if pos < positions - 1:
                    result = self._move.relative_move(forward=forward_step_m)
                    if "reached" not in result.lower():
                        logger.info("room_scan stopping early: move result %r", result)
                        break
                    self._rotate_in_place(turn_between_deg)
        finally:
            try:
                self.cmd_vel.publish(Twist.zero())
            except Exception:  # noqa: BLE001 — best effort
                pass
            logger.info("room_scan finished (run=%s): uploaded %d photos", run, count)

    def _rotate_in_place(
        self,
        deg: float,
        max_rate: float = 0.6,
        min_rate: float = 0.15,
        tol_deg: float = 3.0,
        timeout_s: float = 12.0,
    ) -> None:
        """Turn the base by `deg` degrees (closed-loop on odom yaw) via cmd_vel.

        +deg turns left (CCW), matching relative_move's convention. Holds the
        loop until the heading is within `tol_deg` or `timeout_s` elapses, then
        stops the base. No-op if there's no odometry yet.
        """
        pose = getattr(self, "_pose", None)
        if pose is None:
            logger.warning("room_scan rotate skipped: no odometry yet")
            return
        target = pose.yaw + math.radians(deg)
        deadline = time.monotonic() + timeout_s
        tol = math.radians(tol_deg)
        try:
            while not self._capture_stop.is_set():
                cur = getattr(self, "_pose", None)
                cur_yaw = cur.yaw if cur is not None else target
                # Shortest signed angular error in (-pi, pi].
                err = math.atan2(math.sin(target - cur_yaw), math.cos(target - cur_yaw))
                if abs(err) <= tol or time.monotonic() > deadline:
                    break
                # Proportional, clamped, with a floor so it doesn't stall near zero.
                rate = max(min_rate, min(max_rate, abs(err) * 1.5))
                wz = math.copysign(rate, err)
                self.cmd_vel.publish(Twist(linear=[0.0, 0.0, 0.0], angular=[0.0, 0.0, wz]))
                self._capture_stop.wait(0.05)
        finally:
            self.cmd_vel.publish(Twist.zero())
