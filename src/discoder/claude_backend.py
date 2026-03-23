"""Claude Code backend implementation."""

import json
import logging
from typing import AsyncIterator

from .backend import Backend

logger = logging.getLogger(__name__)


def _tool_detail(tool_name: str, inp: dict) -> str:
    """Format tool name + key input for display."""
    if tool_name == "Bash":
        cmd = inp.get("command", "")
        first_line = cmd.split("\n")[0][:60]
        return f"Bash: `{first_line}`"
    elif tool_name == "Read":
        path = inp.get("file_path", "")
        return f"Read: `{path.split('/')[-1]}`"
    elif tool_name == "Edit":
        path = inp.get("file_path", "")
        return f"Edit: `{path.split('/')[-1]}`"
    elif tool_name == "Write":
        path = inp.get("file_path", "")
        return f"Write: `{path.split('/')[-1]}`"
    elif tool_name == "Glob":
        return f"Glob: `{inp.get('pattern', '')}`"
    elif tool_name == "Grep":
        return f"Grep: `{inp.get('pattern', '')}`"
    elif tool_name == "Agent":
        desc = inp.get("description", "")
        if desc:
            return f"Agent: {desc}"
        prompt = inp.get("prompt", "")
        if prompt:
            return f"Agent: {prompt[:50]}"
    elif tool_name == "ToolSearch":
        return f"ToolSearch: `{inp.get('query', '')}`"
    if inp:
        for v in inp.values():
            if isinstance(v, str) and v:
                return f"{tool_name}: {v[:50]}"
    return tool_name


class ClaudeBackend(Backend):
    """Backend for Claude Code CLI."""

    @property
    def name(self) -> str:
        return "claude"

    def build_cmd(
        self,
        prompt: str,
        session_id: str | None = None,
        model: str | None = None,
        continue_last: bool = False,
        cwd: str | None = None,
    ) -> list[str]:
        cmd = ["claude", "-p", prompt, "--output-format", "json"]
        if continue_last:
            cmd.append("--continue")
        elif session_id:
            cmd.extend(["--resume", session_id])
        if model:
            cmd.extend(["--model", model])
        cmd.append("--dangerously-skip-permissions")
        return cmd

    def build_stream_cmd(
        self,
        prompt: str,
        session_id: str | None = None,
        model: str | None = None,
        continue_last: bool = False,
        cwd: str | None = None,
    ) -> list[str]:
        cmd = ["claude", "-p", prompt, "--output-format", "stream-json", "--verbose"]
        if continue_last:
            cmd.append("--continue")
        elif session_id:
            cmd.extend(["--resume", session_id])
        if model:
            cmd.extend(["--model", model])
        cmd.append("--dangerously-skip-permissions")
        cmd.append("--include-partial-messages")
        return cmd

    def parse_result(self, stdout: str, session_id: str | None) -> dict:
        try:
            data = json.loads(stdout.strip())
            return {
                "result": data.get("result", ""),
                "session_id": data.get("session_id", session_id),
                "error": None,
                "cost_usd": data.get("total_cost_usd"),
            }
        except json.JSONDecodeError as e:
            raw = stdout.strip()
            logger.error(f"Failed to parse JSON: {e}\nRaw: {raw[:500]}")
            return {"result": raw, "session_id": session_id, "error": None}

    async def parse_stream(
        self,
        proc_stdout,
        session_id: str | None,
    ) -> AsyncIterator[tuple[str, object]]:
        result_session_id = session_id
        full_text = ""
        current_tool = None
        tool_input_json = ""

        async for line in proc_stdout:
            line = line.decode().strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue

            msg_type = data.get("type")

            if msg_type == "stream_event":
                event = data.get("event", {})
                result_session_id = data.get("session_id", result_session_id)
                if event.get("type") == "content_block_start":
                    block = event.get("content_block", {})
                    if block.get("type") == "tool_use":
                        current_tool = block.get("name", "tool")
                        tool_input_json = ""
                    else:
                        current_tool = None
                elif event.get("type") == "content_block_stop":
                    if current_tool and tool_input_json:
                        try:
                            inp = json.loads(tool_input_json)
                            detail = _tool_detail(current_tool, inp)
                        except json.JSONDecodeError:
                            detail = current_tool
                        yield ("tool", detail)
                    elif current_tool:
                        yield ("tool", current_tool)
                    current_tool = None
                    tool_input_json = ""
                elif event.get("type") == "content_block_delta":
                    delta = event.get("delta", {})
                    if delta.get("type") == "text_delta":
                        text = delta.get("text", "")
                        if text:
                            full_text += text
                            yield ("text", text)
                    elif delta.get("type") == "input_json_delta":
                        tool_input_json += delta.get("partial_json", "")

            elif msg_type == "result":
                result_session_id = data.get("session_id", result_session_id)
                yield ("done", {
                    "result": data.get("result", full_text),
                    "session_id": result_session_id,
                    "error": None,
                    "cost_usd": data.get("total_cost_usd"),
                })
                return

        # If we got here without a "result" event, yield what we have
        if full_text:
            yield ("done", {
                "result": full_text,
                "session_id": result_session_id,
                "error": None,
            })

    def handoff_command(self, session_id: str, cwd: str) -> str:
        return f"cd {cwd} && claude --resume {session_id}"
