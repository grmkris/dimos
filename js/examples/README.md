# @dimos examples

Small, runnable examples for the `@dimos/topics` SDK. Each is a Bun script — run it with a
gateway + a data source up (see [../apps/dimoscope/RUN.md](../apps/dimoscope/RUN.md): start
`dimoscope/servers/start-all.sh` + a source like `examples/simplerobot`).

| Example                          | Shows                                                                    | Run                                                                  |
| -------------------------------- | ------------------------------------------------------------------------ | -------------------------------------------------------------------- |
| [`hello-topics`](./hello-topics) | connect → discover topics → subscribe `/odom` (typed via `DimosTopics`)  | `GATEWAY_URL=ws://localhost:8089 bun examples/hello-topics/index.ts` |
| [`teleop`](./teleop)             | safe velocity control — `client.teleop()` (gateway clamps + TTL/deadman) | `GATEWAY_URL=ws://localhost:8089 bun examples/teleop/index.ts`       |

`GATEWAY_URL` defaults to the Bun↔LCM gateway (`ws://localhost:8089`); point it at `:8088`
(Python↔Zenoh) or `:10000` (zenoh-ts) to try the other transports — same code, any transport.

## Follow-ups (not yet built)

- `custom-widget` — register an app panel for a message type (`registerWidget` from `@dimos/react/registry`).
- `react-quickstart` — minimal Vite + `@dimos/react` app rendering one topic.
- `patrol-fleet` — multi-robot coordination (needs per-robot addressing; see [../IDEAS.md](../IDEAS.md)).
- `bring-your-own-topic` — app-defined message types (needs `registerType`; see [../IDEAS.md](../IDEAS.md)).
