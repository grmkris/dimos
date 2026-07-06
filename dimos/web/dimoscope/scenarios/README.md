# Scenario Publishers

The scenario publishers provide three real-world topic profiles for dimoscope: navigation,
manipulation, and perception. They are regular DimOS modules, so the gateway discovers them without
scenario-specific app code.

| Scenario | Namespace | Main topics | Stress axis | Primary viewer |
| --- | --- | --- | --- | --- |
| `nav` | `/nav/*` | pose, path, cloud, map | mixed size/QoS | WorldView |
| `arm` | `/arm/*` | joint states, ee pose, imu, trajectory | high message rate | stream cards |
| `cam` | `/cam/*` | rgb, depth, points, detections | bandwidth/bufferbloat | Camera + WorldView |

## Run

Start the gateway and app from `dimos/web/dimoscope`:

```bash
deno task serve
deno task app
```

Run one publisher in another terminal:

```bash
./scenarios/run.sh nav
./scenarios/run.sh arm
./scenarios/run.sh cam
```

Open http://localhost:5173. The sidebar discovers live topics; WorldView renders spatial topics,
CameraView shows `/cam/rgb`, and the Topics tab shows rate/latency stream cards.

`DIMOS_TRANSPORT=zenoh` is the default and matches the dimoscope tasks. `DIMOS_TRANSPORT=lcm` also
works because the gateway taps both buses.

## Switching Scenarios

Stop one scenario and start another to change the live data. The gateway discovery registry does not
evict old topic names during a process lifetime, so restart `deno task serve` when you want a pristine
topic list or deterministic first-topic selection.

## Types

`deno task gen-types` reads these sources plus `go2_load.py` and writes
`app/src/dimos.topics.gen.ts`. Details are in [`../packages/web/README.md`](../packages/web/README.md).

## Benchmarking

Run a scenario, then use the app's Topics tab -> Benchmark drawer. The three scenarios exercise
different axes:

- `nav`: about 1-2 MB/s with mixed small and bulk topics.
- `arm`: many small messages per second.
- `cam`: heavy image/depth/point-cloud traffic.

For the standard synthetic benchmark source, use `deno task scope:bench` or `deno task load`.

## Remote

Run the gateway and a scenario on the remote machine, then open:

```text
http://localhost:5173/?gw=<host>:8080
```

Expose TCP `8080` and, for UDP transports, `8443/udp` and `8444/udp`.

## Files

```text
common.py       shared helpers
nav.py          navigation publisher
arm.py          manipulation publisher
cam.py          perception publisher
bench.py        standalone /load/* publisher
run.sh          scenario launcher
```
