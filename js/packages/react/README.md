# @dimos/react

Thin React bindings over [`@dimos/topics`](../topics) — hooks to subscribe, visualize,
teleop, and a pluggable widget registry. Built for dimoscope; usable in any Vite/React app.

## Install

```sh
bun add @dimos/react @dimos/topics react react-dom
```

## Setup

Wrap your tree in a provider. Pass a single `url`, or a `servers` list to expose a
live transport switcher (the client is rebuilt when the active server changes):

```tsx
import { DimosProvider } from "@dimos/react";

<DimosProvider url="ws://localhost:8089">
  <App />
</DimosProvider>;
```

## Hooks

**Discovery & connection**

- `useTopics()` → live `TopicInfo[]` of discovered topics
- `useStatus()` → `"connecting" | "open" | "closed"`
- `useServers()` → `{ servers, activeId, setActiveId }` (the transport switcher)
- `useDimosClient()` → the raw `DimosClient` (escape hatch)

**Data**

- `useTopicLatest<T>(topic, { maxHz })` → `{ data?, meta? }`, re-renders per message
- `useTopicRef<T>(topic)` → a ref updated without re-rendering (read it in a rAF loop — for canvas)
- `useTopicStats(topic, pollMs)` → `{ hz, ... }`, **passive** (never forces a subscription)

**Camera / media**

- `useImageTopic(topic, { maxFps })` → `{ canvasRef, info }` — paints a `sensor_msgs.Image`
- `useVideo(topic, { mode })` → `{ kind, videoRef, canvasRef, label, active, requested }` —
  the negotiated media plane (WebRTC/WebCodecs `<video>` or the JPEG `<canvas>` floor).
  `mode`: `"auto" | "webrtc" | "webcodecs" | "jpeg"`.

**Control**

- `useTeleop()` → `{ drive(linearX, angularZ, ttlMs?), stop() }` (gateway clamps + deadman)
- `useRpc()` → `{ call(target, method, ...args) }` (whitelisted dimos `@rpc` commands)
- `useCommands()` → `CommandInfo[]` the gateway advertises as browser-callable

`SubscribeBar` is a ready-made component to pin/observe any topic by name.

## Widget registry

Map a message _type_ → a panel, without editing library source (the `bring-your-own-topic`
story). Lives on a subpath so the app registers its widgets at startup:

```tsx
import { registerWidget, widgetForType } from "@dimos/react/registry";

registerWidget("myapp.PatrolStatus", PatrolStatusPanel);
const Panel = widgetForType(topic.type); // render Panel if defined
```

See [`@dimos/topics`](../topics) for the underlying client, typed topics, and transports.
