from __future__ import annotations

import sys
from io import StringIO
from pathlib import Path
from datetime import date, datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loc_service import RepoTotals, build_report, day_window
from main import main


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def viewer_login(self) -> str:
        return "ryan"

    def api(self, path: str):
        self.calls.append(path)
        if path == "users/ryan/events?per_page=100&page=1":
            return [
                {
                    "type": "PushEvent",
                    "created_at": "2026-03-09T01:00:00Z",
                    "repo": {"name": "ryan/a"},
                    "payload": {
                        "ref": "refs/heads/main",
                        "before": "1111111111111111111111111111111111111111",
                        "head": "2222222222222222222222222222222222222222",
                        "commits": [{"sha": "2222222222222222222222222222222222222222"}],
                    },
                },
                {
                    "type": "PushEvent",
                    "created_at": "2026-03-09T02:00:00Z",
                    "repo": {"name": "ryan/a"},
                    "payload": {
                        "ref": "refs/heads/main",
                        "before": "2222222222222222222222222222222222222222",
                        "head": "3333333333333333333333333333333333333333",
                        "commits": [{"sha": "3333333333333333333333333333333333333333"}],
                    },
                },
                {
                    "type": "PushEvent",
                    "created_at": "2026-03-08T10:00:00Z",
                    "repo": {"name": "ryan/old"},
                    "payload": {},
                },
            ]
        if path == "users/ryan/events?per_page=100&page=2":
            return []
        if path == "repos/ryan/a/compare/1111111111111111111111111111111111111111...2222222222222222222222222222222222222222":
            return {
                "commits": [{"sha": "c1"}],
                "files": [{"additions": 10, "deletions": 3}],
            }
        if path == "repos/ryan/a/compare/2222222222222222222222222222222222222222...3333333333333333333333333333333333333333":
            return {
                "commits": [{"sha": "c1"}, {"sha": "c2"}],
                "files": [
                    {"additions": 10, "deletions": 3},
                    {"additions": 4, "deletions": 1},
                ],
            }
        if path == "repos/ryan/a/commits/c1":
            return {"stats": {"additions": 10, "deletions": 3}}
        if path == "repos/ryan/a/commits/c2":
            return {"stats": {"additions": 4, "deletions": 1}}
        raise AssertionError(path)

def test_main_rejects_unknown_args() -> None:
    stderr = StringIO()
    original = sys.stderr
    try:
        sys.stderr = stderr
        assert main(["--bad"]) == 1
    finally:
        sys.stderr = original
    assert "Unknown flag '--bad'" in stderr.getvalue()


def test_day_window() -> None:
    start, end = day_window(date(2026, 3, 9), timezone.utc)
    assert start.isoformat() == "2026-03-09T00:00:00+00:00"
    assert end.isoformat() == "2026-03-10T00:00:00+00:00"


def test_build_report_dedupes_commit_stats() -> None:
    report = build_report(
        FakeClient(),
        label="2026-03-09",
        window_start=datetime(2026, 3, 9, 0, 0, tzinfo=timezone.utc),
        window_end=datetime(2026, 3, 10, 0, 0, tzinfo=timezone.utc),
        now=datetime(2026, 3, 9, 12, 0, tzinfo=timezone.utc),
    )

    assert report.login == "ryan"
    assert report.label == "2026-03-09"
    assert report.pushes == 2
    assert report.commits == 2
    assert report.additions == 14
    assert report.deletions == 4
    assert report.net == 10
    assert list(report.repos) == ["ryan/a"]
    repo = report.repos["ryan/a"]
    assert isinstance(repo, RepoTotals)
    assert repo.pushes == 2
    assert repo.commits == 2
    assert repo.branches == {"main"}
