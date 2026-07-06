# Status & known gaps

What works is measured in [benchmarks.md](benchmarks.md); this page is the honest remainder — what's
rough, what's out of scope, and the todo for each.

## Works, measured

- Five delivery mechanisms on one gateway (WS · SSE · poll · WebRTC · WebTransport), identical
  self-describing frames, browser-real benchmark matrix with netem — [benchmarks.md](benchmarks.md)
  §3 + the `bench-results-*.md` files.
- QoS: four priority lanes (command > sensor > default > bulk), conflate-to-freshest, per-client
  per-topic overrides (`setQos`), operator glob rules; the fast lane holds beside a flood on WT
  (§0 of benchmarks.md is the 5-minute demo).
- Durability: a late subscriber gets the last value on any wire — the gateway keeps a last-value
  cache and replays it on subscribe over WS and down the sidecar pipe for WT/WebRTC.
- Point-cloud plane: gateway-transcoded `_ds` + `_draco` variants (~7× at full point density),
  Clouds comparison tab, 3D WorldView.
- Teleop trust boundary: velocity clamp, TTL deadman, stop-on-disconnect, server-side RPC whitelist.
- Build-your-own-webapp path: [packages/web/README.md](../packages/web/README.md), typed topics +
  commands via `deno task gen-types`, `Example.tsx` reference panel.

## Known issues

- **Video latency**: the Camera panel shows a live glass-to-glass readout; WebRTC plays out with a
  zeroed jitter buffer. Open: `gateway/media.py` feeds the encoder through a FIFO — under sustained
  encode-slower-than-camera it delays instead of dropping stale frames. The fix shape is a depth-1
  latest-frame mailbox per topic.
- **Safari / Firefox**: no (stable) WebTransport → Auto falls back to WS. Works, but without lane
  isolation; the fallback is the documented behavior, not a bug.
- **Sidecar is a build step**: WebTransport/WebRTC need the Rust sidecar (`cargo build`, ~2 min once).
  WS-only works with zero Rust — the gateway serves everything and `/cert` returns 503 until a
  sidecar appears. Prebuilt binaries are a packaging todo.

## Out of scope here — and the todo

- **#2502 API convergence + JSR publish** — this SDK implements ~80% of the upstream TS-API spec.
  The delta: a `Dimos.connect({decode, dimosWs})` wrapper, injectable `decode` (removes the hard
  `@dimos/msgs` dep → clean JSR publish + a gateway-served `/dimos.js`), QoS renames
  (`maxHz`→`rate`, `best_effort`, add `durability`), `m.stream` on the firehose, topic
  whitelist/blacklist.
- **Gateway as a dimos Module** (`DimosWebsocket.blueprint()`, subscribe-all like the rerun bridge) —
  #2710 is deciding bridge-as-Module vs separate process; this gateway uses a raw bus tap to stay
  dependency-free. The port is mechanical: `pubsub.subscribe_all` delivers raw bytes (no re-encode
  penalty), and `module_info` introspection can replace the hardcoded RPC whitelist.
- **`@web_module` / `@web_init`** — spec-only in #2502; the natural implementation is the
  `@rpc`/`@skill` marker-attribute pattern.
- **Auth + TLS** — dimos has no inbound-auth precedent; this stack targets LAN/VPS behind your own
  firewall. Internet exposure needs its own design pass.
- **Cloudflare-SFU bench column** — specced end-to-end (operator protocol; constraints: 16 KiB
  message cap, ~1k msg/s per channel, one reliable ordered robot→browser channel); running it needs
  live broker credentials. Published measurements put the SFU DataChannel data plane at ~1–4 MB/s.
- **CI** — none for this tree; verification is the manual commands in the README. The todo is one
  deno job: typecheck + tests + app build.
- **Multi-robot namespacing** — the gateway canonicalizes the single `dimos/` prefix; N robots need a
  namespace scheme, which is an upstream bus decision, not a gateway change.

## Relation to the hosted-teleop track (#2048 / #2562)

Complementary planes, not competitors: the CF/LiveKit SFU path is internet operator teleop —
commands + video through any NAT with managed auth; dimoscope is the full-bus developer cockpit —
every topic, QoS, benchmarks, on LAN or a reachable host. The numbers agree across both efforts:
SCTP DataChannels carry ~1–4 MB/s of data; WebTransport carries 16–19 MB/s with lane isolation.
Video rides WebRTC media in both.
