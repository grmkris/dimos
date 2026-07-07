# dimoscope - DimOS topics in the browser

`dimoscope` is a browser SDK, gateway, and reference app for DimOS topics. It subscribes to
LCM/Zenoh topics, decodes DimOS messages in the browser with `@dimos/msgs`, visualizes robot state,
and routes teleop/RPC through a server-side safety boundary.

The useful split is:

- `@dimos/web`: transport-agnostic TypeScript client.
- `@dimos/react`: React hooks around the client.
- Python gateway: FastAPI service, bus tap, topic discovery, QoS, media/cloud transcodes, teleop/RPC.
- Rust sidecar: WebTransport and WebRTC data egress over UDP.
- React app: reference cockpit with WorldView, camera, clouds, topic streams, teleop, and benchmarks.

## Quickstart

Prereqs: `uv`, Deno 2.x, Rust, and Chrome/Edge for WebTransport. Other browsers use WebSocket.

From the repo root:

```bash
uv sync --extra web
cd dimos/web/dimoscope
deno install && deno task build

deno task serve   # gateway + WT/WebRTC sidecar -> http://localhost:8080/
deno task load    # synthetic /load/* data source
```

Open http://localhost:8080/. Topics appear in the sidebar and the Topics tab shows per-topic rate,
bandwidth, latency, and QoS controls.

For a simulated Go2 with teleop, camera, lidar, and the same load lanes:

```bash
uv sync --extra web --extra unitree --extra sim --extra mapping
cd dimos/web/dimoscope
deno task dog
```

WASD drives through the gateway deadman; closing the tab stops the robot.

## SDK in 15 lines

```ts
import { createDimosClient } from "@dimos/web";

const client = createDimosClient();
await client.connect("ws://localhost:8080");

console.table(client.listTopics());

const sub = client.subscribe("/load/cloud", (m) => {
  console.log(m.data, m.meta.latencyMs);
});

client.setQos("/load/cloud", {
  maxHz: 2,
  priority: "low",
  reliability: "best-effort",
});

const one = await client.peek("/load/grid", { timeoutMs: 2000 });
sub.unsubscribe();
```

Also available: `client.teleop(lin, ang)`, `client.subscribeAll(cb)`, `client.topic(name)`,
`client.modules.<Module>.<rpc>()`, and typed clients generated from blueprint sources. See
[`packages/web/README.md`](packages/web/README.md) for typed topic/RPC codegen and
[`app/README.md`](app/README.md) for the reference app and React guide.

## Gateway and Transports

The gateway taps both LCM and Zenoh, normalizes messages, and fans them out over one service:

| Wire | Path | Purpose |
| --- | --- | --- |
| WebSocket | `/ws` | Universal duplex fallback; topics, teleop, goal, RPC |
| WebTransport | UDP `:8443` | Preferred data path; QUIC streams + datagrams, no TCP head-of-line |
| WebRTC data | `/rtc` + UDP `:8444` | Data-channel comparison path and UDP fallback |
| SSE | `/sse` | Server-to-client baseline |
| HTTP poll | `/poll` | Request/response baseline |
| Media | `/media` | Camera via WebCodecs, WebRTC media, or JPEG topic fallback |

Selecting the WebRTC transport needs the sidecar to advertise a reachable ICE candidate:
`RTC_PUBLIC_IP=127.0.0.1 deno task serve` for same-machine testing (macOS especially), or the host's
public IP on a NATed/multi-NIC box. Without it the DataChannel silently fails to connect.

Derived topics keep heavy browser paths practical:

- `sensor_msgs.Image` -> `<topic>_jpeg` through TurboJPEG.
- `sensor_msgs.PointCloud2` -> `<topic>_ds` and `<topic>_draco`.

All teleop, goal, and RPC traffic goes through `SafetyEgress`: velocity clamps, TTL deadman,
stop-on-disconnect, and an RPC whitelist.

## Benchmarks

The benchmark runs in the real browser across the transports above. It sweeps network profiles,
workloads, rates, and repeats, then exports Markdown/JSON with reproduce URLs. The current measured
verdict is:

| Scenario | WebTransport | WebSocket | WebRTC data |
| --- | ---: | ---: | ---: |
| Clean bulk | 19 MB/s | 11-14 MB/s | 2-3 MB/s |
| Bulk at 5% loss | 9-11 MB/s | collapses without BBR | near zero |
| Fast lane beside flood | p95 0.28-0.48 s on shaped links | can collapse behind TCP bulk | parity on shaped links, poor under loss |

Use WebTransport for robot data where UDP is available, WebCodecs/H.264 over WebTransport for camera
where available, and WebSocket/WebRTC/JPEG as reachability fallbacks. Full methodology, QoS model,
current transport/video/cloud numbers, VPS runbook, env reference, and copy-paste preset URLs live in
[`docs/benchmarks.md`](docs/benchmarks.md#preset-urls).

## Development

```bash
deno task check
deno task test
uv run pytest dimos/web/dimoscope/gateway/tests -q
deno task fmt && deno task lint
```

Useful docs:

- [`docs/benchmarks.md`](docs/benchmarks.md): measurements, QoS, netem, runbook.
- [`app/README.md`](app/README.md): reference app panels, hooks, and app-building guide.
- [`packages/web/README.md`](packages/web/README.md): SDK, typed topic/RPC codegen, hook surface.
- [`scenarios/README.md`](scenarios/README.md): navigation, arm, camera publisher scenarios.
- [`gateway/wt-sidecar/README.md`](gateway/wt-sidecar/README.md): Rust sidecar notes.

## Caveats

- Safari and Firefox do not provide stable WebTransport. `auto` falls back to WebSocket there, which
  keeps reachability but loses QUIC lane isolation.
- WebTransport and WebRTC data need the Rust sidecar. WS/SSE/poll continue to work without it; `/cert`
  returns 503 until the sidecar writes its certificate hash.
- Auth and TLS are out of scope for this prototype. Treat it as LAN/VPN/VPS-behind-firewall software.
- `@dimos/web` and `@dimos/react` are workspace packages, not published packages yet. Use the
  workspace packages or vendor/alias them as described in [`app/README.md`](app/README.md).
- The SDK intentionally does not fully match the upstream web API proposal yet. Remaining convergence:
  `Dimos.connect(...)`, injectable decode, QoS naming, `m.stream`, and topic allow/deny lists.
- Multi-robot namespacing is not designed here. The gateway currently assumes one logical DimOS topic
  namespace.
