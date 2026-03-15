#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from datetime import datetime

from github_client import GitHubCLIError, GitHubClient
from loc_service import LocReport, build_report, day_window
from rgw_cli_contract import AppSpec, resolve_install_script_path, run_app

from _version import __version__

INSTALL_SCRIPT = resolve_install_script_path(__file__)
HELP_TEXT = """loc

flags:
  loc -h
    show this help
  loc -v
    print the installed version
  loc -u
    upgrade to the latest release

features:
  count today's pushed lines of code
  # loc
  loc
"""


class UsageError(ValueError):
    """Raised for invalid CLI usage."""


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


def _dispatch(argv: list[str]) -> int:
    if argv:
        raise UsageError(f"Unknown flag '{argv[0]}'")

    now = datetime.now().astimezone()
    start, end = day_window(now.date(), now.tzinfo)
    loader = Loader()

    try:
        loader.start()
        report = build_report(
            GitHubClient(),
            label=now.date().isoformat(),
            window_start=start,
            window_end=end,
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
    _print_text(report)
    return 0


APP_SPEC = AppSpec(
    app_name="loc",
    version=__version__,
    help_text=HELP_TEXT,
    install_script_path=INSTALL_SCRIPT,
    no_args_mode="dispatch",
)


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    try:
        return run_app(APP_SPEC, argv, _dispatch)
    except UsageError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
