// App-global run state (server-side blueprint/replay launcher, GET/POST/DELETE /runs —
// gateway/runs.py, opt-in via RUNS_CTL=1). Same shape as netem.tsx: one provider so the topbar
// control and anything else that cares agree on what's running.
import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import { useGateway } from "./gateway";

export interface RunsActive {
  runId: string;
  pid: number;
  blueprint: string;
  uptimeS: number;
  replayDb: string | null;
}
export interface RunsState {
  enabled: boolean;
  active: RunsActive | null;
  blueprints: string[];
  dbs: string[];
  error: string | null;
}

export async function getRuns(httpBase: string): Promise<RunsState | null> {
  try {
    return await (await fetch(`${httpBase}/runs`)).json();
  } catch {
    return null; // older gateway without /runs, or unreachable
  }
}

async function mutate(httpBase: string, init: RequestInit): Promise<RunsState> {
  const res = await fetch(`${httpBase}/runs`, init);
  const body = await res.json();
  if (!res.ok) throw new Error(String(body.error ?? res.status));
  return body;
}

interface RunsCtx {
  /** null = endpoint absent/unreachable; `enabled: false` = present but not opted in. */
  runs: RunsState | null;
  ready: boolean;
  busy: boolean;
  msg?: string;
  refresh: () => Promise<RunsState | null>;
  /** Start (or replace) the managed run; resolves null (and sets `msg`) on failure. */
  start: (blueprint: string, db: string | null) => Promise<RunsState | null>;
  stop: () => Promise<RunsState | null>;
}
const Ctx = createContext<RunsCtx>({
  runs: null,
  ready: false,
  busy: false,
  refresh: () => Promise.resolve(null),
  start: () => Promise.resolve(null),
  stop: () => Promise.resolve(null),
});
export const useRuns = () => useContext(Ctx);

export function RunsProvider({ children }: { children: ReactNode }) {
  const { gateway } = useGateway();
  const httpBase = `${location.protocol}//${gateway}`;
  const [runs, setRuns] = useState<RunsState | null>(null);
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string>();
  // Bumped by every successful mutation — a slow GET that started earlier must not overwrite it.
  const epoch = useRef(0);

  const refresh = useCallback(async () => {
    const started = epoch.current;
    const st = await getRuns(httpBase);
    if (epoch.current === started) setRuns(st);
    setReady(true);
    return st;
  }, [httpBase]);

  const run = useCallback(async (init: RequestInit) => {
    setBusy(true);
    setMsg(undefined);
    try {
      const st = await mutate(httpBase, init);
      epoch.current++;
      setRuns(st);
      return st;
    } catch (e) {
      setMsg(`✗ ${(e as Error).message}`);
      return null;
    } finally {
      setBusy(false);
    }
  }, [httpBase]);

  const start = useCallback(
    (blueprint: string, db: string | null) =>
      run({
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ blueprint, db }),
      }),
    [run],
  );
  const stop = useCallback(() => run({ method: "DELETE" }), [run]);

  // Mount / gateway change + window focus keep the view honest against shell-side runs;
  // a slow tick only while something runs keeps the uptime readout moving.
  useEffect(() => {
    refresh();
    const onFocus = () => refresh();
    globalThis.addEventListener("focus", onFocus);
    return () => globalThis.removeEventListener("focus", onFocus);
  }, [refresh]);
  const active = !!runs?.enabled && runs.active !== null;
  useEffect(() => {
    if (!active) return;
    const t = setInterval(refresh, 5000);
    return () => clearInterval(t);
  }, [active, refresh]);

  return (
    <Ctx.Provider value={{ runs, ready, busy, msg, refresh, start, stop }}>
      {children}
    </Ctx.Provider>
  );
}
