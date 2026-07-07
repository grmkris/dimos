// The app's typed hooks — bound once to the generated topic map (dimos.topics.gen.ts, from
// `deno task gen-types`), then imported everywhere instead of `@dimos/react` so the whole app is typed.
import { createDimosHooks } from "@dimos/react";
import type { DimosCommands, DimosTopics } from "./dimos.topics.gen.ts";

export const {
  useDimosClient,
  useModules,
  useTopic,
  useTopicSnapshot,
  useTopicStats,
} = createDimosHooks<DimosTopics, DimosCommands>();

// Map-agnostic hooks re-exported so `../dimos` is the one import site for every panel.
export {
  useCapabilities,
  useCommands,
  useRpc,
  useServers,
  useConnectionState,
  useTeleop,
  useTopics,
  useVideo,
} from "@dimos/react";
