// hello-topics — the 60-second @dimos/topics example: connect, discover, subscribe, print.
//
// RUN (with a gateway + a data source up — e.g. dimoscope's servers/start-all.sh +
//      examples/simplerobot):
//   GATEWAY_URL=ws://localhost:8089 bun run index.ts
import { connect } from "@dimos/topics";
import type { DimosTopics } from "@dimos/topics";

const url = process.env.GATEWAY_URL ?? "ws://localhost:8089";
const client = await connect({ url });
console.log(`connected → ${url}`);

// 1) Discover what's on the bus (the gateway reports it; decode is by 8-byte type hash).
setTimeout(() => {
  console.log("topics:");
  for (const { topic, type } of client.listTopics()) {
    console.log(`  ${topic}  (${type})`);
  }
}, 1000);

// 2) Subscribe to odometry — typed as geometry_msgs.PoseStamped via the DimosTopics
//    registry (explicit type param; or compose your own map for app topics).
client.topic<DimosTopics["/odom"]>("/odom").subscribeLatest((pose, meta) => {
  const { x, y } = pose.pose.position;
  const lat = meta.latencyMs?.toFixed(1) ?? "?";
  console.log(`/odom  x=${x.toFixed(2)} y=${y.toFixed(2)}  (${lat} ms)`);
});

// Stop after 10s so the example exits cleanly.
setTimeout(() => {
  client.close();
  process.exit(0);
}, 10_000);
