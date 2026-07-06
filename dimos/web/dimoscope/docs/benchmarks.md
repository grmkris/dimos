# dimoscope Benchmarks, QoS, and Runbook

This is the canonical benchmark record for dimoscope. It keeps the current conclusions and enough
methodology to reproduce them; dated raw run logs were folded into this page.

The load source is `go2-load` (`dimos/robot/benchmark/go2_load.py`): small `/load/{fast,mid,slow}`
lanes, structured `/load/{grid,cloud}`, and a crankable `/load/img` flood controlled by
`GO2Load.start_bench` / `stop_bench`.

```bash
cd dimos/web/dimoscope
deno install && deno task build
deno task serve   # gateway + WT/WebRTC sidecar
deno task load    # /load/* source
# open http://localhost:8080/ -> Topics tab -> Benchmark drawer
```

## Current Verdict

| Workload | WebTransport | WebSocket | WebRTC data |
| --- | ---: | ---: | ---: |
| Clean bulk | 18-19 MB/s | 11-14 MB/s | 2-3 MB/s |
| 5% random loss | 9-11 MB/s | collapses without BBR | near zero |
| Fast lane beside dense flood | p95 26 ms clean; 278-471 ms on shaped links | can collapse behind the TCP pipe | parity on shaped links; poor under loss |
| Camera | data path only | JPEG fallback | preferred media path |

Recommendation: `Auto` should prefer WebTransport for data, fall back to WebSocket for reachability,
and use WebRTC for camera media. The remaining reason to expose WebRTC data is comparison, UDP-path
coverage, and browser-to-browser style future work.

## Browser Benchmark

The app's Benchmark drawer measures publish-to-browser latency in the real browser. Each sweep can
vary:

- transport: WebSocket, WebTransport, WebRTC data, SSE, poll.
- network profile: clean, wifi-normal, wifi-crowded, loss-only profiles, or custom netem.
- workload: pose lanes, bulk floods, cloud variants, and co-existence rows (`+pose` beside floods).
- maxHz and repeat count.

Rows report delivered Hz, kB/s, delivery/loss, p50/p95/p99 latency, fast-lane p95 for multi-lane
rows, and the actual wire used. A warmup window removes subscription ramp-up and last-value replay.
An NTP-style ping probe corrects clock offset for cross-machine runs.

Useful URL parameters:

```text
?gw=host:port
?transport=webtransport|ws|webrtc|sse|poll|auto
?profiles=pose,dense,lidar
?coex=1
?net=clean,wifi-crowded,loss-5
?dur=15000
?maxHz=0,60
?run=1
```

## QoS Model

QoS is enforced at the browser egress, where robot bus QoS cannot help. Defaults classify topics into
four lanes; client declarations and operator rules can override them.

| Lane | Reliability | Priority | Behavior under load | Examples |
| --- | --- | ---: | --- | --- |
| command | reliable | highest | never intentionally dropped | teleop, goals, RPC control |
| sensor | best-effort | high | latest wins | pose, odom, tf, joints |
| default | reliable | normal | bounded queue | normal topics |
| bulk | best-effort | low | conflates and sheds first | images, lidar, maps, point clouds |

The gateway priority outbox uses weighted round-robin across lanes and latest-only slots for
best-effort bulk topics. WebTransport reinforces this by putting small fresh state on datagrams and
large frames on reliable streams. WebSocket bounds its kernel send buffer so WAN backlog stays in the
gateway outbox instead of becoming an opaque FIFO.

Measured on a roughly 4 Mbps shaped link with pose beside a heavy stream:

| Mode | Pose Hz | Pose p50 | Pose p95 | Heavy Hz |
| --- | ---: | ---: | ---: | ---: |
| FIFO | 55 | 1294 ms | 2419 ms | 120 |
| Priority outbox | 99.5 | 4 ms | 9 ms | 116 |

Operator overrides live in `qos.rules.json` / `QOS_RULES`. The gateway and Rust sidecar both read the
same rule file so the default lane is consistent across wires; client `setQos` still wins per
subscription.

## WebTransport Credit Gate

The Rust sidecar uses a browser-acknowledged bulk credit gate. The browser reports consumed
bulk-stream bytes; the sidecar keeps outstanding reliable bulk near `ack_rate * WT_BULK_TARGET_MS`
with a small floor. This prevents rate-capped links from building seconds of reliable-stream backlog
while preserving clean-path throughput.

Fast-lane p95 beside a flood, WebTransport gate off vs on:

| Network | Flood | Gate off | Gate on | Change |
| --- | --- | ---: | ---: | ---: |
| clean | dense+pose | 25.6 ms | 26.4 ms | unchanged |
| wifi-normal | dense+pose | 1283 ms | 278 ms | -78% |
| wifi-crowded | dense+pose | 6884 ms | 471 ms | -93% |
| loss-5 | dense+pose | 124 ms | 131 ms | unchanged |

With the gate on, WebTransport matches WebRTC's fast-lane freshness on shaped links while keeping
about 9.5x the clean bulk throughput and a large advantage under random loss.

## Point Clouds

Raw `PointCloud2` is too large for many browser links: a 20k-point cloud is about 320 KB/frame, or
3.2 MB/s at 10 Hz. The gateway cloud plane republishes browser-friendly sibling topics:

- `<topic>_ds`: stride-decimated standard `PointCloud2`.
- `<topic>_draco`: full-point-count Draco geometry on `draco.PointCloud2`.

Clean localhost measurements at 10 Hz:

| Transport | Variant | Hz | kB/s | Size vs raw | p50 |
| --- | --- | ---: | ---: | ---: | ---: |
| WS | raw cloud | 9.33 | 2917 | 1.0x | 1.8 ms |
| WS | `_ds` | 9.33 | 293 | 10.0x smaller | 2.2 ms |
| WS | `_draco` | 9.27 | 477 | 6.1x smaller | 9.8 ms |
| WT | raw cloud | 9.33 | 2918 | 1.0x | 3.5 ms |
| WT | `_ds` | 9.33 | 293 | 10.0x smaller | 1.9 ms |
| WT | `_draco` | 9.33 | 481 | 6.1x smaller | 9.4 ms |

On a structured lidar scan, Draco measured about 7.4x smaller while preserving the full point count.
The Clouds tab renders raw, downsampled, and Draco versions side-by-side in a shared three.js orbit
view; WorldView can switch lidar between raw, `_ds`, and `_draco`.

## Camera Latency

Raw Go2 camera frames are about 2.76 MB at 14 Hz, or roughly 39 MB/s. Loopback hides that cost; a
real 100 Mbit path does not. The gateway image/media fixes are:

- republish raw `Image` as `<topic>_jpeg` with TurboJPEG.
- use freshest-wins ingest for media, image, and cloud transcode planes.
- keep one client-side JPEG decode in flight.
- set WebRTC receiver playout/jitter hints to zero for low-latency robot video.
- choose WebCodecs first when available, then WebRTC media, then JPEG.

Measured on a 100 Mbit throttled link:

| Mode | Before | After |
| --- | --- | --- |
| JPEG topic | 3.3 fps, 387-502 ms rising, link saturated | 14.2 fps, about 8 ms flat, about 1 MB/s |
| WebCodecs | 14 fps, about 20 ms | 14.3 fps, about 13 ms |
| WebRTC media | 12.7 fps, 46-71 ms jitter buffer | 14.2 fps, 9-19 ms jitter buffer |
| Auto | WebRTC | WebCodecs when supported |

## Network Shaping

`NETEM_CTL=1` enables `/netem` on Linux when the `dimos-netem` wrapper is installed:

```bash
deno task netem:install
sudo dimos-netem wifi-crowded
curl -X POST http://<gw>:8080/netem -H 'content-type: application/json' -d '{"profile":"loss-5"}'
curl http://<gw>:8080/netem
```

Profiles shape gateway egress: TCP `:8080` plus all egress UDP used by WebTransport and WebRTC. SSH
is left untouched. Apply loss after transports connect; QUIC handshakes are expected to be fragile
under packet loss.

## VPS Runbook

Open firewall ports:

```bash
sudo ufw allow 8080/tcp
sudo ufw allow 8443/udp
sudo ufw allow 8444/udp
```

Install and run:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
GIT_LFS_SKIP_SMUDGE=1 git clone <your-dimos-remote> && cd dimos
uv sync --extra unitree --extra sim --extra mapping

cd dimos/web/dimoscope
deno install && deno task build
cargo build --release --manifest-path gateway/wt-sidecar/Cargo.toml

DIMOS_TRANSPORT=zenoh uv run python -m dimos.web.dimoscope.gateway &
gateway/wt-sidecar/target/release/wt-sidecar &
DIMOS_TRANSPORT=zenoh DIMSIM_RENDER=cpu uv run dimos --simulation dimsim run go2-load &
```

From a local machine:

```bash
cd dimos/web/dimoscope
deno task app
# open http://localhost:5173/?gw=<vps-host>:8080
```

Serve the page from localhost for WebTransport during raw-IP testing; the app fetches the sidecar cert
hash from `/cert`.

## Environment Reference

| Env | Default | Purpose |
| --- | --- | --- |
| `HOST` / `PORT` | `0.0.0.0` / `8080` | HTTP/WS bind |
| `WT_PORT` | `8443` | WebTransport UDP port |
| `RTC_PORT` | `8444` | WebRTC UDP port |
| `RTC_PUBLIC_IP` | off | ICE candidate override for NAT/macOS local testing |
| `WT_PIPE` | `/tmp/dimoscope-wt.sock` | gateway-sidecar unix socket |
| `WT_CERT_HASH_FILE` | `/tmp/dimoscope-wt-cert.hash` | cert hash served by `/cert` |
| `EGRESS_KBPS` | off | explicit per-client egress pacer |
| `WT_SEND_WINDOW` | `1500000` | bound QUIC reliable-stream buffering |
| `WT_DGRAM_TTL_MS` | `200` | drop stale datagrams at drain time |
| `WT_DGRAM_BUF` | `16384` | QUIC datagram send buffer |
| `WT_BULK_TARGET_MS` | `250` | receiver-acked bulk queue target |
| `WT_BULK_MIN` | `65536` | bulk credit floor |
| `IMAGE_JPEG` / `IMAGE_JPEG_QUALITY` | `1` / `75` | JPEG sibling topic generation |
| `RUNS_CTL` | off | enable `/runs` start/stop control |
| `WS_SNDBUF` | `262144` | bound WebSocket kernel send buffer |
| `WS_DEFLATE` | off | enable WebSocket permessage-deflate |
| `QOS_RULES` | `qos.rules.json` | operator topic/type lane rules |
| `NETEM_CTL` | off | enable `/netem` |
| `ZENOH_KEY` | `**` | zenoh subscription key expression |
| `DIMOS_LCM_HOST` / `DIMOS_LCM_PORT` | `239.255.76.67` / `7667` | LCM multicast group |
| `STATIC_DIR` | `app/dist` | app bundle served at `/` |

## Checks

```bash
deno task check
deno task test
uv run pytest dimos/web/dimoscope/gateway/tests -q
```
