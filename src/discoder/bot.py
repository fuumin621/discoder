"""Discord bot for discoder."""

import asyncio
import json
import logging
import os
import time as _time

import discord
from discord import app_commands

from .claude import run_claude, stream_claude
from .session import SessionStore

logger = logging.getLogger(__name__)

DISCORD_MSG_LIMIT = 2000


def chunk_message(text: str, limit: int = DISCORD_MSG_LIMIT) -> list[str]:
    """Split a message into chunks that fit Discord's character limit."""
    if len(text) <= limit:
        return [text]

    chunks = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break

        split_at = text.rfind("\n", 0, limit)
        if split_at <= 0:
            split_at = limit

        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")

    return chunks


OPTIONS_SUFFIX = '\n\n(At the end of your reply, suggest 4 short follow-up replies the user might send. Format: <options>["a","b","c","d"]</options> max 25 chars each, in the same language as the conversation)'


def parse_options(text: str) -> tuple[str, list[str]]:
    """Extract <options> JSON from response text. Returns (clean_text, options)."""
    import re
    match = re.search(r'<options>\s*(\[.*?\])\s*</options>', text, re.DOTALL)
    if not match:
        return text, []
    try:
        options = json.loads(match.group(1))
        clean = text[:match.start()].rstrip()
        return clean, [str(o)[:80] for o in options[:4]]
    except (json.JSONDecodeError, TypeError):
        return text, []


class SuggestView(discord.ui.View):
    """Buttons for suggested replies."""

    def __init__(self, suggestions: list[str], session_info: dict, bot: "DiscoderBot"):
        super().__init__(timeout=None)
        self.bot = bot
        self.session_info = session_info
        self.suggestions = suggestions

        for i, text in enumerate(suggestions[:4]):
            button = discord.ui.Button(
                label=text[:80],
                style=discord.ButtonStyle.secondary,
                custom_id=f"suggest_{i}",
            )
            button.callback = self._make_callback(text)
            self.add_item(button)

    def _make_callback(self, text: str):
        async def callback(interaction: discord.Interaction):
            self.stop()
            # Disable all buttons
            for item in self.children:
                item.disabled = True
            await interaction.response.edit_message(view=self)

            # Send the selected text as a regular message, bot will pick it up
            await interaction.channel.send(f"**> {text}**")

            # Enqueue (since the bot ignores its own messages and
            # the above message is from the bot via interaction)
            await self.bot._enqueue(
                interaction.channel, text, self.session_info
            )

        return callback


class DiscoderBot(discord.Client):
    def __init__(self, default_cwd: str | None = None):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)

        self.tree = app_commands.CommandTree(self)
        self.sessions = SessionStore()
        self.default_cwd = default_cwd or os.getcwd()
        self._thread_queues: dict[str, asyncio.Queue] = {}
        self._thread_workers: dict[str, asyncio.Task] = {}

        self._register_commands()

    def _register_commands(self):
        @self.tree.command(name="new", description="Start a new Claude Code session")
        @app_commands.describe(
            prompt="Your prompt for Claude",
            dir="Working directory (default: discoder start directory)",
        )
        async def cmd_new(
            interaction: discord.Interaction,
            prompt: str,
            dir: str | None = None,
        ):
            logger.info(f"/new called: prompt={prompt[:50]}, dir={dir}")
            cwd = dir or self.default_cwd

            if not os.path.isdir(cwd):
                await interaction.response.send_message(
                    f"Directory not found: `{cwd}`", ephemeral=True
                )
                return

            await interaction.response.send_message(
                f"Starting new session in `{cwd}`..."
            )
            response = await interaction.original_response()

            thread = await response.create_thread(
                name=f"discoder: {prompt[:50]}",
                auto_archive_duration=1440,
            )

            info = {"session_id": None, "cwd": cwd, "model": None}
            try:
                await self._handle_session_message(thread, prompt, info)
            except Exception as e:
                logger.error(f"/new failed: {e}", exc_info=True)
                await thread.send(f"Error: {str(e)[:1900]}")

        @self.tree.command(
            name="sessions", description="List active Claude Code sessions"
        )
        async def cmd_sessions(interaction: discord.Interaction):
            sessions = self.sessions.list_sessions()
            if not sessions:
                await interaction.response.send_message(
                    "No active sessions.", ephemeral=True
                )
                return

            lines = ["**Active Sessions:**"]
            for tid, info in sessions.items():
                sid = info["session_id"]
                cwd = info["cwd"]
                lines.append(f"- Thread <#{tid}> | `{sid[:8]}...` | `{cwd}`")

            await interaction.response.send_message("\n".join(lines), ephemeral=True)

        @self.tree.command(
            name="clear",
            description="Clear all saved sessions",
        )
        async def cmd_clear(interaction: discord.Interaction):
            sessions = self.sessions.list_sessions()
            if not sessions:
                await interaction.response.send_message(
                    "No sessions to clear.", ephemeral=True
                )
                return

            count = len(sessions)
            self.sessions.clear_all()
            await interaction.response.send_message(
                f"Cleared {count} session(s).", ephemeral=True
            )

        @self.tree.command(
            name="resume",
            description="Resume a session (omit session_id for most recent)",
        )
        @app_commands.describe(
            session_id="Claude Code session ID (omit for most recent)",
            dir="Working directory (default: discoder start directory)",
        )
        async def cmd_resume(
            interaction: discord.Interaction,
            session_id: str = None,
            dir: str = None,
        ):
            cwd = dir or self.default_cwd
            use_continue = session_id is None

            if session_id:
                existing = self.sessions.get_by_session_id(session_id)
                if existing:
                    tid, _ = existing
                    await interaction.response.send_message(
                        f"Session already active in <#{tid}>", ephemeral=True
                    )
                    return

            label = f"last session in `{cwd}`" if use_continue else f"session `{session_id[:8]}...`"
            await interaction.response.send_message(f"Resuming {label}...")
            response = await interaction.original_response()

            thread_name = f"discoder: resumed {'latest' if use_continue else session_id[:8]}"
            thread = await response.create_thread(
                name=thread_name,
                auto_archive_duration=1440,
            )

            resume_prompt = "Summarize our session in the same language the user has been using. Format:\n## Summary\n(what we were working on, 1-2 lines)\n## Last interaction\n(user's last request and your response, 1-2 lines each)"
            info = {"session_id": session_id, "cwd": cwd, "model": None}

            try:
                await self._handle_session_message(
                    thread, resume_prompt, info,
                    continue_last=use_continue, append_options=False,
                )
            except Exception as e:
                logger.error(f"/resume failed: {e}", exc_info=True)
                await thread.send(f"Error: {str(e)[:1900]}")

        @self.tree.command(
            name="handoff",
            description="Get the session ID to continue in terminal",
        )
        async def cmd_handoff(interaction: discord.Interaction):
            if not isinstance(interaction.channel, discord.Thread):
                await interaction.response.send_message(
                    "Use this command inside a session thread.", ephemeral=True
                )
                return

            info = self.sessions.get_by_thread(str(interaction.channel.id))
            if not info:
                await interaction.response.send_message(
                    "No session found for this thread.", ephemeral=True
                )
                return

            sid = info["session_id"]
            cwd = info["cwd"]
            await interaction.response.send_message(
                f"**Session ID:** `{sid}`\n"
                f"**Directory:** `{cwd}`\n\n"
                f"**Resume in terminal:**\n"
                f"```\ncd {cwd} && claude --resume {sid}\n```",
                ephemeral=True,
            )

        @self.tree.command(
            name="compact",
            description="Compress conversation context to save tokens",
        )
        async def cmd_compact(interaction: discord.Interaction):
            if not isinstance(interaction.channel, discord.Thread):
                await interaction.response.send_message(
                    "Use this command inside a session thread.", ephemeral=True
                )
                return

            info = self.sessions.get_by_thread(str(interaction.channel.id))
            if not info:
                await interaction.response.send_message(
                    "No session found for this thread.", ephemeral=True
                )
                return

            await interaction.response.send_message("Compacting context...")

            result = await asyncio.to_thread(
                run_claude,
                "/compact",
                info["session_id"],
                info["cwd"],
                info.get("model"),
            )

            if result["error"]:
                await interaction.channel.send(
                    f"Error:\n```\n{result['error'][:1900]}\n```"
                )
            else:
                await interaction.channel.send(
                    f"Context compacted.\n{result['result'][:1900]}"
                )

        @self.tree.command(
            name="model",
            description="Change the model for this session",
        )
        @app_commands.describe(model="Model to use")
        @app_commands.choices(model=[
            app_commands.Choice(name="opus", value="opus"),
            app_commands.Choice(name="sonnet", value="sonnet"),
            app_commands.Choice(name="haiku", value="haiku"),
        ])
        async def cmd_model(interaction: discord.Interaction, model: app_commands.Choice[str]):
            if not isinstance(interaction.channel, discord.Thread):
                await interaction.response.send_message(
                    "Use this command inside a session thread.", ephemeral=True
                )
                return

            info = self.sessions.get_by_thread(str(interaction.channel.id))
            if not info:
                await interaction.response.send_message(
                    "No session found for this thread.", ephemeral=True
                )
                return

            self.sessions.set_model(str(interaction.channel.id), model.value)
            await interaction.response.send_message(
                f"Model changed to **{model.value}** for this session."
            )

        @self.tree.command(
            name="cost",
            description="Show the cost of the current session",
        )
        async def cmd_cost(interaction: discord.Interaction):
            if not isinstance(interaction.channel, discord.Thread):
                await interaction.response.send_message(
                    "Use this command inside a session thread.", ephemeral=True
                )
                return

            info = self.sessions.get_by_thread(str(interaction.channel.id))
            if not info:
                await interaction.response.send_message(
                    "No session found for this thread.", ephemeral=True
                )
                return

            await interaction.response.defer(ephemeral=True)

            result = await asyncio.to_thread(
                run_claude,
                "/cost",
                info["session_id"],
                info["cwd"],
                info.get("model"),
            )

            if result["error"]:
                await interaction.followup.send(
                    f"Error:\n```\n{result['error'][:1900]}\n```", ephemeral=True
                )
            else:
                await interaction.followup.send(
                    result["result"][:2000] or "No cost info available.",
                    ephemeral=True,
                )

        @self.tree.command(
            name="stop",
            description="Stop the current running task in this thread",
        )
        async def cmd_stop(interaction: discord.Interaction):
            if not isinstance(interaction.channel, discord.Thread):
                await interaction.response.send_message(
                    "Use this command inside a session thread.", ephemeral=True
                )
                return

            tid = str(interaction.channel.id)
            worker = self._thread_workers.get(tid)
            if not worker or worker.done():
                await interaction.response.send_message(
                    "Nothing is running in this thread.", ephemeral=True
                )
                return

            worker.cancel()
            # Drain the queue
            if tid in self._thread_queues:
                q = self._thread_queues[tid]
                while not q.empty():
                    try:
                        q.get_nowait()
                    except asyncio.QueueEmpty:
                        break

            await interaction.response.send_message("⏹️ Stopped.")

    async def on_ready(self):
        logger.info(f"Logged in as {self.user}")

        @self.tree.error
        async def on_app_command_error(interaction, error):
            logger.error(f"Command error: {error}", exc_info=True)
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(f"Error: {error}", ephemeral=True)
                else:
                    await interaction.response.send_message(f"Error: {error}", ephemeral=True)
            except Exception:
                pass

        for guild in self.guilds:
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            logger.info(f"Slash commands synced to guild: {guild.name}")
        logger.info("Slash commands synced")

    async def _handle_session_message(
        self, channel: discord.Thread, content: str, info: dict,
        continue_last: bool = False, append_options: bool = True,
    ):
        """Process a message in a session thread with streaming + suggestions."""
        prompt = content + OPTIONS_SUFFIX if append_options else content

        reply_msg = await channel.send("⏳")
        buffer = ""
        last_update = _time.monotonic()
        UPDATE_INTERVAL = 3.0
        final_result = None

        async for event_type, data in stream_claude(
            prompt,
            session_id=info["session_id"],
            cwd=info["cwd"],
            model=info.get("model"),
            continue_last=continue_last,
        ):
            if event_type == "tool":
                tool_name = data
                # Flush buffered text as a finalized message
                if buffer.strip():
                    display, _ = parse_options(buffer)
                    chunks = chunk_message(display)
                    try:
                        await reply_msg.edit(content=chunks[0])
                    except discord.HTTPException:
                        pass
                    for chunk in chunks[1:]:
                        try:
                            await channel.send(chunk)
                        except discord.HTTPException:
                            pass
                    buffer = ""
                # New message for tool status (not reused for text)
                tool_msg = await channel.send(f"🔧 `{tool_name}`...")
                reply_msg = None  # Next text will create a new message
                last_update = _time.monotonic()

            elif event_type == "text":
                buffer += data
                if reply_msg is None:
                    reply_msg = await channel.send("...")
                    last_update = _time.monotonic()
                now = _time.monotonic()
                if now - last_update >= UPDATE_INTERVAL and buffer:
                    display, _ = parse_options(buffer)
                    # Show last 1900 chars, prefer cutting at newline but don't require it
                    if len(display) > 1900:
                        display = display[-1900:]
                        # Try to cut at newline for cleaner display
                        first_nl = display.find("\n")
                        if first_nl > 0 and first_nl < 200:
                            display = display[first_nl + 1:]
                    try:
                        await reply_msg.edit(content=display + "\n...")
                    except discord.HTTPException:
                        pass
                    last_update = now

            elif event_type == "done":
                final_result = data
                break

            elif event_type == "error":
                if reply_msg:
                    await reply_msg.edit(content=f"❌ Error:\n```\n{data[:1900]}\n```")
                else:
                    await channel.send(f"❌ Error:\n```\n{data[:1900]}\n```")
                return

        if final_result and final_result.get("error"):
            if reply_msg:
                await reply_msg.edit(
                    content=f"❌ Error:\n```\n{final_result['error'][:1900]}\n```"
                )
            else:
                await channel.send(f"❌ Error:\n```\n{final_result['error'][:1900]}\n```")
            return

        if final_result and final_result.get("session_id") and final_result["session_id"] != info["session_id"]:
            info = {**info, "session_id": final_result["session_id"]}
            self.sessions.create(
                str(channel.id), final_result["session_id"], info["cwd"]
            )

        raw_text = (final_result or {}).get("result") or buffer or "(empty response)"
        text, suggestions = parse_options(raw_text)
        chunks = chunk_message(text)

        # First chunk replaces the streaming message
        last_msg = None
        if reply_msg:
            try:
                await reply_msg.edit(content=chunks[0])
                last_msg = reply_msg
            except discord.HTTPException:
                last_msg = await channel.send(chunks[0][:1900])
        else:
            last_msg = await channel.send(chunks[0][:1900])
        # Remaining chunks as new messages
        for chunk in chunks[1:]:
            try:
                last_msg = await channel.send(chunk)
            except discord.HTTPException:
                logger.warning(f"Failed to send chunk (len={len(chunk)})")

        # Mark completion with reaction
        if last_msg:
            try:
                await last_msg.add_reaction("✅")
            except discord.HTTPException:
                pass

        # Show suggested reply buttons
        if suggestions:
            view = SuggestView(suggestions, info, self)
            await channel.send("", view=view)

    async def _enqueue(self, channel: discord.Thread, content: str, info: dict):
        """Enqueue a message for sequential processing per thread."""
        tid = str(channel.id)
        if tid not in self._thread_queues:
            self._thread_queues[tid] = asyncio.Queue()

        await self._thread_queues[tid].put((channel, content, info))

        if tid not in self._thread_workers or self._thread_workers[tid].done():
            self._thread_workers[tid] = asyncio.create_task(self._queue_worker(tid))

    async def _queue_worker(self, tid: str):
        """Process queued messages for a thread one at a time."""
        queue = self._thread_queues[tid]
        while not queue.empty():
            channel, content, info = await queue.get()
            try:
                # Refresh session info in case it was updated
                fresh = self.sessions.get_by_thread(tid)
                if fresh:
                    info = fresh
                await self._handle_session_message(channel, content, info)
            except Exception as e:
                logger.error(f"Queue worker error: {e}", exc_info=True)
                try:
                    await channel.send(f"Error: {str(e)[:1900]}")
                except Exception:
                    pass

    async def on_message(self, message: discord.Message):
        if message.author == self.user:
            return

        if not isinstance(message.channel, discord.Thread):
            return

        # Reload sessions from disk (may have been updated externally)
        self.sessions.reload()
        info = self.sessions.get_by_thread(str(message.channel.id))
        if not info:
            return

        await self._enqueue(message.channel, message.content, info)


def run_bot(token: str, default_cwd: str | None = None):
    """Start the Discord bot."""
    bot = DiscoderBot(default_cwd=default_cwd)
    bot.run(token, log_handler=None)
