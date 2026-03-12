"""Claude Code CLI wrapper."""

import asyncio
import json
import logging
import os
import subprocess

logger = logging.getLogger(__name__)

_BASE_ENV = {**os.environ, "CLAUDECODE": "", "IS_SANDBOX": "1"}


def _tool_detail(tool_name: str, inp: dict) -> str:
    """Format tool name + key input for display."""
    if tool_name == "Bash":
        cmd = inp.get("command", "")
        # Show first line of command, truncated
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
    # Fallback: show any string-valued input for unknown tools
    if inp:
        for v in inp.values():
            if isinstance(v, str) and v:
                return f"{tool_name}: {v[:50]}"
    return tool_name


def _build_cmd(
    prompt: str,
    session_id: str | None = None,
    model: str | None = None,
    continue_last: bool = False,
    output_format: str = "json",
) -> list[str]:
    cmd = ["claude", "-p", prompt, "--output-format", output_format]
    if output_format == "stream-json":
        cmd.append("--verbose")
    if continue_last:
        cmd.append("--continue")
    elif session_id:
        cmd.extend(["--resume", session_id])
    if model:
        cmd.extend(["--model", model])
    cmd.append("--dangerously-skip-permissions")
    return cmd


def run_claude(
    prompt: str,
    session_id: str | None = None,
    cwd: str | None = None,
    model: str | None = None,
    continue_last: bool = False,
    timeout: int = 900,
) -> dict:
    """Run claude CLI and return the result.

    Returns dict with keys: result, session_id, error
    """
    cmd = _build_cmd(prompt, session_id, model, continue_last, "json")
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
        logger.error("Claude CLI timed out")
        return {"result": None, "session_id": session_id, "error": "Timed out"}

    if proc.returncode != 0:
        error_msg = proc.stderr.strip()
        logger.error(f"Claude CLI error: {error_msg}")
        return {"result": None, "session_id": session_id, "error": error_msg}

    try:
        data = json.loads(proc.stdout.strip())
        return {
            "result": data.get("result", ""),
            "session_id": data.get("session_id", session_id),
            "error": None,
            "cost_usd": data.get("total_cost_usd"),
        }
    except json.JSONDecodeError as e:
        raw = proc.stdout.strip()
        logger.error(f"Failed to parse JSON: {e}\nRaw: {raw[:500]}")
        return {"result": raw, "session_id": session_id, "error": None}


async def stream_claude(
    prompt: str,
    session_id: str | None = None,
    cwd: str | None = None,
    model: str | None = None,
    continue_last: bool = False,
    timeout: int = 900,
):
    """Stream claude CLI output. Yields (event_type, data) tuples.

    event_type: "text" (partial text), "done" (final result dict), "error" (error string)
    """
    cmd = _build_cmd(prompt, session_id, model, continue_last, "stream-json")
    cmd.append("--include-partial-messages")
    logger.info(f"Streaming: {' '.join(cmd)}")

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
        env=_BASE_ENV,
        limit=1024 * 1024,  # 1MB line buffer for large stream-json responses
    )

    result_session_id = session_id
    full_text = ""
    current_tool = None
    tool_input_json = ""

    try:
        async with asyncio.timeout(timeout):
            async for line in proc.stdout:
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

    except asyncio.TimeoutError:
        proc.kill()
        yield ("error", "Timed out")
        return
    except (asyncio.CancelledError, GeneratorExit):
        proc.kill()
        await proc.wait()
        return
    except Exception as e:
        proc.kill()
        yield ("error", str(e))
        return

    await proc.wait()
    if proc.returncode != 0:
        stderr = await proc.stderr.read()
        yield ("error", stderr.decode().strip())
    elif full_text:
        yield ("done", {
            "result": full_text,
            "session_id": result_session_id,
            "error": None,
        })
