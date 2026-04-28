"""Utility for invoking the `claude` CLI in non-interactive (`-p`) mode.

Strips Claude Code's default scaffolding (CLAUDE.md auto-discovery, hooks,
skills, MCP servers, tools, dynamic system-prompt sections) so the call
behaves close to a bare Anthropic API request.
"""

import subprocess

DEFAULT_TIMEOUT_SECONDS = 600

# Flags that suppress Claude Code's default context injection.
MINIMAL_FLAGS = (
    "--system-prompt",
    "",
    "--tools",
    "",
    "--setting-sources",
    "",
    "--strict-mcp-config",
    "--disable-slash-commands",
)


class ClaudeCodeCLIError(RuntimeError):
    """Raised when `claude -p` exits with a non-zero status."""

    def __init__(self, returncode: int, stdout: str, stderr: str):
        detail = stderr.strip() or stdout.strip()
        super().__init__(f"claude -p exited with code {returncode}: {detail}")
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def run_claude_code(
    prompt: str,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    extra_args: list[str] | None = None,
) -> str:
    """Run `claude -p <prompt>` and return stdout.

    Raises:
        ClaudeCodeCLIError: if claude exits with a non-zero status.
        subprocess.TimeoutExpired: if the call exceeds `timeout` seconds.
        FileNotFoundError: if the `claude` CLI is not on PATH.
    """
    cmd = ["claude", "-p", *MINIMAL_FLAGS, prompt, *(extra_args or [])]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise ClaudeCodeCLIError(result.returncode, result.stdout, result.stderr)
    return result.stdout
