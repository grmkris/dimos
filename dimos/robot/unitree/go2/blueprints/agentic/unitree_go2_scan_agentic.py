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

"""unitree-go2-scan-agentic — LiDAR-aware Gaussian-splat scanning blueprint.

Composes the existing `unitree_go2_agentic_gemini` agentic stack with:

  * `FastLio2` (Mid-360 LiDAR-inertial odometry, native module) — publishes
    drift-bounded `odom` (full 6-DoF PoseStamped) + accumulated `global_map`
    (PointCloud2) at 3 Hz. Replaces the raw `/odom` source the gemini
    blueprint uses; the rest of the graph reads the same stream name and
    doesn't notice.
  * `RoomScanSkill` (new) — agent-callable @skill that opens a scan window,
    POSTs each color_image with full 6-DoF pose to robomoo's
    `/api/robot/frame` (the 6-DoF cols added in robohack PR #20), and at
    `stop_scan` POSTs the accumulated voxel cloud + the per-frame pose
    batch to `/api/robot/pointcloud` + `/api/robot/poses`. That is the
    producer side of the Tier-A LiDAR-splat path
    ([direction-c/07](https://github.com/grmkris/robohack/blob/master/direction-c/07-lidar-splat-plan.md)).

End-to-end demo loop this enables:

    dimos run unitree-go2-scan-agentic
    dimos agent-send "start a scan, walk the apartment, then stop scan"
    # → agent calls RoomScanSkill.start_scan, drives motion via
    #   TakePictureSkill.room_scan or relative_move, then
    #   RoomScanSkill.stop_scan posts cloud + poses
    # → gs-pot mode=lidar pulls the run, writes COLMAP-bin via
    #   lidar_poses.write_colmap_workspace, trains with Brush, pushes
    #   the .ply back. View Splat in robohack /splats renders the
    #   apartment walkthrough.

Hardware/sim:
  * Real Mid-360 over UDP (FastLio2Config `host_ip`/`lidar_ip`) for live.
  * `dimos --replay <recording.db>` for offline dev — needs a `.db` with
    color_image + lidar streams (DimOS upstream PR #2266 ships
    `mid360_sample.db`).
  * NOT compatible with `dimos --simulation` — MuJoCo Go2 has no Mid-360.

Env required (same contract as TakePictureSkill / MapUploader):

    ROBOMOO_URL=https://gateway-...up.railway.app
    ROBOT_INGEST_TOKEN=<secret matching robomoo's server>
    GOOGLE_API_KEY=<for the gemini agent brain + TTS + detection>

The gemini base disables `SecurityModule` (CUDA-only) and `SpeakSkill`
(OpenAI-only) so this blueprint also boots on Apple Silicon with no
CUDA — which is the target venue laptop.
"""

from dimos.agents.skills.room_scan_skill import RoomScanSkill
from dimos.core.coordination.blueprints import autoconnect
from dimos.hardware.sensors.lidar.fastlio2.module import FastLio2
from dimos.robot.unitree.go2.blueprints.agentic.unitree_go2_agentic_gemini import (
    unitree_go2_agentic_gemini,
)

# FastLio2 with `map_freq=3.0` so the `global_map` cloud actually publishes
# every ~0.3 s. RoomScanSkill subscribes to global_map and caches the
# latest cloud for upload at stop_scan; with map_freq=-1 (default) the
# cloud stream is silent and stop_scan would upload an empty PLY.
_VOXEL_M = 0.05  # match gs-pot's `lidar_poses.write_colmap_workspace` default

unitree_go2_scan_agentic = autoconnect(
    unitree_go2_agentic_gemini,
    FastLio2.blueprint(
        voxel_size=_VOXEL_M,
        map_voxel_size=_VOXEL_M,
        map_freq=3.0,
    ),
    RoomScanSkill.blueprint(),
).global_config(robot_model="mid360_fastlio2")

__all__ = ["unitree_go2_scan_agentic"]
