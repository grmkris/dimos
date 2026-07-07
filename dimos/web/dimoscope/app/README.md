# dimoscope Reference App

The app is the copyable reference implementation for building on `@dimos/web` and `@dimos/react`.
It shows topic discovery, live subscriptions, typed RPC, camera media, teleop, WorldView, cloud
comparison, run controls, and the benchmark drawer.

## Run It

```bash
cd dimos/web/dimoscope
deno install && deno task build
deno task serve
deno task load
```

Open http://localhost:8080/. For development against a local or remote gateway:

```bash
deno task app
# open http://localhost:5173/?gw=placeholder%2Fvps
```

`placeholder/vps` is a placeholder, not a literal gateway. Replace it with your real gateway
`host:port`, for example `localhost:8080` locally or a reachable VPS gateway.

## Copy Points

Open `?tab=example`. [`src/Example.tsx`](src/Example.tsx) is the smallest panel that demonstrates the
usual workflow:

- connection status and live topic discovery
- typed subscription through `src/dimos.ts` and `src/dimos.topics.gen.ts`
- dynamic topic inspection with server-side `maxHz`
- passive stats with `useTopicStats`
- whitelisted RPC buttons and typed `modules.<Module>.<rpc>()`

The app's other panels are the larger examples:

| Goal | File | Main API |
| --- | --- | --- |
| Minimal panel | `src/Example.tsx` | `useStatus`, `useTopics`, `useTopic` |
| Typed hooks | `src/dimos.ts` | `createDimosHooks` |
| Pose readout | `src/panels/PoseReadout.tsx` | `useTopic` |
| Stats | `src/panels/StatsBar.tsx` | `useTopics`, `useTopicStats` |
| Camera | `src/panels/CameraView.tsx` | `useVideo` |
| Teleop | `src/panels/TeleopPad.tsx` | `useTeleop` |
| RPC buttons | `src/panels/CommandsPanel.tsx` | `useCommands`, `useRpc` |
| Canvas/world viz | `src/panels/WorldView.tsx` | `useTopicSnapshot` |
| Transport switcher | `src/main.tsx` | `DimosProvider servers=`, `useServers` |

## React usage example

```tsx
import { createRoot } from "react-dom/client";
import { DimosProvider } from "@dimos/react";
import { useTopic, useTopics } from "./dimos";

function Pose() {
  const topics = useTopics();
  const { data, meta } = useTopic("/nav/pose", { maxHz: 10 });

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

## Hooks

| Export | Use |
| --- | --- |
| `DimosProvider` | Provides a client; `url` shorthand or a `servers` list |
| `useDimosClient` | Raw client, or `null` before connect |
| `useStatus` | `"connecting" | "open" | "closed"` |
| `useServers` | Transport switcher state |
| `useCaps` | Active transport capabilities |
| `useTopics` | Live discovered topics |
| `useTopic` | Latest decoded message and metadata |
| `useTopicSnapshot` | Latest messages in a ref for render loops |
| `useTopicStats` | Passive Hz, bytes/s, latency |
| `useTopicHistory` | Rolling inspector feed |
| `useVideo` | Negotiated camera media |
| `useTopicImage` | Paint an image topic into a canvas |
| `useTeleop` | Deadman-protected velocity control |
| `useRpc` | Call whitelisted RPC methods |
| `useCommands` | Advertised command list |
| `SubscribeBar` | Ready-made topic subscription UI |
| `createDimosHooks` | Bind hooks to generated topic/RPC maps |

## Typed Topics and Commands

`deno task gen-types` generates `DimosTopics` and `DimosCommands` from scenario/blueprint sources
without running a robot. Pass them to `createDimosClient<DimosTopics, DimosCommands>()` or
`createDimosHooks<DimosTopics, DimosCommands>()` for topic-name autocomplete, payload inference, and
typed RPC calls. The SDK codegen reference lives in [`../packages/web/README.md`](../packages/web/README.md).

## Using the Packages Elsewhere

`@dimos/web` and `@dimos/react` are not published to JSR/npm yet. Today:

- In this repo, add an app to the Deno workspace and import the workspace packages.
- Outside this repo, vendor `packages/web` and `packages/react`, then alias them in your bundler.

For a Vite React scaffold:

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

Runtime deps: `@dimos/msgs` for decoding and React 18 for `@dimos/react`. For npm/bun installs, use
`.npmrc` with `@jsr:registry=https://npm.jsr.io` and depend on
`"@dimos/msgs": "npm:@jsr/dimos__msgs"`.
