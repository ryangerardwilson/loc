from __future__ import annotations

import json
import subprocess
from typing import Any


class GitHubCLIError(RuntimeError):
    """Raised when gh api returns an error."""


class GitHubClient:
    def __init__(self, executable: str = "gh") -> None:
        self.executable = executable

    def api(self, path: str) -> Any:
        command = [self.executable, "api", path]
        try:
            proc = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
        except subprocess.TimeoutExpired as exc:
            raise GitHubCLIError(f"gh api timed out for {path}") from exc
        if proc.returncode != 0:
            stderr = proc.stderr.strip() or proc.stdout.strip() or "gh api failed"
            raise GitHubCLIError(stderr)
        try:
            return json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise GitHubCLIError("gh api returned invalid JSON") from exc

    def viewer_login(self) -> str:
        payload = self.api("user")
        login = payload.get("login")
        if not isinstance(login, str) or not login.strip():
            raise GitHubCLIError("Unable to determine authenticated GitHub login")
        return login.strip()
