// DimosTopics — the typed registry of known DimOS core topics, by *canonical*
// (transport-independent) name. `client.topic("/odom")` and the React hooks
// resolve message types from this by default.
//
// Consumers extend it by composing their OWN map — no `declare module`:
//   type AppTopics = DimosTopics & { "/myapp/state": myapp.State };
//   const client = await connect<AppTopics>({ url });
//   const { useTopicLatest } = createDimosReact<AppTopics>();
import type {
  PointStamped,
  PoseStamped,
  Twist,
} from "@dimos/msgs/geometry_msgs";
import type { OccupancyGrid, Path } from "@dimos/msgs/nav_msgs";
import type { CameraInfo, Image, PointCloud2 } from "@dimos/msgs/sensor_msgs";
import type { Bool } from "@dimos/msgs/std_msgs";
import type { TFMessage } from "@dimos/msgs/tf2_msgs";

export interface DimosTopics {
  "/odom": PoseStamped;
  "/cmd_vel": Twist;
  "/nav_cmd_vel": Twist;
  "/lidar": PointCloud2;
  "/global_map": PointCloud2;
  "/color_image": Image;
  "/camera_info": CameraInfo;
  "/tf": TFMessage;
  "/global_costmap": OccupancyGrid;
  "/path": Path;
  "/goal": PointStamped;
  "/way_point": PointStamped;
  "/clicked_point": PointStamped;
  "/goal_reached": Bool;
}

/** A message class (has `static decode`) — for the `topic(name, Class)` form. */
export type MsgClass<T> = { decode(data: Uint8Array): T };
