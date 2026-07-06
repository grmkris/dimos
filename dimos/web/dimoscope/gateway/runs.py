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

# Browser-controlled runs: GET/POST/DELETE /runs starts and stops a dimos blueprint (optionally a
# recording replay) on the gateway host — the same thing an operator does from a shell with
# `dimos --replay --replay-db <db> run <blueprint>`. The endpoint passes an allowlisted blueprint
# NAME and a known recording NAME only, spawns the CLI in daemon mode (health-checked, watchdogged,
# registered in the run registry), and stops through the same registry `dimos stop` uses — so a run
# started from the UI and one started from a shell are the same kind of thing, visible to both.
# OFF unless RUNS_CTL=1 (never expose process control on a public box by accident).
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import os
from pathlib import Path
import sys
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

import dimos
from dimos.core.run_registry import get_most_recent, stop_entry
from dimos.utils.logging_config import setup_logger

logger = setup_logger()

RUNS_CTL = os.environ.get("RUNS_CTL", "0") == "1"
# The web picks from names, never composes argv: blueprints the UI may launch.
BLUEPRINTS = ["unitree-go2", "go2-load"]
REPO_ROOT = Path(dimos.__file__).resolve().parents[1]
START_TIMEOUT_S = 180  # `run -d` health-checks before daemonizing; first runs may pull data/LFS

_lock = asyncio.Lock()  # one start/stop in flight at a time
_last_error: str | None = None


def _dbs() -> list[str]:
    """Recordings the CLI can resolve: data/.lfs/<name>.db.tar.gz (what resolve_named_path pulls)."""
    lfs = REPO_ROOT / "data" / ".lfs"
    return sorted(p.name.removesuffix(".db.tar.gz") for p in lfs.glob("*.db.tar.gz"))


def _active() -> dict[str, Any] | None:
    entry = get_most_recent(alive_only=True)
    if entry is None:
        return None
    uptime_s = 0
    try:
        started = datetime.fromisoformat(entry.started_at)
        uptime_s = int((datetime.now(timezone.utc) - started).total_seconds())
    except Exception:
        pass
    return {
        "runId": entry.run_id,
        "pid": entry.pid,
        "blueprint": entry.blueprint,
        "uptimeS": uptime_s,
        # replay flags ride cli_args/original_argv; surface the db when present
        "replayDb": _argv_db(getattr(entry, "original_argv", None) or []),
    }


def _argv_db(argv: list[str]) -> str | None:
    try:
        return argv[argv.index("--replay-db") + 1]
    except (ValueError, IndexError):
        return None


def _state() -> dict[str, Any]:
    return {
        "enabled": RUNS_CTL,
        "active": _active(),
        "blueprints": BLUEPRINTS,
        "dbs": _dbs(),
        "error": _last_error,
    }


async def _spawn(blueprint: str, db: str | None) -> tuple[bool, str]:
    """`uv run dimos [--replay --replay-db <db>] run -d <blueprint>` — returns (ok, output tail)."""
    argv = [sys.executable, "-m", "dimos.robot.cli.dimos"]
    if db:
        argv += ["--replay", "--replay-db", db]
    argv += ["run", "-d", blueprint]
    proc = await asyncio.create_subprocess_exec(
        *argv,
        cwd=REPO_ROOT,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=START_TIMEOUT_S)
    except asyncio.TimeoutError:
        proc.kill()
        return False, f"start timed out after {START_TIMEOUT_S}s"
    tail = out.decode(errors="replace").strip()[-400:]
    return (proc.returncode or 0) == 0, tail


async def _stop_active() -> str | None:
    """Stop the registered run (SIGTERM, escalate to SIGKILL if it lingers). None = nothing ran."""
    entry = get_most_recent(alive_only=True)
    if entry is None:
        return None
    msg, ok = await asyncio.to_thread(stop_entry, entry)
    if not ok:
        msg, _ = await asyncio.to_thread(stop_entry, entry, True)  # force
    # stop_entry signals; give the tree a moment so a follow-up start doesn't race a dying zenoh peer
    for _ in range(20):
        if get_most_recent(alive_only=True) is None:
            break
        await asyncio.sleep(0.5)
    return msg


async def get_state() -> JSONResponse:
    return JSONResponse(_state())


async def start_run(req: Request) -> JSONResponse:
    global _last_error
    if not RUNS_CTL:
        return JSONResponse({"error": "runs control disabled (set RUNS_CTL=1)"}, status_code=403)
    try:
        body = await req.json()
        blueprint = str(body.get("blueprint", ""))
        db = body.get("db")
        db = str(db) if db else None
    except Exception:
        return JSONResponse(
            {"error": 'body must be JSON: {"blueprint": "<name>", "db": "<recording>|null"}'},
            status_code=400,
        )
    if blueprint not in BLUEPRINTS:
        return JSONResponse({"error": f"unknown blueprint: {blueprint}"}, status_code=400)
    if db is not None and db not in _dbs():
        return JSONResponse({"error": f"unknown recording: {db}"}, status_code=400)
    async with _lock:
        await _stop_active()  # one managed run — starting replaces whatever runs
        ok, tail = await _spawn(blueprint, db)
        _last_error = None if ok else tail
        if ok:
            logger.info("run started", blueprint=blueprint, db=db)
        else:
            logger.warning("run start failed", blueprint=blueprint, db=db, out=tail[:200])
    return JSONResponse(_state(), status_code=200 if ok else 500)


async def stop_run() -> JSONResponse:
    global _last_error
    if not RUNS_CTL:
        return JSONResponse({"error": "runs control disabled (set RUNS_CTL=1)"}, status_code=403)
    async with _lock:
        msg = await _stop_active()
        _last_error = None
        logger.info("run stopped", result=msg or "nothing running")
    return JSONResponse(_state())
