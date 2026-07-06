# Bench results — 2026-07-07, real WAN (Mac ↔ company VPS), post WT-video/ABR

Setup: browser = headless Chrome-for-Testing on a Mac (scripts/bench-headless.ts, anti-throttle
flags), gateway + wt-sidecar + `deno task dog:vps` (MuJoCo headless/EGL, video 5 fps, lidar 1 fps)
on the company VPS (4 vCPU Debian, ~25 ms RTT, netem on the box via `NETEM_CTL=1`). Branch head
`73c4039e2` (includes H.264-over-WT media, ABR, stream-per-frame, smooth-playout). App served by the
local gateway, `?gw=` pointed at the VPS; one 15 s cell per row, netem profiles applied server-side.

Reproduce any row: `deno run -A scripts/bench-headless.ts "<url>"` with

```text
http://localhost:8080/?tab=topics&gw=GW-HOST%3A8080&transport=<webtransport|ws|webrtc>&profiles=pose%2Clidar%2Cdense&coex=1&net=clean%2Cwifi-normal%2Cwifi-crowded%2Closs-5&dur=15000&run=1
http://localhost:8080/?tab=topics&gw=GW-HOST%3A8080&transport=<webtransport|ws>&profiles=cloud%2Ccloud-ds%2Ccloud-draco&net=clean%2Closs-5&dur=15000&run=1
deno task bench-video "http://localhost:8080/?gw=GW-HOST%3A8080" 45 jpeg,webcodecs,auto
```

## 1 · Transport matrix (pose · lidar+pose · dense+pose × 4 network profiles)

Columns: delivered hz · wire kB/s · delivery % · e2e p50/p95 ms · fast-lane p95 (×late-factor).
The ~12 % "loss" on clean pose cells is the known conflation-measurement artifact — uniform across
transports, so comparisons hold.

### WebTransport (WT-rs sidecar)
| net | scenario | hz | kB/s | deliv% | p50 | p95 | fast p95 |
|---|---|---:|---:|---:|---:|---:|---:|
| clean | pose | 97 | 8 | 88 | 15 | 28 | 23 |
| clean | lidar+pose | 106 | 1933 | 88 | 15 | 42 | 29×1.2 |
| clean | dense+pose | 112 | **18864** | 88 | 20 | 95 | 37×1.6 |
| wifi-normal | dense+pose | 97 | 1114 | 76 | 242 | 308 | 290×2.3 |
| wifi-crowded | dense+pose | 96 | 216 | 78 | 330 | 476 | 472×1.1 |
| loss-5 | pose | 90 | 8 | 81 | 56 | 70 | 66 |
| loss-5 | dense+pose | 99 | **8916** | 76 | 97 | 342 | 132×2.0 |

### WebSocket
| net | scenario | hz | kB/s | deliv% | p50 | p95 | fast p95 |
|---|---|---:|---:|---:|---:|---:|---:|
| clean | pose | 98 | 8 | 89 | 14 | 28 | 24 |
| clean | dense+pose | 35 | 10536 | **27** | 59 | 176 | 65×2.6 |
| wifi-normal | dense+pose | 2 | 455 | **2** | 829 | 2834 | 966×13 |
| wifi-crowded | dense+pose | 1 | 143 | **1** | 2767 | 6972 | 2869×4.3 |
| loss-5 | pose | 89 | 7 | 87 | 67 | 158 | 155 |
| loss-5 | lidar+pose | 3 | 91 | **3** | 1509 | 4831 | 4268×27.5 |

### WebRTC data (rtc-rs sidecar, RTC_PUBLIC_IP set)
| net | scenario | hz | kB/s | deliv% | p50 | p95 | fast p95 |
|---|---|---:|---:|---:|---:|---:|---:|
| clean | pose | 95 | 8 | 86 | 15 | 30 | 24 |
| clean | dense+pose | 95 | 1958 | 74 | 20 | 52 | 45×1.9 |
| wifi-normal | dense+pose | 98 | 346 | 78 | 147 | 257 | 255×3.3 |
| wifi-crowded | dense+pose | 93 | 151 | 79 | 370 | 496 | 495×1.1 |
| loss-5 | pose | 89 | 8 | 72 | 628 | **2588** | 2578 |
| loss-5 | dense+pose | 77 | 32 | 74 | 450 | 1140 | 1120 |

Reading: WT is the only wire that carries bulk everywhere — 18.9 MB/s clean, 8.9 MB/s at 5 % loss —
while its pose lane stays double-digit-ms beside the flood. WS matches WT on a clean pose-only link
and collapses the moment bulk or loss appears (TCP HoL: 1-3 % delivery, pose ×13-27 late behind the
backlog). WebRTC keeps pose parity on shaped links (per-message SCTP) but bulk ceilings ~2 MB/s and
5 % loss pushes even its pose p95 to 2.6 s.

## 2 · Large streams: point-cloud raw vs `_ds` vs `_draco` (clean · loss-5)

| wire | net | variant | hz | kB/s | deliv% | p50 | p95 |
|---|---|---|---:|---:|---:|---:|---:|
| WT | clean | cloud (raw) | 9.9 | 3084 | 100 | 4 | 21 |
| WT | clean | cloud-ds | 9.8 | 307 | 99 | 5 | 51 |
| WT | clean | cloud-draco | 9.9 | 508 | 100 | 33 | 53 |
| WT | loss-5 | cloud (raw) | 9.9 | 3084 | 99 | 136 | 269 |
| WT | loss-5 | cloud-ds | 9.8 | 307 | 99 | 70 | 213 |
| WT | loss-5 | cloud-draco | 9.4 | 484 | 95 | 97 | 240 |
| WS | clean | cloud (raw) | 9.8 | 3063 | 99 | 2 | 30 |
| WS | loss-5 | cloud (raw) | 0.3 | 83 | **4** | 2583 | 4145 |
| WS | loss-5 | cloud-ds | 2.7 | 84 | 70 | 2646 | 4094 |
| WS | loss-5 | cloud-draco | 0.8 | 41 | 100 | 1525 | 4857 |

Reading: on QUIC, loss costs latency (p95 ~0.25 s) but not throughput — even the raw 3 MB/s cloud
keeps 99 % delivery. On TCP, loss kills the stream regardless of compression: the 10× smaller `_ds`
still crawls at 2.7 Hz with 4 s p95. Compression helps bandwidth; only the transport fixes loss.

## 3 · Camera video over the WAN (scripts/video-bench.ts, 45 s per mode)

Source: MuJoCo headless camera on the VPS — 4 vCPU EGL render sustains ~3.5-3.9 fps of the 5 fps
target, so all modes are source-limited; the transport column to read is AGE.

| mode | draw fps | glass-to-glass age |
|---|---:|---:|
| jpeg (WS data plane, q92) | 3.4-3.7 | 45-53 ms |
| webcodecs (H.264/WT → WS fallback chain) | 3.5-3.7 | 23-73 ms (one 788 ms resync blip) |
| auto (→ webcodecs) | 3.5-3.9 | 23-30 ms |

Reading: over a 25 ms-RTT WAN the H.264 path shows ~25-70 ms of glass-to-glass age — encode + wire +
decode adds only a few tens of ms over the RTT floor. The single 788 ms spike in the webcodecs run is
a shed→IDR resync (the ABR/pressure path doing its job); the smooth-playout toggle (`?smooth=150`)
trades that spikiness for a constant 150 ms when watching replays. webrtc video mode is excluded:
gateway-side media WebRTC does not ICE over a raw-IP WAN (documented; use jpeg/webcodecs there).
