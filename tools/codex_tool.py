import os
import subprocess
from pathlib import Path

from hermes_cli.auth import resolve_codex_runtime_credentials


def run(prompt: str) -> str:
    """Execute Codex CLI using Hermes-managed openai-codex auth.

    Maintenance policy:
    - Do NOT hardcode CODEX_HOME.
    - Reuse Hermes auth flow (hermes auth/login), then sync tokens to Codex CLI.
    """
    env = os.environ.copy()

    try:
        # Uses Hermes auth store (~/.hermes/auth.json), performs refresh if needed,
        # and syncs tokens to Codex CLI auth.json.
        resolve_codex_runtime_credentials(force_refresh=False)
    except Exception as exc:
        return (
            "[ERROR]\n"
            f"Codex credentials are not ready: {exc}\n"
            "Run: hermes auth add openai-codex (or hermes login --provider openai-codex)"
        )

    repo_root = Path(__file__).resolve().parents[1]
    cmd = [
        "codex",
        "exec",
        "--skip-git-repo-check",
        prompt,
    ]

    result = subprocess.run(
        cmd,
        cwd=str(repo_root),
        env=env,
        capture_output=True,
        text=True,
        timeout=1800,
    )

    if result.returncode != 0:
        return f"[ERROR]\n{result.stderr}"

    return result.stdout.strip()
