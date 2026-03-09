#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from datetime import date, datetime
from typing import Sequence
from urllib.error import URLError
from urllib.request import Request, urlopen

from github_client import GitHubCLIError, GitHubClient
from loc_service import LocReport, build_report, day_window

try:
    from _version import __version__
except Exception:  # pragma: no cover
    __version__ = "0.0.0"

INSTALL_URL = "https://raw.githubusercontent.com/ryangerardwilson/loc/main/install.sh"
LATEST_RELEASE_API = "https://api.github.com/repos/ryangerardwilson/loc/releases/latest"


class UsageError(ValueError):
    """Raised for invalid CLI usage."""


def _version_tuple(value: str) -> tuple[int, ...]:
    parts: list[int] = []
    for chunk in value.strip().lstrip("v").split("."):
        try:
            parts.append(int(chunk))
        except ValueError:
            break
    return tuple(parts)


def _fetch_latest_version() -> str | None:
    try:
        req = Request(LATEST_RELEASE_API, headers={"Accept": "application/vnd.github+json"})
        with urlopen(req, timeout=10) as resp:  # nosec B310
            payload = resp.read()
    except (URLError, TimeoutError):
        return None
    try:
        data = json.loads(payload)
    except Exception:
        return None
    tag = data.get("tag_name")
    if isinstance(tag, str) and tag.strip():
        return tag.strip().lstrip("v")
    return None


def _run_upgrade() -> int:
    latest_version = _fetch_latest_version()
    if latest_version:
        current_tuple = _version_tuple(__version__)
        latest_tuple = _version_tuple(latest_version)
        if current_tuple and latest_tuple and current_tuple >= latest_tuple:
            print(f"loc is already up to date (version {__version__}).")
            return 0
    try:
        curl = subprocess.Popen(
            ["curl", "-fsSL", INSTALL_URL],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError:
        print("Upgrade requires curl", file=sys.stderr)
        return 1

    try:
        bash = subprocess.Popen(["bash", "-s", "--", "--upgrade"], stdin=curl.stdout)
        if curl.stdout is not None:
            curl.stdout.close()
    except FileNotFoundError:
        print("Upgrade requires bash", file=sys.stderr)
        curl.terminate()
        curl.wait()
        return 1

    bash_rc = bash.wait()
    curl_rc = curl.wait()
    if curl_rc != 0:
        stderr = curl.stderr.read().decode("utf-8", errors="replace") if curl.stderr else ""
        if stderr:
            sys.stderr.write(stderr)
        return curl_rc
    return bash_rc


def _print_help() -> None:
    print(
        "loc - count lines pushed to GitHub today across your repos\n\n"
        "Usage:\n"
        "  loc                 Count today in local timezone\n"
        "  loc 2026-03-09      Count a specific day in local timezone\n"
        "  loc -j              Print JSON instead of text\n"
        "  loc -h              Show this help\n"
        "  loc -v              Show installed version\n"
        "  loc -u              Reinstall latest release if newer exists\n"
    )


def parse_args(argv: Sequence[str]) -> tuple[bool, bool, bool, bool, date | None]:
    show_help = False
    show_version = False
    do_upgrade = False
    as_json = False
    target_day: date | None = None

    for arg in argv:
        if arg == "-h":
            show_help = True
            continue
        if arg == "-v":
            show_version = True
            continue
        if arg == "-u":
            do_upgrade = True
            continue
        if arg == "-j":
            as_json = True
            continue
        if arg.startswith("-"):
            raise UsageError(f"Unknown flag '{arg}'")
        if target_day is not None:
            raise UsageError("Usage: loc [YYYY-MM-DD] [-j]")
        try:
            target_day = date.fromisoformat(arg)
        except ValueError as exc:
            raise UsageError("Date must be YYYY-MM-DD") from exc

    if show_version and (show_help or do_upgrade or as_json or target_day is not None):
        raise UsageError("-v cannot be combined with other arguments")
    if show_help and (show_version or do_upgrade or as_json or target_day is not None):
        raise UsageError("-h cannot be combined with other arguments")
    if do_upgrade and (show_version or show_help or as_json or target_day is not None):
        raise UsageError("-u cannot be combined with other arguments")

    return show_help, show_version, do_upgrade, as_json, target_day


def _report_as_dict(report: LocReport) -> dict[str, object]:
    start, end = day_window(report.target_day, report.generated_at.tzinfo)
    repos = [
        {
            "repo": item.repo,
            "pushes": item.pushes,
            "commits": item.commits,
            "additions": item.additions,
            "deletions": item.deletions,
            "net": item.net,
            "branches": sorted(item.branches),
        }
        for item in report.repos.values()
    ]
    return {
        "login": report.login,
        "date": report.target_day.isoformat(),
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "generated_at": report.generated_at.isoformat(),
        "repo_count": len(report.repos),
        "pushes": report.pushes,
        "commits": report.commits,
        "additions": report.additions,
        "deletions": report.deletions,
        "net": report.net,
        "repos": repos,
        "warnings": report.warnings,
    }


def _print_text(report: LocReport) -> None:
    start, end = day_window(report.target_day, report.generated_at.tzinfo)
    print(f"login      : {report.login}")
    print(f"date       : {report.target_day.isoformat()}")
    print(f"window     : {start.isoformat()} -> {end.isoformat()}")
    print(f"repos      : {len(report.repos)}")
    print(f"pushes     : {report.pushes}")
    print(f"commits    : {report.commits}")
    print(f"added      : {report.additions}")
    print(f"deleted    : {report.deletions}")
    print(f"net        : {report.net}")

    for idx, repo in enumerate(report.repos.values(), start=1):
        print()
        print(f"[{idx}]-----")
        print(f"repo       : {repo.repo}")
        print(f"pushes     : {repo.pushes}")
        print(f"commits    : {repo.commits}")
        print(f"added      : {repo.additions}")
        print(f"deleted    : {repo.deletions}")
        print(f"net        : {repo.net}")
        print(f"branches   : {', '.join(sorted(repo.branches))}")

    if report.warnings:
        print()
        for warning in report.warnings:
            print(f"warning    : {warning}")


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    try:
        show_help, show_version, do_upgrade, as_json, target_day = parse_args(argv)
    except UsageError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if show_help:
        _print_help()
        return 0
    if show_version:
        print(__version__)
        return 0
    if do_upgrade:
        return _run_upgrade()

    now = datetime.now().astimezone()
    target_day = target_day or now.date()

    try:
        report = build_report(GitHubClient(), target_day=target_day, now=now)
    except GitHubCLIError as exc:
        print(f"GitHub CLI error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"loc failed: {exc}", file=sys.stderr)
        return 1

    if as_json:
        print(json.dumps(_report_as_dict(report), indent=2))
    else:
        _print_text(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
