// teleop — drive the robot safely. `client.teleop()` is structured velocity, and the gateway
// clamps it + runs a TTL/deadman watchdog, so a dropped connection (or a missed refresh) stops
// the robot. Sustain the command faster than the TTL to keep moving.
//
// RUN (with a gateway + a robot — e.g. dimoscope's servers/start-all.sh + examples/simplerobot):
//   GATEWAY_URL=ws://localhost:8089 bun run index.ts
import { connect } from "@dimos/topics";

const url = process.env.GATEWAY_URL ?? "ws://localhost:8089";
const client = await connect({ url });
console.log(`connected → ${url} — driving forward 0.4 m/s for 3s`);

// 10 Hz refresh, each with a 300ms TTL → the deadman never trips while we drive.
const id = setInterval(() => client.teleop(0.4, 0, 300), 100);

setTimeout(() => {
  clearInterval(id);
  client.stop(); // zero velocity (also what the deadman would do on disconnect)
  console.log("stopped.");
  client.close();
  process.exit(0);
}, 3000);
