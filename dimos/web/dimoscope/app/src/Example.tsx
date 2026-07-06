// Example — the smallest useful dimoscope panel, kept as a copy-me starting point for your own
// app. Live at ?tab=example · walkthrough: docs/webapp-guide.md.
//
// Everything imports from @dimos/react, so this file drops into any app unchanged. dimoscope's
// real panels import the same hooks from ./dimos instead — a one-file typed binding over the
// generated topic map (src/dimos.ts + `deno task gen-types`) that autocompletes topic names.
import { useState } from "react";
import {
  jsonPretty,
  useCommands,
  useRpc,
  useStatus,
  useTopicLatest,
  useTopics,
  useTopicStats,
} from "@dimos/react";

export function Example() {
  // Connection + discovery — both live-update on their own; nothing to subscribe for these.
  const status = useStatus();
  const topics = useTopics();

  // One subscription. It exists only while this component is mounted (on-demand end to end:
  // unmount → unsubscribe → the gateway stops sending this topic's bytes to this client).
  // maxHz is server-side QoS — the gateway downsamples before anything hits the wire.
  const [picked, setPicked] = useState<string>();
  const topic = picked ?? topics[0]?.topic ?? null;
  const { data, meta } = useTopicLatest(topic, { maxHz: 10 });
  const stats = useTopicStats(topic); // passive rolling window — hz / bytes/s / latency

  // @rpc commands the gateway whitelists (RPC_COMMANDS in gateway/egress.py). Empty when none
  // are advertised — the button row simply disappears.
  const commands = useCommands();
  const { call } = useRpc();
  const [rpcOut, setRpcOut] = useState<string>();

  return (
    <div className="panel" style={{ maxWidth: 760, margin: "0 auto" }}>
      <div className="panel-title">
        Example · the copy-me panel (app/src/Example.tsx · docs/webapp-guide.md)
      </div>
      <div className="muted small">
        transport: {status} · {topics.length} topics discovered
      </div>

      {/* Pick any discovered topic — switching moves the one subscription over. */}
      <select
        className="server-select"
        style={{ margin: "10px 0", maxWidth: "100%" }}
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

      <div className="muted small">
        {stats ? `${stats.hz} Hz · ${(stats.bytesPerSec / 1000).toFixed(1)} kB/s` : "no stats yet"}
        {meta?.latencyMs != null ? ` · ${meta.latencyMs.toFixed(1)} ms latency` : ""}
      </div>
      <pre className="json">{data !== undefined ? jsonPretty(data) : "waiting for a message…"}</pre>

      {commands.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 8 }}>
          {commands.map((c) => (
            <button
              key={`${c.target}/${c.method}`}
              className="tab"
              title={`${c.target}.${c.method}()`}
              onClick={() =>
                call(c.target, c.method)
                  .then((r) => setRpcOut(`${c.label} → ${JSON.stringify(r)}`))
                  .catch((e) => setRpcOut(`${c.label} ✗ ${(e as Error).message}`))}
            >
              {c.label}
            </button>
          ))}
        </div>
      )}
      {rpcOut && (
        <div className="muted small" style={{ marginTop: 6 }}>
          {rpcOut}
        </div>
      )}
    </div>
  );
}
