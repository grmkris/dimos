# Status and Known Gaps

This page lists the current caveats for dimoscope. Measured behavior and runbooks live in
[`benchmarks.md`](benchmarks.md); app-building guidance lives in [`webapp-guide.md`](webapp-guide.md).

## Works

- One gateway fans LCM/Zenoh topics to WebSocket, WebTransport, WebRTC data, SSE, and poll.
- Browser SDK and React hooks support discovery, subscriptions, QoS, latest values, stats, teleop,
  whitelisted RPC, camera, and typed topic/RPC codegen.
- QoS uses command/sensor/default/bulk lanes, per-client overrides, operator rules, conflation, and
  last-value replay.
- Heavy media paths have browser-friendly siblings: image topics get `_jpeg`; point clouds get `_ds`
  and `_draco`.
- The app includes WorldView, camera, clouds comparison, stream cards, teleop, benchmark drawer, and
  optional `/runs` controls.

## Known Gaps

- Safari and Firefox do not provide stable WebTransport. Auto falls back to WebSocket, which is
  correct but loses QUIC lane isolation.
- WebTransport and WebRTC data need the Rust sidecar. WS/SSE/poll continue to work without it; `/cert`
  returns 503 until the sidecar writes its cert hash.
- Auth and TLS are out of scope for this prototype. Treat it as LAN/VPN/VPS-behind-firewall software.
- `@dimos/web` and `@dimos/react` are not published packages yet. Use the workspace packages or vendor
  them as described in `webapp-guide.md`.
- The SDK intentionally does not fully match the upstream web API proposal yet. Remaining convergence:
  `Dimos.connect(...)`, injectable decode, QoS naming, `m.stream`, and topic allow/deny lists.
- CI for this tree is still manual. The intended job is `deno task check`, `deno task test`, and
  `uv run pytest dimos/web/dimoscope/gateway/tests -q`.
- Multi-robot namespacing is not designed here. The gateway currently assumes one logical DimOS topic
  namespace.

## Related Work

Hosted teleop/SFU work and dimoscope are complementary: SFU paths are for internet operator video and
NAT traversal; dimoscope is a full-bus developer cockpit with topic discovery, QoS, benchmarks, and
local or reachable-host operation. Video should ride WebRTC media; general robot data should prefer
WebTransport where UDP is available and WebSocket as fallback.
