# Status & known gaps

Snapshot for evaluators (2026-07-06). What works is measured in [benchmarks.md](benchmarks.md);
this page is the honest remainder — what's rough, what's deliberately deferred, and why.

## Works, measured

- Five delivery mechanisms on one gateway (WS · SSE · poll · WebRTC · WebTransport), identical
  self-describing frames, browser-real benchmark matrix with netem — [benchmarks.md](benchmarks.md)
  §3 + the `bench-results-*.md` files.
- QoS: four priority lanes (command > sensor > default > bulk), conflate-to-freshest, per-client
  per-topic overrides (`setQos`), operator glob rules; the fast lane holds beside a flood on WT
  (§0 above is the 5-minute demo).
- Point-cloud plane: gateway-transcoded `_ds` + `_draco` variants (~7× at full point density),
  Clouds comparison tab, 3D WorldView.
- Teleop trust boundary: velocity clamp, TTL deadman, stop-on-disconnect, server-side RPC whitelist.
- Build-your-own-webapp path: [packages/web/README.md](../packages/web/README.md), typed topics +
  commands via `deno task gen-types`, `Example.tsx` reference panel.

## Known issues (open)

- **Video latency**: the receiver-side fix landed (zeroed WebRTC jitter buffer + a latency readout in
  the Camera panel); encoder-side hardening is still queued — `gateway/media.py` feeds the encoder
  through a FIFO queue that should be a depth-1 latest-frame mailbox, so sustained
  encode-slower-than-camera builds standing delay instead of dropping stale frames.
- **Safari / Firefox**: no (stable) WebTransport → Auto falls back to WS. Works, but loses lane
  isolation; the fallback is the documented behavior, not a bug.
- **Sidecar is a build step**: WebTransport/WebRTC need the Rust sidecar (`cargo build`, ~2 min once).
  WS-only works with zero Rust — the gateway serves everything and `/cert` returns 503 until a
  sidecar appears. Prebuilt binaries are a packaging todo.

## Deliberately deferred — why, and the todo

- **#2502 API convergence + JSR publish** — the upstream TS-API spec is still open; this SDK already
  implements ~80% of it. Remaining delta is enumerated and small: `Dimos.connect({decode, dimosWs})`
  wrapper, injectable `decode` (drops the hard `@dimos/msgs` dep → clean JSR publish + a
  gateway-served `/dimos.js`), QoS renames (`maxHz`→`rate`, `best_effort`, add `durability`),
  `m.stream` on the firehose, topic whitelist/blacklist.
- **Gateway as a dimos Module** (`DimosWebsocket.blueprint()`, subscribe-all like the rerun bridge) —
  #2710 is actively deciding bridge-as-Module vs separate process; the spike kept a raw bus tap to
  stay dependency-free. The port is mechanical: `pubsub.subscribe_all` delivers raw bytes (no
  re-encode penalty), and `module_info` introspection can replace the hardcoded RPC whitelist.
- **`@web_module` / `@web_init`** — greenfield everywhere (spec-only in #2502); would follow the
  `@rpc`/`@skill` marker-attribute pattern.
- **Auth + TLS** — no inbound-auth precedent exists anywhere in dimos; trial scope was LAN/VPS behind
  your own firewall. Needs its own design pass before internet exposure.
- **Cloudflare-SFU bench column** — designed end-to-end (operator protocol reconstructed from
  PR #2048's e2e client; known constraints: 16 KiB message cap, ~1k msg/s per channel, one reliable
  ordered robot→browser channel) but not run — needs live broker credentials. PR #2048's own numbers
  already bound the data plane at ~1–4 MB/s.
- **CI** — a deno job (typecheck + tests + app build) was written and then reverted to keep shared
  `ci.yml` churn out of the trial branch; restoring it is ~27 lines.
- **Multi-robot namespacing** — the gateway canonicalizes the single `dimos/` prefix; N robots need a
  namespace scheme, which is an upstream bus decision, not a gateway change.

## Relation to the hosted-teleop track (#2048 / #2562)

Complementary planes, not competitors: the CF/LiveKit SFU path is internet operator teleop —
commands + video through any NAT with managed auth; dimoscope is the full-bus developer cockpit —
every topic, QoS, benchmarks, on LAN or a reachable host. The numbers agree across both efforts:
SCTP DataChannels carry ~1–4 MB/s of data; WebTransport carries 16–19 MB/s with lane isolation.
Video rides WebRTC media in both.
