# Running dimoscope from this worktree

This is the `js/` workspace in the **`dimos-js` worktree** (branch `kris/js-monorepo`).
It holds the full dimoscope (media plane: WebRTC/WebCodecs/JPEG camera, 3-transport
dropdown, in-browser benchmark) ported from the agents' work on `kris/research-29-06-2026`.

**Why two checkouts:** the LCM/Zenoh bus is **machine-wide**, so the JS side (app + Bun
gateway) runs from _this worktree_ while the Python side (sim + the aiortc Zenoh gateway)
runs from the **main checkout** (`~/Code/github-com/dimos`), which has the `.venv` +
`dimos` package. `servers/start-all.sh` auto-finds that venv, so you can also launch the
Python gateway from here.

## One-time

```sh
cd ~/Code/github-com/dimos-js/js && bun install
```

## Bring it up (3 terminals)

**A — data source (sim), from the MAIN checkout** (has uv + dimos + .venv):

```sh
cd ~/Code/github-com/dimos
DIMOS_TRANSPORT=zenoh uv run dimos --simulation dimsim run unitree-go2
```

**B — all transports/gateways, from THIS worktree** (start-all.sh finds the main venv
for the Python↔Zenoh gateway; the Bun↔LCM gateway + zenoh-ts bridge are pure JS/binary):

```sh
cd ~/Code/github-com/dimos-js/js/apps/dimoscope
bash servers/start-all.sh
#   Python↔Zenoh  ws://localhost:8088   (camera media plane: aiortc WebRTC/WebCodecs)
#   Bun↔LCM       ws://localhost:8089
#   zenoh-ts      ws://localhost:10000  (needs: cargo install zenoh-bridge-remote-api)
```

**C — the app, from THIS worktree:**

```sh
cd ~/Code/github-com/dimos-js/js/apps/dimoscope
bun run dev          # → http://localhost:5173   (benchmark page: /bench.html)
```

The topbar dropdown switches transport live; the **cam** dropdown A/Bs the media mode
(auto / webrtc / webcodecs / jpeg). Click the WorldView to send a nav goal.

## Headless sanity (no browser, with B + a source running)

```sh
cd ~/Code/github-com/dimos-js/js/apps/dimoscope
bun run probe                 # lists discovered topics
bun run bench/sdk_smoke.ts    # decodes /odom + /map via the SDK
```

## Notes

- `@dimos/msgs` is still the published `npm:@jsr/dimos__msgs@0.1.4` (unchanged from the
  agents' build — so it runs identically). Swapping it to a vendored `workspace:*` is
  deferred (see `js/IDEAS.md`).
- `bench/bench_deno.ts` is a Deno script (`deno run`), excluded from the Bun/TS build.
- Verify the workspace is healthy any time: `cd ~/Code/github-com/dimos-js/js &&
bunx turbo lint typecheck build` (all green).
