# dimoscope camera latency — raw-Image firehose fixed (2026-07-06)

Headless Chrome (`scripts/video-bench.ts`), 45 s/mode, go2_hongkong_office replay on an M-series
Mac (`dimos --dtop --replay --replay-db go2_hongkong_office run unitree-go2` + `deno task serve`).
The camera topic is raw rgb8 1280×720: **2.76 MB/frame at ~14 Hz ≈ 39 MB/s** — loopback carries
that invisibly, any real network does not, so the "capped" rows run through a 100 Mbit TCP proxy
(`deno task throttle 8081 100 8080`, app at `?gw=localhost:8081`). Latency is the CameraView
header's live readout (`age` = source→draw for frames channels, `jb` = jitter-buffer delay for
webrtc).

## Before / after, 100 Mbit link

| mode | before | after |
|---|---|---|
| jpeg (Image topic) | 3.3 fps · age 387→502 ms **rising** · 10 MB/s (link-saturated) | 14.2 fps · age 8 ms flat · ~1 MB/s |
| webcodecs | 14 fps · age ~20 ms | 14.3 fps · age ~13 ms |
| webrtc (aiortc) | 12.7 fps · jb 46–71 ms | 14.2 fps · jb 9–19 ms |
| auto | negotiated webrtc | negotiates webcodecs |

Loopback (uncapped) before-numbers hid the problem entirely: 14 fps / 16 ms with 43 MB/s on the
wire. The wire budget is the story, not CPU.

## What was wrong (one line each)

1. **No transcode existed** — the "jpeg floor" shipped whatever the topic carries; for the go2
   that is raw rgb8, ~40× larger than JPEG. → gateway image plane republishes `<topic>_jpeg`
   (TurboJPEG, source header/ts preserved); the jpeg media channel rides the sibling when
   discovered (and swaps to it when it appears after subscribe).
2. **Media-plane ingest was a 256-deep FIFO** labeled freshest-wins — an encoder running slower
   than the camera served frames up to ~18 s stale. → `ConflatedIngest` (latest-per-topic) shared
   by the media, image, and cloud planes (the cloud plane had the same bug for point clouds).
3. **No client conflation** — the jpeg channel started an async decode per message; decode slower
   than delivery = unbounded backlog and out-of-order frames. → single decode in flight, newest
   wins; raw rgb8/bgr8 additionally skip the per-pixel JS loop via a synchronous `VideoFrame`
   (RGBX/BGRX) construct.
4. **Chrome's WebRTC jitter buffer** reads a low-fps camera's inter-frame gaps as jitter and holds
   several frame-intervals of playout delay even on loopback. → `jitterBufferTarget = 0` /
   `playoutDelayHint = 0` on the receiver.

Supporting fixes: H.264 encoder waits ~5 frames and configures with the measured camera rate
(was: hardcoded 30 fps rate control / wrong IDR cadence), rebuilds on resolution change; the
encoded-chunk fanout is bounded and evicts viewers that stall > 1 s; `webcodecs` capability is
probed honestly (`isConfigSupported` + the gateway hello's `media` list, 4 s timeout) and `auto`
walks the preference list instead of dropping straight to the jpeg floor.

## Knobs

- `IMAGE_JPEG=0` — disable the gateway transcode (the A/B lever for the table above).
- `IMAGE_JPEG_QUALITY=75` — TurboJPEG quality.

## Reproduce

```bash
dimos --dtop --replay --replay-db go2_hongkong_office run unitree-go2   # tab 1 (restart at end-of-db)
deno task serve                                                          # tab 2
deno task throttle 8081 100 8080                                         # tab 3 — 100 Mbit "LAN"
deno task bench-video "http://localhost:8080/?transport=ws&gw=localhost:8081" 45 jpeg,webcodecs,webrtc,auto
```
