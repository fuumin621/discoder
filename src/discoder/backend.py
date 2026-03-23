"""Backend abstraction for AI coding agent CLIs."""

from abc import ABC, abstractmethod
from typing import AsyncIterator


class Backend(ABC):
    """Abstract base class for coding agent backends (Claude Code, Codex, etc.)."""

    @abstractmethod
    def build_cmd(
        self,
        prompt: str,
        session_id: str | None = None,
        model: str | None = None,
        continue_last: bool = False,
        cwd: str | None = None,
    ) -> list[str]:
        """Build the CLI command list."""
        ...

    @abstractmethod
    def build_stream_cmd(
        self,
        prompt: str,
        session_id: str | None = None,
        model: str | None = None,
        continue_last: bool = False,
        cwd: str | None = None,
    ) -> list[str]:
        """Build the CLI command list for streaming output."""
        ...

    @abstractmethod
    def parse_result(self, stdout: str, session_id: str | None) -> dict:
        """Parse non-streaming CLI output into a result dict.

        Returns dict with keys: result, session_id, error, cost_usd
        """
        ...

    @abstractmethod
    async def parse_stream(
        self,
        proc_stdout,
        session_id: str | None,
    ) -> AsyncIterator[tuple[str, object]]:
        """Parse streaming output line by line.

        Yields (event_type, data) tuples:
          - ("text", str)   — text chunk
          - ("tool", str)   — tool/command description
          - ("done", dict)  — final result
          - ("error", str)  — error message
        """
        ...

    @abstractmethod
    def handoff_command(self, session_id: str, cwd: str) -> str:
        """Return the terminal command to resume a session."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Backend display name."""
        ...
