"""Agent CLI wrapper — dispatches to the configured backend."""

import asyncio
import json
import logging
import os
import subprocess

from .backend import Backend
from .claude_backend import ClaudeBackend
from .codex_backend import CodexBackend

logger = logging.getLogger(__name__)

_BASE_ENV = {**os.environ, "CLAUDECODE": "", "IS_SANDBOX": "1"}


def _kill_safe(proc):
    """Kill a subprocess, ignoring ProcessLookupError if already exited."""
    try:
        proc.kill()
    except ProcessLookupError:
        pass

_BACKENDS: dict[str, type[Backend]] = {
    "claude": ClaudeBackend,
    "codex": CodexBackend,
}

_backend_instance: Backend | None = None


def get_backend(name: str | None = None) -> Backend:
    """Get or create the backend instance."""
    global _backend_instance
    if name:
        cls = _BACKENDS.get(name)
        if not cls:
            raise ValueError(f"Unknown backend: {name}. Available: {list(_BACKENDS.keys())}")
        _backend_instance = cls()
    if _backend_instance is None:
        _backend_instance = ClaudeBackend()
    return _backend_instance


def set_backend(name: str) -> Backend:
    """Set the active backend by name."""
    global _backend_instance
    cls = _BACKENDS.get(name)
    if not cls:
        raise ValueError(f"Unknown backend: {name}. Available: {list(_BACKENDS.keys())}")
    _backend_instance = cls()
    return _backend_instance


def run_claude(
    prompt: str,
    session_id: str | None = None,
    cwd: str | None = None,
    model: str | None = None,
    continue_last: bool = False,
    timeout: int = 900,
) -> dict:
    """Run the agent CLI and return the result.

    Returns dict with keys: result, session_id, error
    """
    backend = get_backend()
    cmd = backend.build_cmd(prompt, session_id, model, continue_last, cwd)
    logger.info(f"Running: {' '.join(cmd)}")

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=cwd,
            env=_BASE_ENV,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        logger.error("Agent CLI timed out")
        return {"result": None, "session_id": session_id, "error": "Timed out"}

    if proc.returncode != 0:
        error_msg = proc.stderr.strip()
        logger.error(f"Agent CLI error: {error_msg}")
        return {"result": None, "session_id": session_id, "error": error_msg}

    return backend.parse_result(proc.stdout, session_id)


async def stream_claude(
    prompt: str,
    session_id: str | None = None,
    cwd: str | None = None,
    model: str | None = None,
    continue_last: bool = False,
    timeout: int = 900,
):
    """Stream agent CLI output. Yields (event_type, data) tuples.

    event_type: "text" (partial text), "tool" (tool use), "done" (final result dict), "error" (error string)
    """
    backend = get_backend()
    cmd = backend.build_stream_cmd(prompt, session_id, model, continue_last, cwd)
    logger.info(f"Streaming: {' '.join(cmd)}")

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
        env=_BASE_ENV,
        limit=1024 * 1024,  # 1MB line buffer for large stream-json responses
    )

    try:
        async with asyncio.timeout(timeout):
            async for event_type, data in backend.parse_stream(proc.stdout, session_id):
                yield (event_type, data)

    except asyncio.TimeoutError:
        _kill_safe(proc)
        yield ("error", "Timed out")
        return
    except (asyncio.CancelledError, GeneratorExit):
        _kill_safe(proc)
        await proc.wait()
        return
    except Exception as e:
        _kill_safe(proc)
        yield ("error", str(e))
        return

    await proc.wait()
    if proc.returncode != 0:
        stderr = await proc.stderr.read()
        error_text = stderr.decode().strip()
        if error_text:
            yield ("error", error_text)
