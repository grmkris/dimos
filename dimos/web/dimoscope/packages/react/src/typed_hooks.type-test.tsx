// Compile-only type test for createDimosHooks<TMap>() (no runtime; picked up by `deno task check`).
// Proves the factory-bound hooks autocomplete the topic name and infer the mapped message type,
// with the same runtime-string fallback as the client.
import { createDimosHooks } from "./index.tsx";

type Fixture = { "/odom": { x: number } };

const { useTopic, useTopicHistory, useTopicSnapshot, useTopicLatest, useTopicRef } =
  createDimosHooks<Fixture>();

function _component() {
  // ① known key → data inferred as the mapped message type
  const { data } = useTopic("/odom");
  const _pose: { x: number } | undefined = data;
  // @ts-expect-error — data is {x:number}|undefined, not {y:number}
  const _wrong: { y: number } | undefined = data;

  // ② runtime-discovered name → Topic<unknown>
  const { data: d2 } = useTopic("/not_in_map");
  const _u: unknown = d2;

  // ref hook is typed the same way
  const ref = useTopicSnapshot("/odom");
  const _rx: { x: number } | undefined = ref.current.data;

  const history = useTopicHistory("/odom");
  const _hx: { x: number } | undefined = history.latest?.data;

  // deprecated aliases stay typed during the transition
  const { data: aliasData } = useTopicLatest("/odom");
  const _aliasPose: { x: number } | undefined = aliasData;
  const aliasRef = useTopicRef("/odom");
  const _aliasRx: { x: number } | undefined = aliasRef.current.data;
}
