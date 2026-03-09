#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from datetime import datetime
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
            "loc\n\n"
            "flags:\n"
            "  loc -h\n"
            "    show this help\n"
            "  loc -v\n"
            "    print the installed version\n"
            "  loc -u\n"
            "    upgrade to the latest release\n\n"
            "features:\n"
            "  count today's pushed lines of code\n"
            "  # loc\n"
            "  loc\n"
        )
    )


def parse_args(argv: Sequence[str]) -> tuple[bool, bool, bool]:
    show_help = False
    show_version = False
    do_upgrade = False

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
        raise UsageError(f"Unknown flag '{arg}'")

    if show_version and (show_help or do_upgrade):
        raise UsageError("-v cannot be combined with other arguments")
    if show_help and (show_version or do_upgrade):
        raise UsageError("-h cannot be combined with other arguments")
    if do_upgrade and (show_version or show_help):
        raise UsageError("-u cannot be combined with other arguments")

    return show_help, show_version, do_upgrade


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

    try:
        show_help, show_version, do_upgrade = parse_args(argv)
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


if __name__ == "__main__":
    raise SystemExit(main())
