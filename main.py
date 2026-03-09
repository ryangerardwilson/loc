#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
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


MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


@dataclass(frozen=True)
class QueryWindow:
    label: str
    start: datetime
    end: datetime


class Loader:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not sys.stdout.isatty():
            return
        frames = [
            "◐" * 12,
            "◓" * 12,
            "◑" * 12,
            "◒" * 12,
            "◐◓◑◒◐◓◑◒◐◓◑◒",
            "◓◑◒◐◓◑◒◐◓◑◒◐",
            "◑◒◐◓◑◒◐◓◑◒◐◓",
            "◒◐◓◑◒◐◓◑◒◐◓◑",
        ]

        def run() -> None:
            idx = 0
            print("\033[?25l", end="", flush=True)
            while not self._stop.is_set():
                frame = frames[idx % len(frames)]
                idx += 1
                print(f"\r\033[97m{frame}\033[0m", end="", flush=True)
                time.sleep(0.06)
            print("\r" + " " * 12 + "\r", end="", flush=True)
            print("\033[?25h", end="", flush=True)

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._thread is None:
            return
        self._stop.set()
        self._thread.join()


def _muted(text: str) -> str:
    if not sys.stdout.isatty() or "NO_COLOR" in os.environ:
        return text
    return f"\033[38;5;245m{text}\033[0m"


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
        proc = subprocess.run(
            ["gh", "release", "view", "--repo", "ryangerardwilson/loc", "--json", "tagName", "--jq", ".tagName"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        proc = None
    if proc is not None and proc.returncode == 0:
        tag = proc.stdout.strip()
        if tag:
            return tag.lstrip("v")
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
        _muted(
            "loc - count lines pushed to GitHub across your repos\n\n"
            "Usage:\n"
            "  loc -h              Show this help\n"
            "  loc tm 0            Today\n"
            "  loc 2026-03-09      Count a specific day\n"
            "  loc tm 1            Yesterday\n"
            "  loc wm 0            Current calendar week\n"
            "  loc mm 1            Previous calendar month\n"
            "  loc jan             January of current year\n"
            "  loc jan 2024        January 2024\n"
            "  loc -j              Print JSON instead of text\n"
            "  loc -v              Show installed version\n"
            "  loc -u              Reinstall latest release if newer exists\n"
        )
    )


def _start_of_month(target_year: int, target_month: int, tzinfo) -> datetime:
    return datetime(target_year, target_month, 1, tzinfo=tzinfo)


def _shift_month(target_year: int, target_month: int, delta: int) -> tuple[int, int]:
    absolute = (target_year * 12 + (target_month - 1)) - delta
    return absolute // 12, (absolute % 12) + 1


def _parse_non_negative_int(raw: str, label: str) -> int:
    try:
        value = int(raw)
    except ValueError as exc:
        raise UsageError(f"{label} must be an integer") from exc
    if value < 0:
        raise UsageError(f"{label} must be >= 0")
    return value


def resolve_query(tokens: Sequence[str], now: datetime) -> QueryWindow:
    tzinfo = now.tzinfo
    if tzinfo is None:
        raise UsageError("Current time must be timezone-aware")

    if not tokens:
        start, end = day_window(now.date(), tzinfo)
        return QueryWindow(label=now.date().isoformat(), start=start, end=end)

    if len(tokens) == 1:
        token = tokens[0].lower()
        try:
            target_day = date.fromisoformat(tokens[0])
        except ValueError:
            target_day = None
        if target_day is not None:
            start, end = day_window(target_day, tzinfo)
            return QueryWindow(label=target_day.isoformat(), start=start, end=end)
        if token in MONTHS:
            start = _start_of_month(now.year, MONTHS[token], tzinfo)
            end_year, end_month = _shift_month(now.year, MONTHS[token], -1)
            end = _start_of_month(end_year, end_month, tzinfo)
            return QueryWindow(
                label=f"{start.date().isoformat()}..{(end - timedelta(days=1)).date().isoformat()}",
                start=start,
                end=end,
            )
        raise UsageError("Usage: loc [YYYY-MM-DD | tm N | wm N | mm N | mon [YYYY]] [-j]")

    head = tokens[0].lower()
    if head == "tm" and len(tokens) == 2:
        offset = _parse_non_negative_int(tokens[1], "tm")
        target_day = now.date() - timedelta(days=offset)
        start, end = day_window(target_day, tzinfo)
        return QueryWindow(label=target_day.isoformat(), start=start, end=end)

    if head == "wm" and len(tokens) == 2:
        offset = _parse_non_negative_int(tokens[1], "wm")
        week_start_day = now.date() - timedelta(days=now.weekday() + (offset * 7))
        start, _ = day_window(week_start_day, tzinfo)
        end = start + timedelta(days=7)
        return QueryWindow(
            label=f"{week_start_day.isoformat()}..{(week_start_day + timedelta(days=6)).isoformat()}",
            start=start,
            end=end,
        )

    if head == "mm" and len(tokens) == 2:
        offset = _parse_non_negative_int(tokens[1], "mm")
        year_value, month_value = _shift_month(now.year, now.month, offset)
        start = _start_of_month(year_value, month_value, tzinfo)
        end_year, end_month = _shift_month(year_value, month_value, -1)
        end = _start_of_month(end_year, end_month, tzinfo)
        return QueryWindow(
            label=f"{start.date().isoformat()}..{(end - timedelta(days=1)).date().isoformat()}",
            start=start,
            end=end,
        )

    if head in MONTHS and len(tokens) == 2:
        year_value = _parse_non_negative_int(tokens[1], "year")
        if year_value < 1:
            raise UsageError("year must be >= 1")
        start = _start_of_month(year_value, MONTHS[head], tzinfo)
        end_year, end_month = _shift_month(year_value, MONTHS[head], -1)
        end = _start_of_month(end_year, end_month, tzinfo)
        return QueryWindow(
            label=f"{start.date().isoformat()}..{(end - timedelta(days=1)).date().isoformat()}",
            start=start,
            end=end,
        )

    raise UsageError("Usage: loc [YYYY-MM-DD | tm N | wm N | mm N | mon [YYYY]] [-j]")


def parse_args(argv: Sequence[str]) -> tuple[bool, bool, bool, bool, list[str]]:
    show_help = False
    show_version = False
    do_upgrade = False
    as_json = False
    selector_tokens: list[str] = []

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
        selector_tokens.append(arg)

    if show_version and (show_help or do_upgrade or as_json or selector_tokens):
        raise UsageError("-v cannot be combined with other arguments")
    if show_help and (show_version or do_upgrade or as_json or selector_tokens):
        raise UsageError("-h cannot be combined with other arguments")
    if do_upgrade and (show_version or show_help or as_json or selector_tokens):
        raise UsageError("-u cannot be combined with other arguments")

    return show_help, show_version, do_upgrade, as_json, selector_tokens


def _report_as_dict(report: LocReport) -> dict[str, object]:
    return {
        "date": report.label,
        "repos": len(report.repos),
        "pushes": report.pushes,
        "commits": report.commits,
        "additions": report.additions,
        "deletions": report.deletions,
        "net": report.net,
        "warnings": report.warnings,
    }


def _print_text(report: LocReport) -> None:
    print(f"date       : {report.label}")
    print(f"repos      : {len(report.repos)}")
    print(f"pushes     : {report.pushes}")
    print(f"commits    : {report.commits}")
    print(f"added      : {report.additions}")
    print(f"deleted    : {report.deletions}")
    print(f"net        : {report.net}")

    if report.warnings:
        print()
        for warning in report.warnings:
            print(f"warning    : {warning}")


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    if not argv:
        _print_help()
        return 0

    try:
        show_help, show_version, do_upgrade, as_json, selector_tokens = parse_args(argv)
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
    try:
        query = resolve_query(selector_tokens, now)
    except UsageError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    loader = Loader()

    try:
        if not as_json:
            loader.start()
        report = build_report(
            GitHubClient(),
            label=query.label,
            window_start=query.start,
            window_end=query.end,
            now=now,
        )
    except GitHubCLIError as exc:
        loader.stop()
        print(f"GitHub CLI error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        loader.stop()
        print(f"loc failed: {exc}", file=sys.stderr)
        return 1
    loader.stop()

    if as_json:
        print(json.dumps(_report_as_dict(report), indent=2))
    else:
        _print_text(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
