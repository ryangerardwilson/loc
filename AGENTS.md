# Repository Guidelines

## Product Boundary
- `loc` is a terminal-native GitHub activity counter.
- Its scope is narrow: count the lines you pushed to GitHub for a chosen day and show cumulative totals only.
- Keep the happy path fast, but stay compliant with the global CLI rule that `loc` with no args prints help.
- Prefer plain-text output that is dense, stable, and script-friendly.

## Architecture
- Keep the project flat and stdlib-only.
- `main.py` owns CLI parsing, output, version, and upgrade flow.
- `github_client.py` should be the only module that shells out to `gh`.
- `loc_service.py` should own aggregation logic and date-window handling.
- Avoid hidden state, caches, or background services.

## Interface Rules
- Support `-h`, `-v`, `-u`, and `-j`.
- Accept compact date selectors:
  - `YYYY-MM-DD`
  - `tm <n>` for today minus `n` days
  - `wm <n>` for week minus `n` calendar weeks
  - `mm <n>` for month minus `n` calendar months
  - `jan` ... `dec` with optional year
- Errors must be terse and shape-specific.
- `loc` with no args must print the same help as `loc -h`.
- Output should show cumulative totals only.

## Implementation Guardrails
- Use the authenticated `gh` CLI account instead of asking for tokens directly.
- Count pushed commits from GitHub push events, then fetch commit stats for those SHAs.
- De-duplicate commits per repo so repeated pushes of the same SHA do not inflate totals.
- If GitHub API limits or event truncation weaken accuracy, surface that explicitly in output instead of guessing silently.
