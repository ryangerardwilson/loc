from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from github_client import GitHubClient


def test_github_client_injects_pat_into_gh_environment() -> None:
    with patch(
        "github_client.subprocess.run",
        return_value=SimpleNamespace(returncode=0, stdout='{"login":"ryan"}', stderr=""),
    ) as run:
        login = GitHubClient(token="ghp_test_token").viewer_login()

    assert login == "ryan"
    env = run.call_args.kwargs["env"]
    assert env["GH_TOKEN"] == "ghp_test_token"
    assert env["GITHUB_TOKEN"] == "ghp_test_token"
