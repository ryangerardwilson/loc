#!/usr/bin/env python3
from __future__ import annotations

import sys
import threading
import time
from datetime import datetime
from getpass import getpass
import os
from pathlib import Path
import shlex
import subprocess

from github_client import GitHubCLIError, GitHubClient
from loc_config import CONFIG_BOOTSTRAP_TEXT, ConfigError, LocConfig, config_path, load_config, save_alias
from loc_service import LocReport, build_report, combine_reports, day_window

from _version import __version__

ANSI_GRAY = "\033[38;5;245m"
ANSI_RESET = "\033[0m"
INSTALL_SCRIPT = Path(__file__).resolve().with_name("install.sh")
HELP_TEXT = """loc
count lines pushed to GitHub today

flags:
  loc -h
    show this help
  loc -v
    print the installed version
  loc -u
    upgrade to the latest release

features:
  count today's pushed lines across every configured alias
  # loc count all
  loc count all

  count today's pushed lines for one configured alias
  # loc count <alias>
  loc count personal
  loc count wiom

  save or replace a GitHub token alias
  # loc token add <alias> [<token>]
  loc token add wiom ghp_example
  loc token add personal

  open the user config
  # loc config
  loc config
"""


class UsageError(ValueError):
    """Raised for invalid CLI usage."""


def muted(text: str) -> str:
    if not sys.stdout.isatty() or "NO_COLOR" in os.environ:
        return text
    return f"{ANSI_GRAY}{text}{ANSI_RESET}"


def print_help() -> None:
    print(muted(HELP_TEXT.rstrip()))


def open_path_in_editor(path: Path) -> int:
    editor = (os.environ.get("VISUAL") or os.environ.get("EDITOR") or "vim").strip()
    command = shlex.split(editor) if editor else ["vim"]
    path.parent.mkdir(parents=True, exist_ok=True)
    return subprocess.run([*(command or ["vim"]), str(path)], check=False).returncode


def open_config() -> int:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(CONFIG_BOOTSTRAP_TEXT, encoding="utf-8")
        path.chmod(0o600)
    return open_path_in_editor(path)


def upgrade_app() -> int:
    if not INSTALL_SCRIPT.exists():
        print(f"install.sh is missing: {INSTALL_SCRIPT}", file=sys.stderr)
        return 1
    return subprocess.run(["bash", str(INSTALL_SCRIPT), "-u"], check=False).returncode


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
                print(f"\r{frame}", end="", flush=True)
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


def _print_text(
    report: LocReport,
    *,
    scope: str,
    alias_count: int | None = None,
    show_login: bool = False,
) -> None:
    print(f"scope      : {scope}")
    if alias_count is not None:
        print(f"aliases    : {alias_count}")
    elif show_login:
        print(f"login      : {report.login}")
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


def _configured_aliases(config: LocConfig) -> dict[str, str]:
    return {name: alias.token for name, alias in sorted(config.aliases.items())}


def _current_day_window() -> tuple[datetime, datetime, datetime]:
    now = datetime.now().astimezone()
    start, end = day_window(now.date(), now.tzinfo)
    return now, start, end


def _build_alias_report(
    alias: str,
    token: str,
    *,
    label: str,
    window_start: datetime,
    window_end: datetime,
    now: datetime,
) -> LocReport:
    try:
        return build_report(
            GitHubClient(token=token),
            label=label,
            window_start=window_start,
            window_end=window_end,
            now=now,
        )
    except GitHubCLIError as exc:
        raise GitHubCLIError(f"{alias}: {exc}") from exc


def _run_all_aliases(alias_tokens: dict[str, str]) -> int:
    now, start, end = _current_day_window()
    loader = Loader()
    reports: dict[str, LocReport] = {}
    alias_errors: list[str] = []

    try:
        loader.start()
        for alias, token in alias_tokens.items():
            try:
                reports[alias] = _build_alias_report(
                    alias,
                    token,
                    label=now.date().isoformat(),
                    window_start=start,
                    window_end=end,
                    now=now,
                )
            except GitHubCLIError as exc:
                alias_errors.append(str(exc))
    except Exception as exc:
        loader.stop()
        print(f"loc failed: {exc}", file=sys.stderr)
        return 1
    loader.stop()

    if not reports:
        details = "; ".join(alias_errors) if alias_errors else "no configured aliases succeeded"
        print(f"loc failed: {details}", file=sys.stderr)
        return 1

    report = combine_reports(
        reports,
        label=now.date().isoformat(),
        window_start=start,
        window_end=end,
        now=now,
        extra_warnings=alias_errors,
    )
    _print_text(report, scope="all aliases", alias_count=len(alias_tokens))
    return 0


def _run_single_alias(alias: str, token: str) -> int:
    now, start, end = _current_day_window()
    loader = Loader()

    try:
        loader.start()
        report = _build_alias_report(
            alias,
            token,
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
    _print_text(report, scope=alias, show_login=True)
    return 0


def _add_alias(args: list[str]) -> int:
    if len(args) not in (1, 2):
        raise UsageError("usage: loc token add <alias> [<token>]")

    alias = args[0]
    token = args[1] if len(args) == 2 else getpass("GitHub PAT: ")
    path = save_alias(alias, token)
    print(f"Saved alias '{alias}' to {path}")
    return 0


def _dispatch(argv: list[str]) -> int:
    if argv[:2] == ["token", "add"]:
        return _add_alias(argv[2:])
    if argv and argv[0].startswith("-"):
        raise UsageError(f"unknown flag: {argv[0]}")
    if not argv:
        print_help()
        return 0
    if argv[0] != "count":
        raise UsageError("usage: loc count all | loc count <alias> | loc token add <alias> [<token>] | loc config")
    if len(argv) != 2:
        raise UsageError("usage: loc count all | loc count <alias>")

    alias_tokens = _configured_aliases(load_config())
    if not alias_tokens:
        raise UsageError("No GitHub aliases configured. Add one with: loc token add <alias> <token>")

    alias = argv[1]
    if alias == "all":
        return _run_all_aliases(alias_tokens)
    if alias not in alias_tokens:
        known = ", ".join(alias_tokens)
        raise UsageError(f"Unknown alias '{alias}'. Known aliases: {known}")
    return _run_single_alias(alias, alias_tokens[alias])

    raise UsageError(f"Unknown command '{' '.join(argv)}'")


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args == ["-h"]:
        print_help()
        return 0
    if args == ["-v"]:
        print(__version__)
        return 0
    if args == ["-u"]:
        return upgrade_app()
    if args == ["config"]:
        return open_config()
    if args and args[0] in {"-h", "-v", "-u"}:
        print(f"usage: loc {args[0]}", file=sys.stderr)
        return 1

    try:
        return _dispatch(args)
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except UsageError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
