from __future__ import annotations

import json
import sys
from io import StringIO
from pathlib import Path
from datetime import date, datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as loc_main
from loc_config import LocConfig, AliasConfig, config_path
from loc_service import LocReport, RepoTotals, build_report, combine_reports, day_window
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


def test_combine_reports_merges_alias_reports() -> None:
    report = combine_reports(
        {
            "personal": LocReport(
                login="ryan",
                label="2026-03-09",
                window_start=datetime(2026, 3, 9, 0, 0, tzinfo=timezone.utc),
                window_end=datetime(2026, 3, 10, 0, 0, tzinfo=timezone.utc),
                generated_at=datetime(2026, 3, 9, 12, 0, tzinfo=timezone.utc),
                repos={"ryan/a": RepoTotals(repo="ryan/a", pushes=1, commits=1, additions=10, deletions=3)},
                pushes=1,
                commits=1,
                additions=10,
                deletions=3,
                warnings=[],
            ),
            "wiom": LocReport(
                login="ryan-wiom",
                label="2026-03-09",
                window_start=datetime(2026, 3, 9, 0, 0, tzinfo=timezone.utc),
                window_end=datetime(2026, 3, 10, 0, 0, tzinfo=timezone.utc),
                generated_at=datetime(2026, 3, 9, 12, 0, tzinfo=timezone.utc),
                repos={"wiom/b": RepoTotals(repo="wiom/b", pushes=2, commits=3, additions=30, deletions=5)},
                pushes=2,
                commits=3,
                additions=30,
                deletions=5,
                warnings=["rate limited"],
            ),
        },
        label="2026-03-09",
        window_start=datetime(2026, 3, 9, 0, 0, tzinfo=timezone.utc),
        window_end=datetime(2026, 3, 10, 0, 0, tzinfo=timezone.utc),
        now=datetime(2026, 3, 9, 12, 0, tzinfo=timezone.utc),
        extra_warnings=["personal: compare failed"],
    )

    assert report.pushes == 3
    assert report.commits == 4
    assert report.additions == 40
    assert report.deletions == 8
    assert report.warnings == ["personal: compare failed", "wiom: rate limited"]


def test_main_add_saves_alias_config(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    stdout = StringIO()
    original = sys.stdout
    try:
        sys.stdout = stdout
        assert main(["add", "wiom", "ghp_test_wiom"]) == 0
    finally:
        sys.stdout = original

    data = json.loads(config_path().read_text(encoding="utf-8"))
    assert data == {"aliases": {"wiom": {"token": "ghp_test_wiom"}}}
    assert "Saved alias 'wiom'" in stdout.getvalue()


def test_main_aggregates_all_aliases(monkeypatch) -> None:
    monkeypatch.setattr(
        loc_main,
        "load_config",
        lambda: LocConfig(
            aliases={
                "personal": AliasConfig(name="personal", token="token-personal"),
                "wiom": AliasConfig(name="wiom", token="token-wiom"),
            }
        ),
    )

    class DummyLoader:
        def start(self) -> None:
            pass

        def stop(self) -> None:
            pass

    class DummyClient:
        def __init__(self, token: str | None = None) -> None:
            self.token = token

    monkeypatch.setattr(loc_main, "Loader", DummyLoader)
    monkeypatch.setattr(loc_main, "GitHubClient", DummyClient)

    def fake_build_report(client, *, label, window_start, window_end, now):
        if client.token == "token-personal":
            return LocReport(
                login="ryan",
                label=label,
                window_start=window_start,
                window_end=window_end,
                generated_at=now,
                repos={"ryan/a": RepoTotals(repo="ryan/a", pushes=1, commits=1, additions=10, deletions=3)},
                pushes=1,
                commits=1,
                additions=10,
                deletions=3,
                warnings=[],
            )
        return LocReport(
            login="ryan-wiom",
            label=label,
            window_start=window_start,
            window_end=window_end,
            generated_at=now,
            repos={"wiom/b": RepoTotals(repo="wiom/b", pushes=2, commits=2, additions=5, deletions=1)},
            pushes=2,
            commits=2,
            additions=5,
            deletions=1,
            warnings=[],
        )

    monkeypatch.setattr(loc_main, "build_report", fake_build_report)

    stdout = StringIO()
    original = sys.stdout
    try:
        sys.stdout = stdout
        assert main([]) == 0
    finally:
        sys.stdout = original

    rendered = stdout.getvalue()
    assert "scope      : all aliases" in rendered
    assert "aliases    : 2" in rendered
    assert "added      : 15" in rendered
    assert "deleted    : 4" in rendered


def test_main_prints_specific_alias_report(monkeypatch) -> None:
    monkeypatch.setattr(
        loc_main,
        "load_config",
        lambda: LocConfig(
            aliases={"wiom": AliasConfig(name="wiom", token="token-wiom")}
        ),
    )

    class DummyLoader:
        def start(self) -> None:
            pass

        def stop(self) -> None:
            pass

    class DummyClient:
        def __init__(self, token: str | None = None) -> None:
            self.token = token

    monkeypatch.setattr(loc_main, "Loader", DummyLoader)
    monkeypatch.setattr(loc_main, "GitHubClient", DummyClient)
    monkeypatch.setattr(
        loc_main,
        "build_report",
        lambda client, *, label, window_start, window_end, now: LocReport(
            login="ryangerardwilson-wiom",
            label=label,
            window_start=window_start,
            window_end=window_end,
            generated_at=now,
            repos={"wiom/b": RepoTotals(repo="wiom/b", pushes=1, commits=1, additions=9, deletions=2)},
            pushes=1,
            commits=1,
            additions=9,
            deletions=2,
            warnings=[],
        ),
    )

    stdout = StringIO()
    original = sys.stdout
    try:
        sys.stdout = stdout
        assert main(["wiom"]) == 0
    finally:
        sys.stdout = original

    rendered = stdout.getvalue()
    assert "scope      : wiom" in rendered
    assert "login      : ryangerardwilson-wiom" in rendered
    assert "added      : 9" in rendered
