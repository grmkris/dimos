# @dimos/web

`@dimos/web` is the TypeScript client for DimOS topics. It connects to the dimoscope gateway,
discovers topics, subscribes to decoded messages, sets per-topic QoS, sends teleop, and calls
whitelisted RPC methods.

```ts
import { createDimosClient } from "@dimos/web";

const dimos = createDimosClient();
await dimos.connect("ws://localhost:8080");

dimos.subscribe("/nav/pose", (m) => {
  console.log(m.data, m.ts, m.meta.latencyMs);
});
```

Without generics, topic payloads are `unknown` and dynamic RPC calls are allowed. Generated maps make
topic names, payloads, targets, methods, arguments, and return values type-checked.

## Type-Safe Client

Types are generated from Python source: module-level topic declarations plus `@rpc` signatures.

```text
blueprint/scenario source -> gen_types.py -> dimos.topics.gen.ts -> createDimosClient<DimosTopics, DimosCommands>()
```

Generate the app's baked-in map:

```bash
cd dimos/web/dimoscope
deno task gen-types
```

Generate from a custom source:

```bash
uv run python packages/web/scripts/gen_types.py scenarios/nav.py --out app/src/dimos.topics.gen.ts
```

Consume it:

```ts
import { createDimosClient } from "@dimos/web";
import type { DimosCommands, DimosTopics } from "./dimos.topics.gen.ts";
import type { geometry_msgs } from "@dimos/msgs";

const dimos = createDimosClient<DimosTopics, DimosCommands>();
await dimos.connect("ws://localhost:8080");

dimos.subscribe("/nav/pose", (m) => {
  m.data.position; // geometry_msgs.PoseStamped
});

const goal = {} as geometry_msgs.PoseStamped;
const ok: boolean = await dimos.modules.ScopeNav.navigate_to(goal);
```

The untyped escape hatch remains available:

```ts
await dimos.call("ScopeNav", "navigate_to", goal);
```

## What Codegen Reads

- Topics: module-level `PORTS = [(attr, topic, MsgClass), ...]`.
- Commands: `@rpc` methods on `Module` subclasses.
- Message types: `MsgClass.msg_name`, imported from `@dimos/msgs`.

## Type Mapping

| Python | TypeScript |
| --- | --- |
| `bool` | `boolean` |
| `int` / `float` | `number` |
| `str` | `string` |
| DimOS message class | `pkg.Name` |
| `list[X]` | `X[]` |
| `Optional[X]` / `X | None` | `X | null` |
| `None` / unannotated return | `void` |
| unsupported | `unknown` |

Regenerate whenever the source topic list or RPC signatures change.
