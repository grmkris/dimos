// Example — the copy-me panel: each common SDK use case as one small block. Live at ?tab=example ·
// walkthrough: app/README.md.
//
// Every hook comes from ./dimos — the app's one-file typed binding (src/dimos.ts) over the topic +
// command maps that `deno task gen-types` writes from the blueprints. That binding is what makes
// topic NAMES autocomplete and message payloads fully typed below — no generics, no casts.
// In your own app: copy src/dimos.ts + the generated dimos.topics.gen.ts. Without codegen the same
// hooks import from "@dimos/react" and you pass the type yourself:
//   const pose = useTopic<geometry_msgs.PoseStamped>("/odom", { maxHz: 5 });
import { useState } from "react";
import { jsonPretty } from "@dimos/react";
import {
  useCommands,
  useModules,
  useRpc,
  useConnectionState,
  useTopic,
  useTopics,
  useTopicStats,
} from "./dimos";

export function Example() {
  // ── Use case 1 · connect + discover ──────────────────────────────────────────────────────────
  // Both live-update on their own; DimosProvider (see main.tsx) owns the connection.
  const status = useConnectionState();
  const topics = useTopics();

  // ── Use case 2 · subscribe to a specific topic, typed ────────────────────────────────────────
  // "/nav/pose" autocompletes (try renaming it), and `pose.data` IS a geometry_msgs.PoseStamped —
  // `.pose.position.x` below is checked by tsc. maxHz is server-side QoS: the gateway downsamples
  // before bytes reach the wire. The subscription lives exactly as long as this component.
  const pose = useTopic("/nav/pose", { maxHz: 5 });

  // ── Use case 3 · inspect ANY discovered topic (name only known at runtime) ───────────────────
  // Payload type is unknown here by construction — render it as JSON. The maxHz select shows the
  // same server-side rate control live: switch it and watch the hz readout follow.
  const [picked, setPicked] = useState<string>();
  const [maxHz, setMaxHz] = useState(10);
  const topic = picked ?? topics[0]?.topic ?? null;
  const { data, meta } = useTopic(topic, { maxHz });
  const stats = useTopicStats(topic); // passive rolling window — hz / bytes/s / latency

  // ── Use case 4 · call RPC ─────────────────────────────────────────────────────────────────────
  // Generic: the gateway advertises its whitelist (RPC_COMMANDS in gateway/egress.py) → buttons.
  // Typed: `modules` autocompletes targets/methods/args from the generated command map.
  const commands = useCommands();
  const { call } = useRpc();
  const modules = useModules();
  const [rpcOut, setRpcOut] = useState<string>();
  const show = (label: string, p: Promise<unknown>) =>
    p.then((r) => setRpcOut(`${label} → ${JSON.stringify(r)}`))
      .catch((e) => setRpcOut(`${label} ✗ ${(e as Error).message}`));

  return (
    <div className="panel" style={{ maxWidth: 760, margin: "0 auto" }}>
      <div className="panel-title">
        Example · the copy-me panel (app/src/Example.tsx · app/README.md)
      </div>
      <div className="muted small">
        transport: {status} · {topics.length} topics discovered
      </div>

      {/* use case 2 — typed fields straight off the message; x/y autocomplete, no casts */}
      <div className="muted small" style={{ marginTop: 10 }}>
        typed /nav/pose ·{" "}
        {pose.data
          ? `x=${pose.data.pose.position.x.toFixed(2)} y=${pose.data.pose.position.y.toFixed(2)}`
          : "waiting — publishes when a nav source runs (deno task scope:nav or dog)"}
      </div>

      {/* use case 3 — pick any topic; switching moves the one subscription over */}
      <div style={{ display: "flex", gap: 6, margin: "10px 0" }}>
        <select
          className="server-select"
          style={{ flex: 1, minWidth: 0 }}
          value={topic ?? ""}
          onChange={(e) => setPicked(e.target.value)}
        >
          {topics.length === 0 && <option value="">discovering topics…</option>}
          {topics.map((t) => (
            <option key={t.topic} value={t.topic}>
              {t.topic} · {t.type}
            </option>
          ))}
        </select>
        <select
          className="server-select"
          title="server-side rate cap (maxHz) — the gateway sheds before the wire"
          value={maxHz}
          onChange={(e) => setMaxHz(Number(e.target.value))}
        >
          {[2, 10, 30, 120].map((hz) => (
            <option key={hz} value={hz}>≤{hz} Hz</option>
          ))}
        </select>
      </div>
      <div className="muted small">
        {stats ? `${stats.hz} Hz · ${(stats.bytesPerSec / 1000).toFixed(1)} kB/s` : "no stats yet"}
        {meta?.latencyMs != null ? ` · ${meta.latencyMs.toFixed(1)} ms latency` : ""}
      </div>
      <pre className="json">{data !== undefined ? jsonPretty(data) : "waiting for a message…"}</pre>

      {/* use case 4 — advertised whitelist buttons + one typed-proxy call */}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 8 }}>
        {commands.map((c) => (
          <button
            key={`${c.target}/${c.method}`}
            className="tab"
            title={`${c.target}.${c.method}()`}
            onClick={() => show(c.label, call(c.target, c.method))}
          >
            {c.label}
          </button>
        ))}
        {modules && (
          <button
            className="tab"
            title="typed proxy: modules.GO2Load.status() — target/method/args autocomplete"
            onClick={() => show("GO2Load.status (typed)", modules.GO2Load.status())}
          >
            GO2Load.status (typed)
          </button>
        )}
      </div>
      {rpcOut && (
        <div className="muted small" style={{ marginTop: 6 }}>
          {rpcOut}
        </div>
      )}

      {/* where to look next — the app's real panels, one hook each */}
      <div className="muted small" style={{ marginTop: 12 }}>
        more: camera → useVideo (panels/CameraView.tsx) · teleop → useTeleop (panels/TeleopPad.tsx) ·
        render loops → useTopicSnapshot (panels/WorldView.tsx) · codegen → packages/web/README.md
      </div>
    </div>
  );
}
