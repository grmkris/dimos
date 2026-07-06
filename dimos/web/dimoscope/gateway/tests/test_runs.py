#!/usr/bin/env python3
# Copyright 2026 Dimensional Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Unit tests for the runs plane (browser start/stop of a dimos blueprint/replay): the RUNS_CTL gate,
# name allowlisting (the web never composes argv), start-replaces-active, and stop-with-escalation.
# The CLI spawn and the run registry are faked — no processes are launched.
#
# Run: uv run pytest dimos/web/dimoscope/gateway/tests/test_runs.py -q
import asyncio
import json
import pathlib
import sys
import types

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent))  # dimoscope root → gateway pkg

from gateway import runs


class FakeRequest:
    def __init__(self, body: dict):
        self._body = body

    async def json(self) -> dict:
        return self._body


def _body(resp) -> dict:
    return json.loads(resp.body)


def _entry(run_id: str = "r1", pid: int = 4242, blueprint: str = "unitree-go2"):
    return types.SimpleNamespace(
        run_id=run_id,
        pid=pid,
        blueprint=blueprint,
        started_at="2026-07-06T12:00:00+00:00",
        original_argv=["dimos", "--replay", "--replay-db", "go2_short", "run", blueprint],
    )


def test_disabled_gate_rejects_start_and_stop(monkeypatch):
    monkeypatch.setattr(runs, "RUNS_CTL", False)
    start = asyncio.run(runs.start_run(FakeRequest({"blueprint": "unitree-go2"})))
    stop = asyncio.run(runs.stop_run())
    assert start.status_code == 403 and stop.status_code == 403


def test_unknown_blueprint_and_recording_are_rejected(monkeypatch):
    monkeypatch.setattr(runs, "RUNS_CTL", True)
    monkeypatch.setattr(runs, "_dbs", lambda: ["go2_short"])
    bad_bp = asyncio.run(runs.start_run(FakeRequest({"blueprint": "rm -rf /"})))
    bad_db = asyncio.run(runs.start_run(FakeRequest({"blueprint": "unitree-go2", "db": "nope"})))
    assert bad_bp.status_code == 400 and bad_db.status_code == 400


def test_start_stops_the_active_run_then_spawns(monkeypatch):
    monkeypatch.setattr(runs, "RUNS_CTL", True)
    monkeypatch.setattr(runs, "_dbs", lambda: ["go2_short"])
    calls: list = []

    async def fake_stop():
        calls.append("stop")
        return "stopped"

    async def fake_spawn(blueprint, db):
        calls.append(("spawn", blueprint, db))
        return True, "✓ DimOS running in background"

    monkeypatch.setattr(runs, "_stop_active", fake_stop)
    monkeypatch.setattr(runs, "_spawn", fake_spawn)
    monkeypatch.setattr(runs, "_active", lambda: {"runId": "r2"})
    resp = asyncio.run(runs.start_run(FakeRequest({"blueprint": "unitree-go2", "db": "go2_short"})))
    assert resp.status_code == 200
    assert calls == ["stop", ("spawn", "unitree-go2", "go2_short")]
    assert _body(resp)["active"] == {"runId": "r2"}


def test_failed_spawn_surfaces_the_cli_tail(monkeypatch):
    monkeypatch.setattr(runs, "RUNS_CTL", True)
    monkeypatch.setattr(runs, "_dbs", lambda: [])

    async def fake_stop():
        return None

    async def fake_spawn(blueprint, db):
        return False, "Error: health check failed"

    monkeypatch.setattr(runs, "_stop_active", fake_stop)
    monkeypatch.setattr(runs, "_spawn", fake_spawn)
    monkeypatch.setattr(runs, "_active", lambda: None)
    resp = asyncio.run(runs.start_run(FakeRequest({"blueprint": "go2-load"})))
    assert resp.status_code == 500
    assert "health check failed" in _body(resp)["error"]


def test_stop_escalates_to_force_when_term_fails(monkeypatch):
    monkeypatch.setattr(runs, "RUNS_CTL", True)
    entries = [_entry(), _entry(), None]  # alive at first+second poll, gone after force
    monkeypatch.setattr(runs, "get_most_recent", lambda alive_only=True: entries.pop(0))
    forced: list = []
    monkeypatch.setattr(
        runs, "stop_entry", lambda entry, force=False: (forced.append(force), ("ok", force))[1]
    )
    msg = asyncio.run(runs._stop_active())
    assert msg == "ok"
    assert forced == [False, True]  # SIGTERM first, then the SIGKILL escalation


def test_slow_start_reports_in_progress_without_killing(monkeypatch):
    """Past the health-check timeout the starter keeps running (it registers itself later) — the
    handler reports still-starting instead of killing it."""
    monkeypatch.setattr(runs, "START_TIMEOUT_S", 0.05)
    killed: list = []

    class FakeProc:
        returncode = None
        stdout = None

        async def communicate(self):
            await asyncio.sleep(10)

        def kill(self):
            killed.append(True)

    async def fake_exec(*argv, **kw):
        return FakeProc()

    monkeypatch.setattr(runs.asyncio, "create_subprocess_exec", fake_exec)
    ok, tail = asyncio.run(runs._spawn("unitree-go2", "go2_short"))
    assert ok is False
    assert "still starting" in tail
    assert killed == []  # the slow starter must survive


def test_state_clears_stale_error_when_a_run_is_active(monkeypatch):
    monkeypatch.setattr(runs, "RUNS_CTL", True)
    monkeypatch.setattr(runs, "get_most_recent", lambda alive_only=True: _entry())
    monkeypatch.setattr(runs, "_dbs", lambda: ["go2_short"])
    monkeypatch.setattr(runs, "_last_error", "still starting after 180s")
    st = runs._state()
    assert st["active"] is not None
    assert st["error"] is None  # the live run wins over the stale start error


def test_state_surfaces_active_run_and_replay_db(monkeypatch):
    monkeypatch.setattr(runs, "RUNS_CTL", True)
    monkeypatch.setattr(runs, "get_most_recent", lambda alive_only=True: _entry())
    monkeypatch.setattr(runs, "_dbs", lambda: ["go2_short"])
    st = runs._state()
    assert st["enabled"] is True
    assert st["active"]["blueprint"] == "unitree-go2"
    assert st["active"]["replayDb"] == "go2_short"
    assert st["blueprints"] == runs.BLUEPRINTS
