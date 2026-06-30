# @dimos/topics

DimOS topics in the browser — a transport-agnostic **subscribe → visualize → teleop** SDK.
The bus is self-describing (`<topic>#<type>` + an 8-byte type hash), so `@dimos/msgs` decodes
each message to a real typed object at runtime; this package wraps that in a small client with
topic discovery, per-topic stats/latency, and safe robot control.

## Install

```sh
bun add @dimos/topics      # or: npm i @dimos/topics
```

Browser, no bundler:

```html
<script type="module">
  import { connect } from "https://esm.sh/@dimos/topics";
</script>
```

## 60-second quickstart

```ts
import { connect } from "@dimos/topics";

const client = await connect({ url: "ws://localhost:8089" }); // Bun↔LCM gateway

// Known DimOS topics are typed from `DimosTopics` — `/odom` infers PoseStamped:
client.topic("/odom").subscribeLatest((pose, meta) => {
  console.log(pose.pose.position.x, `${meta.latencyMs?.toFixed(1)} ms`);
});

// Anything discovered on the bus:
for (const { topic, type } of client.listTopics()) console.log(topic, type);
```

## Typed topics

The ~14 core DimOS topics are mapped in `DimosTopics`, so `client.topic(name)` is fully typed
with autocomplete. Unknown/app topics stay dynamic (`unknown`), or you type them inline:

```ts
import type { sensor_msgs } from "@dimos/msgs";

client.topic("/cmd_vel"); // Twist (from DimosTopics)
client.topic<sensor_msgs.PointCloud2>("/my/lidar"); // explicit type
client.topic("/whatever"); // Topic<unknown>
```

Bring your own topic map — no `declare module`, just compose and pass it to `connect`:

```ts
import { connect, type DimosTopics } from "@dimos/topics";
import type { myapp } from "@myapp/msgs";

type AppTopics = DimosTopics & { "/myapp/status": myapp.Status };
const client = await connect<AppTopics>({ url });
client.topic("/myapp/status"); // Topic<myapp.Status>
```

## Control — teleop & navigation

Velocity and goals are structured and **safe**: the gateway clamps values and runs a TTL
watchdog, so a dropped connection stops the robot.

```ts
client.teleop(0.5, 0.0, 300); // linearX m/s, angularZ rad/s, TTL ms
client.stop(); // zero velocity
client.navigate(2.0, 1.5); // world-frame goal (metres) → PointStamped
```

## Transports

`connect()` defaults to a WebSocket gateway; any object implementing `Transport` works.
DimOS ships three:

| Gateway         | URL               | Topic names                                                                                         |
| --------------- | ----------------- | --------------------------------------------------------------------------------------------------- |
| Bun↔LCM         | `ws://host:8089`  | bare (`/odom`)                                                                                      |
| Python↔Zenoh    | `ws://host:8088`  | namespaced (`/dimos/odom`) — pass `connect({ namespace: "dimos" })` to canonicalize back to `/odom` |
| zenoh-ts direct | `ws://host:10000` | via the remote-api bridge                                                                           |

`namespace` makes topic names transport-independent, so `DimosTopics` keys and your app code
don't change when you switch gateways.

## API

- `connect(opts) => Promise<DimosClient>` — `opts`: `{ url?, transport?, reconnect?, namespace? }`.
- `client.topic(name)` — typed/dynamic handle; `.subscribeLatest((data, meta) => …)`, `.stats()`.
- `client.listTopics()` / `client.onTopics(cb)` — discovery (canonical names).
- `client.status` / `client.onStatus(cb)` — connection state; `client.gatewayLabel`.
- `client.teleop(linearX, angularZ, ttlMs?)`, `client.stop()`, `client.navigate(x, y, z?)`.
- `client.close()`.

`meta` carries `{ latencyMs, recvTs, srcTs, sizeBytes, type, topic, dropped }` — `latencyMs` is
true transport latency (gateway-send → browser-recv) when available, else source-stamp age.

## React

Use [`@dimos/react`](../react) for hooks (`useTopics`, `useTopicLatest`, `useStatus`, …), a
typed-hooks factory (`createDimosReact<AppTopics>()`), and a pluggable widget registry
(`registerWidget(type, Component)`).
