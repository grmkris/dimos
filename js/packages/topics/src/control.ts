// The browser → gateway control-plane protocol. The SDK (gatewayWs adapter)
// emits these; a gateway validates them at its boundary. Zod is the single
// source of truth — `parseControl` turns an untrusted WS frame into a typed
// message (or null), so the gateway never touches `any`.
import { z } from "zod";

export const ControlMessage = z.discriminatedUnion("op", [
  z.object({
    op: z.literal("subscribe"),
    topic: z.string(),
    maxHz: z.number().optional(),
  }),
  z.object({ op: z.literal("unsubscribe"), topic: z.string() }),
  z.object({
    op: z.literal("rate"),
    topic: z.string(),
    maxHz: z.number().optional(),
  }),
  z.object({ op: z.literal("list") }),
  z.object({
    op: z.literal("teleop"),
    linearX: z.number(),
    angularZ: z.number(),
    ttlMs: z.number().optional(),
  }),
  z.object({ op: z.literal("stop") }),
  z.object({
    op: z.literal("goal"),
    x: z.number(),
    y: z.number(),
    z: z.number().optional(),
  }),
]);

export type ControlMessage = z.infer<typeof ControlMessage>;

/** Parse an untrusted WS frame into a typed control message; null if invalid. */
export function parseControl(raw: string): ControlMessage | null {
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    return null;
  }
  const result = ControlMessage.safeParse(data);
  return result.success ? result.data : null;
}
