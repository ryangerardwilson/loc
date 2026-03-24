# Repository Guidelines

## Workspace Defaults
- Follow `/home/ryan/Documents/agent_context/CLI_TUI_STYLE_GUIDE.md` for CLI/TUI taste and help shape.
- Follow `/home/ryan/Documents/agent_context/CANONICAL_REFERENCE_IMPLEMENTATION_FOR_CLI_AND_TUI_APPS.md` for executable contract details such as `-h`, `-v`, `-u`, installer behavior, release workflow expectations, and regression expectations.
- This file only records `loc`-specific constraints or durable deviations.

## Product Boundary
- `loc` is a terminal-native GitHub activity counter.
- Its scope is narrow: count the lines you pushed to GitHub today and show cumulative totals only.
- Keep the default path fast: `loc` with no args should print today's totals across every configured alias.
- Prefer plain-text output that is dense, stable, and script-friendly.

## Architecture
- Keep the project flat and stdlib-only.
- `main.py` owns CLI parsing, output, version, and upgrade flow.
- `loc_config.py` owns the XDG config at `~/.config/loc/config.json`.
- `github_client.py` should be the only module that shells out to `gh`.
- `loc_service.py` should own aggregation logic and date-window handling.
- Avoid hidden state, caches, or background services.

## Interface Rules
- Support `-h`, `-v`, and `-u`.
- Errors must be terse and shape-specific.
- Output should show cumulative totals only.

## Implementation Guardrails
- Keep GitHub PAT aliases inside `~/.config/loc/config.json`; do not depend on Bash wrappers for `loc` account selection.
- `loc add <alias> [<token>]` is the canonical setup path for saving or replacing aliases.
- Count pushed commits from GitHub push events for the current local date, then fetch commit stats for those SHAs.
- De-duplicate commits per repo so repeated pushes of the same SHA do not inflate totals.
- If GitHub API limits or event truncation weaken accuracy, surface that explicitly in output instead of guessing silently.
