"""Forge batch simulation runner: Java discovery, command building, process management."""
import asyncio
import datetime
import logging
import os
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

from models.state import CFG, BatchState
from services.deck_service import parse_dck_file

log = logging.getLogger("lab.batch")


def _find_java17() -> str:
    search_dirs = [r'C:\Program Files\Eclipse Adoptium', r'C:\Program Files\Java']
    for d in search_dirs:
        if os.path.isdir(d):
            for child in os.listdir(d):
                if child.startswith('jdk-17'):
                    candidate = os.path.join(d, child, 'bin', 'java.exe')
                    if os.path.isfile(candidate):
                        return candidate
    return 'java'


_JAVA17_PATH = None


def get_java17() -> str:
    global _JAVA17_PATH
    if _JAVA17_PATH is None:
        _JAVA17_PATH = _find_java17()
    return _JAVA17_PATH


def build_java_command(
    decks: list, num_games: int, threads: int, seed: Optional[int],
    clock: int, output_path: str, use_learned_policy: bool = False,
    policy_server: str = "http://localhost:8080", policy_style: str = "midrange",
    policy_greedy: bool = False, ai_simplified: bool = False,
    ai_think_time_ms: int = -1, max_queue_depth: int = -1,
) -> list:
    """Build the Java command list for launching a Forge batch simulation."""
    java17 = get_java17()
    forge_jar = CFG.forge_jar
    cmd = [
        java17, '-jar', forge_jar, 'sim',
        '-decks', ','.join(str(d) for d in decks),
        '-games', str(num_games),
        '-threads', str(threads),
        '-clock', str(clock),
        '-output', output_path,
    ]
    if seed is not None:
        cmd += ['-seed', str(seed)]
    if use_learned_policy:
        cmd += ['-policy', policy_style, '-policyServer', policy_server]
    if policy_greedy:
        cmd += ['-policyGreedy']
    if ai_simplified:
        cmd += ['-aiSimplified']
    if ai_think_time_ms > 0:
        cmd += ['-aiThinkTimeMs', str(ai_think_time_ms)]
    if max_queue_depth > 0:
        cmd += ['-maxQueueDepth', str(max_queue_depth)]
    return cmd


def _run_process_blocking(state: BatchState, cmd: list):
    """Run Forge subprocess, parse progress, generate deck reports."""
    log.info(f"Running: {' '.join(cmd)}")
    state.started_at = datetime.datetime.now().isoformat()
    state.status = "running"
    env = os.environ.copy()
    java17 = get_java17()
    java_bin = os.path.dirname(java17)
    if java_bin:
        env["JAVA_HOME"] = os.path.dirname(java_bin)
        env["PATH"] = java_bin + os.pathsep + env.get("PATH", "")
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, env=env,
        )
    except Exception as e:
        state.status = "error"
        state.error = str(e)
        log.error(f"Failed to start subprocess: {e}")
        return
    last_activity = [time.monotonic()]
    stall_limit = 300  # 5 min
    def watchdog():
        while proc.poll() is None:
            if (time.monotonic() - last_activity[0]) > stall_limit:
                log.warning("Stall detected, killing process")
                proc.kill()
                state.status = "error"
                state.error = "Stall detected (5 min no output)"
                return
            time.sleep(5)
    wd = threading.Thread(target=watchdog, daemon=True)
    wd.start()
    output_lines = []
    for line in proc.stdout:
        last_activity[0] = time.monotonic()
        line = line.rstrip()
        output_lines.append(line)
        gm = re.match(r'\[Game (\d+)/(\d+)\]', line)
        if gm:
            state.games_done = int(gm.group(1))
            state.games_total = int(gm.group(2))
        pm = re.match(r'\[PROGRESS\].*?(\d+\.?\d*)\s*sims/sec', line)
        if pm:
            state.throughput = float(pm.group(1))
    proc.wait()
    state.log = '\n'.join(output_lines)
    if proc.returncode != 0:
        state.status = "error"
        state.error = f"Exit code {proc.returncode}"
    else:
        state.status = "done"
        state.games_done = state.games_total
    state.ended_at = datetime.datetime.now().isoformat()


async def run_batch_subprocess(
    state: BatchState, decks: list, num_games: int, threads: int,
    seed: Optional[int] = None, clock: int = 6000, output_path: str = "results",
    use_learned_policy: bool = False, **kwargs,
):
    """Async wrapper that runs Forge subprocess in executor."""
    cmd = build_java_command(
        decks, num_games, threads, seed, clock, output_path,
        use_learned_policy=use_learned_policy, **kwargs,
    )
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _run_process_blocking, state, cmd)
