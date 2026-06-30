# Ideas & roadmap — `@dimos` web SDK

Forward-looking work for the `js/` monorepo (`@dimos/{msgs,lcm,topics,react}` + dimoscope).
Ordered roughly by leverage. Items marked **(landed)** already exist; the rest are open.

## #2502 — TS API spec alignment

[Issue #2502](https://github.com/dimensionalOS/dimos/issues/2502) (TS API Spec) proposes a
higher-level surface — `Dimos.connect(...)` + `app.subscribe`/`peek`/`subscribeAll`/`setQos` and
`app.modules.X.method()`. The current `@dimos/topics` covers the same ground with a slightly
different shape. Decision (2026-06-30): **align + document now, build the facade later.** Mapping:

| #2502 spec                                                                 | Today (`@dimos/topics`)                                                | Status                                                 |
| -------------------------------------------------------------------------- | ---------------------------------------------------------------------- | ------------------------------------------------------ |
| `Dimos.connect({ decode, dimosWs: { host, port, whitelist, blacklist } })` | `connect({ url, namespace })` — decode is built-in via `@dimos/msgs`   | shape differs; no whitelist/blacklist                  |
| `const unsub = app.subscribe("/tf", m => use(m.data, m.ts))`               | `client.topic("/tf").subscribe((data, meta) => …)` → `{ unsubscribe }` | ✅ equivalent                                          |
| `await app.peek("/tf", { timeoutMs })`                                     | —                                                                      | follow-up (subscribe-once + timeout)                   |
| `app.subscribeAll(m => …)`                                                 | `client.listTopics()` + per-topic subscribe                            | follow-up (one-call firehose)                          |
| `app.setQos("/tf", { rate, reliability, durability, depth })`              | `topic.setRateLimit(hz)`                                               | rate ✅; reliability/durability/depth need gateway QoS |
| `await app.modules.GO2Connection.standup()`                                | `client.call("GO2Connection", "standup")`                              | ✅ equivalent; `app.modules` is sugar (a `Proxy`)      |
| `message.data` + `message.ts`                                              | `(data, meta)` — `meta.srcTs` / `recvTs` / `latencyMs`                 | shape differs                                          |

**Tracked follow-ups to fully realize #2502** (deferred — the data path already works; this is ergonomics + a server):

- A thin **`Dimos.connect` facade** over the current client — `subscribe`/`peek`/`subscribeAll`/`setQos`,
  an `app.modules` RPC `Proxy`, and a `{ data, ts }` message shape — backed by the existing transports.
- The unified **`DimosWebsocket`** server (`:9669`, serves `/dimos.js` + a same-origin WS with
  whitelist/blacklist), so `dimosWs: { host, port }` works end-to-end (today: separate gateways on
  `:8088`/`:8089`, see [apps/dimoscope/servers](apps/dimoscope/servers)).
- Python-side **`@web_module` / `@web_init`** decorators (dimos-core — lets any module ship a frontend).
- **QoS beyond rate** (reliability / durability / depth) — needs gateway + transport support.

## Rerun viewer in the browser — `@dimos/rerun` (deferred)

Today the app embeds the **stock** `@rerun-io/web-viewer-react` and wires click-to-nav via
`selection_change` → `client.navigate()`. The **forked** `dimos-viewer` adds richer
click/keyboard interaction, but that path is **native-only**: `dimos/src/interaction/ws.rs`
uses `tokio` + `tokio_tungstenite::connect_async` on an `std::thread` runtime, with **no**
`#[cfg(target_arch="wasm32")]` / `web-sys` branch — so it cannot build to the browser WASM
target. A `@dimos/rerun` package depends on the fork shipping a browser-capable viewer first.

Two paths to watch:

- **embed-webview** — fork [PR #24](https://github.com/dimensionalOS/dimos-viewer/pull/24).
- **wasm-websocket port** of `ws.rs` — swap native `tokio`/`tokio-tungstenite` for `web-sys`
  under `#[cfg(target_arch="wasm32")]` (see fork [#20](https://github.com/dimensionalOS/dimos-viewer/pull/20),
  [#15](https://github.com/dimensionalOS/dimos-viewer/pull/15)).

Protocol source-of-truth = `ws.rs` (viewer-as-client; `--ws-url` default `ws://127.0.0.1:3030/ws`)
plus `dimos/visualization/rerun/websocket_server.py`. The fork's `docs/websockets.md` is **stale**
(it describes an abandoned server mode) — do not trust it. Until a browser viewer lands, the stock
viewer + `selection_change`→nav is the browser story.

## Fleet / multi-robot SDK

Motivated by the `patrol-fleet` example. The SDK is today effectively **single-robot**:
`client.navigate(x,y,z)` publishes a `PointStamped` to a fixed `clicked_point` and `teleop()`
writes a fixed channel (`packages/topics/src/client.ts`). A fleet needs:

- **Per-robot addressing** — `client.robot("/robot1").navigate(…)` / namespaced `teleop`,
  over either one client on namespaced topics or one gateway+client per robot. The gateway
  already discovers namespaced topics, so the browser can filter by prefix for free.
- **`createScheduler`** — a fleet primitive driving each robot's patrol on its own period/phase.
- **Waypoint/region patrol router** — a variant of dimos's existing `"coverage"` router that
  binds a robot to a region of the shared map.

## App-defined message types (the "vibe-coding" loop)

Custom _topics_ with built-in types already work. The gap is custom _types_ (decode) + custom
_widgets_ (viz):

- **Open the type registry** — export a public `registerType`/`registerPackage` from
  `@dimos/msgs` (today `_registerPackage` is private and `decode()` throws on unknown hashes),
  so an app's generated `@myapp/msgs` decodes by hash like the 14 built-ins. Ideally upstreamed
  to `dimos-lcm`.
- **Pluggable widgets (landed)** — `registerWidget(type, Component)` in `@dimos/react` lets an
  app map its own message type → its own panel without editing library source.
- **Ship the codegen** — bring `dimos-lcm/tools/ts/gen` in as `@dimos/msgs-gen` / a `dimos gen`
  command so a `.lcm` schema becomes Python + TS bindings in one step.
- **Schema-discovery (north star)** — dimos publishes type schemas on a discovery channel so the
  browser decodes _unknown_ types generically with **zero codegen** (analogous to ROS2 type
  descriptions / Foxglove schemas). Needs a dimos Python-side schema-publish.

## Media plane

- **Negotiated camera (landed)** — `useVideo` selects WebRTC (encoded once server-side via
  aiortc, hardware-decoded in the browser) with a JPEG Image-topic floor; a topbar toggle A/Bs
  the bandwidth win. Next: runtime fallback to JPEG on WebRTC connect failure; hoist the
  `MediaChannel` to a provider so a multi-camera grid shares one `PeerConnection`.

## Transports & gateway

- **True on-demand subscribe on the Zenoh gateway** — only forward topics a client actually
  subscribes to (the Bun↔LCM gateway already discovers everything; trim Zenoh egress).
- **Transport benchmark write-up** — the bench page compares LCM vs Zenoh vs zenoh-ts across
  latency/bandwidth; turn `bench/RESULTS*.md` into a docs page.

## Tooling & distribution

- **Single-source codegen** — drive Python + TS msgs from `dimos-lcm/sources/`, retiring the
  vendored `generated/` + `python_lcm_msgs` drift.
- **Publishing automation** — changesets + a CI release workflow for `@dimos/*` on npm.
- **Agent / skills panel** — surface dimos's agentic core (agent + skill telemetry) as a
  first-class dimoscope view, once those topics have stable types (ties into custom types above).
