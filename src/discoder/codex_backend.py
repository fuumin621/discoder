"""Codex CLI backend implementation."""

import json
import logging
from typing import AsyncIterator

from .backend import Backend

logger = logging.getLogger(__name__)


def _command_summary(command: str) -> str:
    """Extract a short summary from a shell command string."""
    # Codex wraps commands as: /bin/bash -lc 'actual command'
    if "-lc " in command:
        # Extract the inner command
        idx = command.index("-lc ") + 4
        inner = command[idx:].strip().strip("'\"")
    else:
        inner = command
    first_line = inner.split("\n")[0][:60]
    return f"Shell: `{first_line}`"


class CodexBackend(Backend):
    """Backend for OpenAI Codex CLI."""

    @property
    def name(self) -> str:
        return "codex"

    def build_cmd(
        self,
        prompt: str,
        session_id: str | None = None,
        model: str | None = None,
        continue_last: bool = False,
        cwd: str | None = None,
    ) -> list[str]:
        if continue_last:
            cmd = ["codex", "exec", "resume", "--last", prompt]
        elif session_id:
            cmd = ["codex", "exec", "resume", session_id, prompt]
        else:
            cmd = ["codex", "exec", prompt]
            # -C is only supported on fresh exec, not on resume
            if cwd:
                cmd.extend(["-C", cwd])
        if model:
            cmd.extend(["-m", model])
        cmd.append("--dangerously-bypass-approvals-and-sandbox")
        return cmd

    def build_stream_cmd(
        self,
        prompt: str,
        session_id: str | None = None,
        model: str | None = None,
        continue_last: bool = False,
        cwd: str | None = None,
    ) -> list[str]:
        if continue_last:
            cmd = ["codex", "exec", "resume", "--last", "--json", prompt]
        elif session_id:
            cmd = ["codex", "exec", "resume", session_id, "--json", prompt]
        else:
            cmd = ["codex", "exec", "--json", prompt]
            # -C is only supported on fresh exec, not on resume
            if cwd:
                cmd.extend(["-C", cwd])
        if model:
            cmd.extend(["-m", model])
        cmd.append("--dangerously-bypass-approvals-and-sandbox")
        return cmd

    def parse_result(self, stdout: str, session_id: str | None) -> dict:
        """Parse Codex JSONL output for non-streaming mode.

        Codex exec --json always outputs JSONL, so we parse all lines.
        """
        result_session_id = session_id
        texts = []
        error = None

        for line in stdout.strip().splitlines():
            if not line.strip():
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue

            evt_type = data.get("type")
            if evt_type == "thread.started":
                result_session_id = data.get("thread_id", result_session_id)
            elif evt_type == "item.completed":
                item = data.get("item", {})
                if item.get("type") == "agent_message":
                    texts.append(item.get("text", ""))
            elif evt_type == "turn.failed":
                err = data.get("error", {})
                error = err.get("message", str(err))
            elif evt_type == "error":
                error = data.get("message", str(data))

        return {
            "result": "\n\n".join(texts) if texts else None,
            "session_id": result_session_id,
            "error": error,
            "cost_usd": None,
        }

    async def parse_stream(
        self,
        proc_stdout,
        session_id: str | None,
    ) -> AsyncIterator[tuple[str, object]]:
        result_session_id = session_id
        texts = []

        async for line in proc_stdout:
            line = line.decode().strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue

            evt_type = data.get("type")

            if evt_type == "thread.started":
                result_session_id = data.get("thread_id", result_session_id)

            elif evt_type == "item.started":
                item = data.get("item", {})
                if item.get("type") == "command_execution":
                    cmd = item.get("command", "")
                    yield ("tool", _command_summary(cmd))

            elif evt_type == "item.completed":
                item = data.get("item", {})
                item_type = item.get("type")
                if item_type == "agent_message":
                    text = item.get("text", "")
                    if text:
                        texts.append(text)
                        yield ("text", text)
                elif item_type == "command_execution":
                    # Command finished — could show output summary
                    pass

            elif evt_type == "turn.completed":
                yield ("done", {
                    "result": "\n\n".join(texts) if texts else "",
                    "session_id": result_session_id,
                    "error": None,
                    "cost_usd": None,
                })
                return

            elif evt_type == "turn.failed":
                err = data.get("error", {})
                yield ("error", err.get("message", str(err)))
                return

            elif evt_type == "error":
                yield ("error", data.get("message", str(data)))
                return

        # Stream ended without turn.completed
        if texts:
            yield ("done", {
                "result": "\n\n".join(texts),
                "session_id": result_session_id,
                "error": None,
            })

    def handoff_command(self, session_id: str, cwd: str) -> str:
        return f"cd {cwd} && codex resume {session_id}"
