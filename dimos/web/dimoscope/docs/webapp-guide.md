# Build a Webapp on dimoscope

The dimoscope app is the reference implementation. For a small app, use `DimosProvider`, subscribe to
topics with hooks, and let the gateway handle discovery, QoS, decoding, and control safety.

## What You Need

- A running backend: `deno task serve`.
- A data source: `deno task load`, `deno task dog`, or a real robot stack.
- Chrome/Edge for WebTransport. Other browsers fall back to WebSocket.

## Five-Minute React App

```tsx
import { createRoot } from "react-dom/client";
import { DimosProvider, useTopicLatest, useTopics } from "@dimos/react";

function Pose() {
  const topics = useTopics();
  const { data, meta } = useTopicLatest<{ pose: { position: { x: number; y: number } } }>(
    "/odom",
    { maxHz: 10 },
  );

  return (
    <pre>
      {topics.length} topics · {meta?.latencyMs?.toFixed(1) ?? "-"} ms{"\n"}
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

No React:

```ts
import { createDimosClient } from "@dimos/web";

const client = createDimosClient();
await client.connect("ws://localhost:8080");
client.subscribe("/odom", (m) => console.log(m.data, m.meta.latencyMs));
```

## Live Example

Open `http://localhost:8080/?tab=example`. The page is
[`app/src/Example.tsx`](../app/src/Example.tsx): connection status, live discovery, one on-demand
subscription with `maxHz`, stats, and RPC buttons. It imports only from `@dimos/react`, so it is the
best copy point for a new app.

## Reference App Map

| Goal | File | Main API |
| --- | --- | --- |
| Minimal panel | `app/src/Example.tsx` | `useStatus`, `useTopics`, `useTopicLatest` |
| Typed hooks | `app/src/dimos.ts` | `createDimosHooks` |
| Pose readout | `app/src/panels/PoseReadout.tsx` | `useTopicLatest` |
| Stats | `app/src/panels/StatsBar.tsx` | `useTopics`, `useTopicStats` |
| Camera | `app/src/panels/CameraView.tsx` | `useVideo` |
| Teleop | `app/src/panels/TeleopPad.tsx` | `useTeleop` |
| RPC buttons | `app/src/panels/CommandsPanel.tsx` | `useCommands`, `useRpc` |
| Canvas/world viz | `app/src/panels/WorldView.tsx` | `useTopicRef` |
| Transport switcher | `app/src/main.tsx` | `DimosProvider servers=`, `useServers` |

## Hook Catalog

| Export | Use |
| --- | --- |
| `DimosProvider` | Provides a client; `url` shorthand or `servers` list |
| `useDimosClient` | Raw client, or `null` before connect |
| `useStatus` | `"connecting" | "open" | "closed"` |
| `useServers` | Transport switcher state |
| `useCaps` | Active transport capabilities |
| `useTopics` | Live discovered topics |
| `useTopicLatest` | Latest decoded message and metadata |
| `useTopicRef` | Latest messages in a ref for render loops |
| `useTopicStats` | Passive hz, bytes/s, latency |
| `useTopicFeed` | Rolling inspector feed |
| `useVideo` | Negotiated camera media |
| `useImageTopic` | Paint an image topic into a canvas |
| `useTeleop` | Deadman-protected velocity control |
| `useRpc` | Call whitelisted RPC methods |
| `useCommands` | Advertised command list |
| `SubscribeBar` | Ready-made topic subscription UI |
| `createDimosHooks` | Bind hooks to generated topic/RPC maps |

## Typed Topics and Commands

`deno task gen-types` generates `DimosTopics` and `DimosCommands` from blueprint/source files without
running a robot. Pass them to `createDimosClient<DimosTopics, DimosCommands>()` or
`createDimosHooks<DimosTopics, DimosCommands>()` for topic-name autocomplete, payload inference, and
typed RPC calls.

The full codegen reference is [`packages/web/README.md`](../packages/web/README.md).

## Using the Packages Elsewhere

`@dimos/web` and `@dimos/react` are not published to JSR/npm yet. Today:

- In this repo, add an app to the Deno workspace and import the workspace packages.
- Outside this repo, vendor `packages/web` and `packages/react`, then alias them in your bundler.
  The snippet below assumes a Vite React scaffold (`npm create vite@latest -- --template react-ts`,
  which brings `@vitejs/plugin-react` — use its v4 line on Vite 5).

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

Runtime deps: `@dimos/msgs` for decoding and React 18 for `@dimos/react`. `@dimos/msgs` is a JSR
package — npm/bun installs need `.npmrc` with `@jsr:registry=https://npm.jsr.io` and the dependency
written as `"@dimos/msgs": "npm:@jsr/dimos__msgs"`.
