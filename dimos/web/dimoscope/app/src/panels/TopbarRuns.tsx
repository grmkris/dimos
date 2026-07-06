// What's running, in the topbar — pick a sim blueprint or a recorded replay and start/stop it on
// the gateway host (the same `dimos run` an operator types in a shell; both show up here). Same
// select idiom as the netem/transport dropdowns beside it; renders nothing unless the gateway
// reports runs control enabled (RUNS_CTL=1).
import { useState } from "react";
import { useRuns } from "../runs";

/** One launchable thing per option: a plain blueprint, or unitree-go2 replaying a recording. */
const choiceId = (blueprint: string, db: string | null) => (db ? `db:${db}` : `bp:${blueprint}`);

export function TopbarRuns() {
  const { runs, busy, msg, start, stop } = useRuns();
  const [picked, setPicked] = useState<string>();
  if (!runs?.enabled) return null;

  const activeId = runs.active ? choiceId(runs.active.blueprint, runs.active.replayDb) : null;
  const sel = picked ?? activeId ?? (runs.dbs.length ? `db:${runs.dbs[0]}` : `bp:${runs.blueprints[0]}`);
  const launch = () => {
    const [kind, name] = [sel.slice(0, 2), sel.slice(3)];
    return kind === "db" ? start("unitree-go2", name) : start(name, null);
  };
  const uptime = runs.active ? `up ${Math.floor(runs.active.uptimeS / 60)}m ${runs.active.uptimeS % 60}s` : "stopped";

  return (
    <>
      <select
        className="server-select"
        value={sel}
        disabled={busy}
        onChange={(e) => setPicked(e.target.value)}
        title={`server-side run — ${uptime}${msg ? ` · ${msg}` : ""}${
          runs.error ? ` · last start failed: ${runs.error}` : ""
        }`}
      >
        {runs.blueprints.map((b) => (
          <option key={`bp:${b}`} value={`bp:${b}`}>sim: {b}</option>
        ))}
        {runs.dbs.map((d) => (
          <option key={`db:${d}`} value={`db:${d}`}>replay: {d}</option>
        ))}
      </select>
      {runs.active && sel === activeId
        ? (
          <button className="tab" disabled={busy} onClick={() => stop()} title={`stop ${runs.active.runId} (pid ${runs.active.pid}) · ${uptime}`}>
            ■ stop
          </button>
        )
        : (
          <button className="tab" disabled={busy} onClick={launch} title={runs.active ? "stop the current run and start this one" : "start on the gateway host"}>
            ▶ {runs.active ? "switch" : "run"}
          </button>
        )}
    </>
  );
}
