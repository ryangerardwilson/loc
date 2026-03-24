#!/usr/bin/env python3
from __future__ import annotations

import sys
import threading
import time
from datetime import datetime
from getpass import getpass

from github_client import GitHubCLIError, GitHubClient
from loc_config import CONFIG_BOOTSTRAP_TEXT, ConfigError, LocConfig, config_path, load_config, save_alias
from loc_service import LocReport, build_report, combine_reports, day_window
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
  count today's pushed lines across every configured alias
  # loc
  loc

  count today's pushed lines for one configured alias
  # loc <alias>
  loc personal
  loc wiom

  save or replace a GitHub token alias
  # loc add <alias> [<token>]
  loc add wiom ghp_example
  loc add personal

  open the user config
  # loc conf
  loc conf
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
        raise UsageError("Usage: loc add <alias> [<token>]")

    alias = args[0]
    token = args[1] if len(args) == 2 else getpass("GitHub PAT: ")
    path = save_alias(alias, token)
    print(f"Saved alias '{alias}' to {path}")
    return 0


def _dispatch(argv: list[str]) -> int:
    if argv[:1] == ["add"]:
        return _add_alias(argv[1:])
    if argv and argv[0].startswith("-"):
        raise UsageError(f"Unknown flag '{argv[0]}'")

    alias_tokens = _configured_aliases(load_config())
    if not alias_tokens:
        raise UsageError("No GitHub aliases configured. Add one with: loc add <alias> <token>")

    if not argv:
        return _run_all_aliases(alias_tokens)

    if len(argv) == 1:
        alias = argv[0]
        if alias not in alias_tokens:
            known = ", ".join(alias_tokens)
            raise UsageError(f"Unknown alias '{alias}'. Known aliases: {known}")
        return _run_single_alias(alias, alias_tokens[alias])

    raise UsageError(f"Unknown command '{' '.join(argv)}'")


APP_SPEC = AppSpec(
    app_name="loc",
    version=__version__,
    help_text=HELP_TEXT,
    install_script_path=INSTALL_SCRIPT,
    no_args_mode="dispatch",
    config_path_factory=config_path,
    config_bootstrap_text=CONFIG_BOOTSTRAP_TEXT,
)


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    try:
        return run_app(APP_SPEC, argv, _dispatch)
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except UsageError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
