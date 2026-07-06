# wt-sidecar

The Rust sidecar owns the native UDP data paths for dimoscope:

- WebTransport on `WT_PORT` (`8443`).
- WebRTC data channels on `RTC_PORT` (`8444`).

The Python gateway remains the safety and state owner: bus tap, topic discovery, `SafetyEgress`,
RPC whitelist, media/cloud transcodes, and `/cert`. The sidecar reconnects to the gateway over the
unix pipe at `WT_PIPE`.

## Run

```sh
deno task serve       # gateway + sidecar together
deno task wt-sidecar  # sidecar only, useful while the gateway stays up
```

## Protocol

- Pipe frames are `[u32be len][u8 kind][payload]`.
- Kind `1` is data: raw LC02 packet, stamped once at pipe ingress.
- Kind `2` is JSON: hello/topic/rpc responses down; subscribe/teleop/stop/goal/rpc/disconnect up.
- Small high-priority frames use QUIC datagrams where possible; large frames use reliable streams.
- WebRTC data uses reliable control plus separate pose/bulk channels.

## Safety and QoS

- Teleop, goal, and RPC requests are forwarded to the gateway `SafetyEgress` and keyed by session id.
- Closing a session sends `disconnect`; dropping the pipe stops all sidecar-owned sessions.
- `src/outbox.rs` mirrors `gateway/qos.py`: lane heuristics, weighted round-robin, conflation, and
  operator `QOS_RULES` / `qos.rules.json` support. Keep rule precedence and lane defaults in sync.
- The browser-acked bulk credit gate limits reliable-stream backlog on shaped links without reducing
  clean-path throughput.

## Why Rust

Native QUIC/WebTransport is needed for high-throughput bulk streams and real stream/datagram behavior
inside one connection. Without the sidecar, the gateway still serves WebSocket, SSE, poll, and media
fallbacks. Current transport measurements are in [`../../docs/benchmarks.md`](../../docs/benchmarks.md).
