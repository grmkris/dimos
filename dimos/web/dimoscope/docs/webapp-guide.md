# Build your own webapp on @dimos/web

The dimoscope app is the reference implementation — this guide is the map. Copy
[`app/src/Example.tsx`](../app/src/Example.tsx), wire a provider, and you have a live robot page;
everything else in the app is the same handful of hooks arranged differently.

## What you need

- A running backend: `deno task serve` plus a data source (`deno task load` for synthetic lanes,
  `deno task dog` for a teleoperable sim) — see the [README quickstart](../README.md#quickstart).
  Or point at a remote gateway: any `host:8080` reachable from the browser.
- Chrome/Edge for WebTransport; every other browser falls back to WebSocket automatically.

## The 5-minute app (React)

`DimosProvider` with a bare `url` is the one-server shorthand — no transport wiring, no config.
The client connects over WebSocket (`/ws` is appended automatically), discovers topics, and every
hook below it just works:

```tsx
import { createRoot } from "react-dom/client";
import { DimosProvider, useTopicLatest, useTopics } from "@dimos/react";

function Pose() {
  const topics = useTopics(); // live discovery — no config, updates as topics appear
  const { data, meta } = useTopicLatest<{ pose: { position: { x: number; y: number } } }>(
    "/odom",
    { maxHz: 10 }, // server-side QoS: the gateway downsamples before bytes hit the wire
  );
  return (
    <pre>
      {topics.length} topics · {meta?.latencyMs?.toFixed(1) ?? "–"} ms{"\n"}
      {JSON.stringify(data?.pose?.position)}
    </pre>
  );
}

createRoot(document.getElementById("root")!).render(
  <DimosProvider url="ws://localhost:8080">
    <Pose />
  </DimosProvider>,
);
```

No React? The vanilla client is the same machinery without hooks:

```ts
import { createDimosClient } from "@dimos/web";

const client = createDimosClient();
await client.connect("ws://localhost:8080");
client.subscribe("/odom", (m) => console.log(m.data, m.meta.latencyMs));
```

Full vanilla tour — QoS, `peek`, teleop, RPC:
[README § The SDK in 15 lines](../README.md#the-sdk-in-15-lines--list-topics-subscribe-control-the-push-rate).

## Start from the live example

Open the app with `?tab=example` (e.g. `http://localhost:8080/?tab=example`) — that page is
[`app/src/Example.tsx`](../app/src/Example.tsx), one ~90-line panel showing the whole loop:
connection status, topic discovery, one on-demand subscription with a server-side `maxHz` cap,
live stats, and the gateway-whitelisted RPC buttons. It imports only from `@dimos/react`, so it
drops into any app unchanged.

## Reading dimoscope as the reference implementation

| You want to build… | Read | Hook(s) it demonstrates |
| --- | --- | --- |
| the minimal panel | [`app/src/Example.tsx`](../app/src/Example.tsx) | the core loop |
| typed topic names + RPC | [`app/src/dimos.ts`](../app/src/dimos.ts) | `createDimosHooks` over the generated map |
| a low-rate readout | [`app/src/panels/PoseReadout.tsx`](../app/src/panels/PoseReadout.tsx) | `useTopicLatest` |
| live per-topic stats | [`app/src/panels/StatsBar.tsx`](../app/src/panels/StatsBar.tsx) | `useTopics` + `useTopicStats` |
| a camera view | [`app/src/panels/CameraView.tsx`](../app/src/panels/CameraView.tsx) | `useVideo` (webcodecs/webrtc/jpeg, negotiated) |
| teleop with a deadman | [`app/src/panels/TeleopPad.tsx`](../app/src/panels/TeleopPad.tsx) | `useTeleop` |
| RPC command buttons | [`app/src/panels/CommandsPanel.tsx`](../app/src/panels/CommandsPanel.tsx) | `useCommands` + `useRpc` |
| 60 fps canvas viz | [`app/src/panels/WorldView.tsx`](../app/src/panels/WorldView.tsx) | `useTopicRef` + rAF (no re-render per message) |
| subscribe-by-name UI | `SubscribeBar` — ships as a component in `@dimos/react` | — |
| a transport switcher | [`app/src/main.tsx`](../app/src/main.tsx) | `DimosProvider servers=` + `useServers` |

[`app/src/main.tsx`](../app/src/main.tsx) matters only if you want the multi-transport dropdown: it
builds a `ServerOpt[]` (Auto/WebTransport, WebSocket, plus the experimental bench transports) and
hands it to `DimosProvider servers=`. A normal app skips all of it — the `url` shorthand above is
the entire setup.

## Hook catalog (@dimos/react)

Provider + connection:

| Export | One-liner |
| --- | --- |
| `DimosProvider` | provides the client; `url` shorthand or `servers` list with a switcher |
| `useDimosClient` | the raw `DimosClient` (null before connect) — full SDK surface |
| `useStatus` | `"connecting" \| "open" \| "closed"` for the active transport |
| `useServers` | the transport switcher: `{ servers, activeId, setActiveId }` |
| `useCaps` | active transport capabilities (on-demand / discovery / qos) for QoS-aware UI |

Topics:

| Export | One-liner |
| --- | --- |
| `useTopics` | live list of discovered topics `[{ topic, type }]` |
| `useTopicLatest` | latest decoded message + meta; `{ maxHz }` sets server-side QoS |
| `useTopicRef` | per-message updates in a ref, zero re-renders — read in a rAF loop (canvas) |
| `useTopicStats` | passive hz / bytes/s / latency window — never forces a subscription |
| `useTopicFeed` | rolling, display-throttled message feed with loss% (a mini topic inspector) |

Media, control, misc:

| Export | One-liner |
| --- | --- |
| `useVideo` | camera via the negotiated media plane (webcodecs → webrtc → jpeg floor) |
| `useImageTopic` | paint a raw/jpeg `sensor_msgs.Image` topic into a canvas |
| `useTeleop` | `drive(lin, ang)` / `stop()` — the gateway clamps velocity + runs a TTL deadman |
| `useRpc` | `call(target, method, ...args)` for whitelisted `@rpc` commands |
| `useCommands` | the commands the gateway advertises (drive a button row) |
| `SubscribeBar` | ready-made subscribe-by-name panel component |
| `createDimosHooks` | bind all topic hooks to a generated map — names + payloads become typed |
| `jsonPreview` / `jsonPretty` | Uint8Array/bigint-safe JSON dumps (never stringify pixels) |

## Typed topics + commands

`deno task gen-types` generates `DimosTopics`/`DimosCommands` from the robot blueprint (no gateway,
no robot needed), and `createDimosHooks<DimosTopics, DimosCommands>()` binds every hook to them —
topic names autocomplete, payload fields are inferred, and RPC signatures are checked. The full
walkthrough lives in [`packages/web/README.md`](../packages/web/README.md); the app's binding is
[`app/src/dimos.ts`](../app/src/dimos.ts).

## Using @dimos/web outside this repo

`@dimos/web` / `@dimos/react` are not yet published to JSR/npm (publishing is a follow-up; the
decoder they build on, [`@dimos/msgs`](https://jsr.io/@dimos/msgs), already is). Today:

- **Inside this repo** — add your app to the Deno workspace next to `app/` (see the root
  [`deno.json`](../deno.json)) and import `@dimos/web` / `@dimos/react` directly.
- **Your own repo** — vendor `packages/web` + `packages/react` and alias them in your bundler,
  exactly as the app does ([`app/vite.config.ts`](../app/vite.config.ts)):

```ts
resolve: {
  dedupe: ["react", "react-dom"],
  alias: {
    "@dimos/web/experimental": "<path>/packages/web/src/transports/experimental/index.ts",
    "@dimos/web": "<path>/packages/web/src/index.ts",
    "@dimos/react": "<path>/packages/react/src/index.tsx",
  },
}
```

Runtime deps: `@dimos/msgs` (`npm:@jsr/dimos__msgs`) for both, React 18 for `@dimos/react`.
