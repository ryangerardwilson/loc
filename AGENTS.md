# Repository Guidelines

## Product Boundary
- `loc` is a terminal-native GitHub activity counter.
- Its scope is narrow: count the lines you pushed to GitHub for a chosen day and show a compact repo-by-repo breakdown.
- Keep the default path fast: `loc` with no args should count today.
- Prefer plain-text output that is dense, stable, and script-friendly.

## Architecture
- Keep the project flat and stdlib-only.
- `main.py` owns CLI parsing, output, version, and upgrade flow.
- `github_client.py` should be the only module that shells out to `gh`.
- `loc_service.py` should own aggregation logic and date-window handling.
- Avoid hidden state, caches, or background services.

## Interface Rules
- Support `-h`, `-v`, `-u`, and `-j`.
- Accept an optional single date argument in `YYYY-MM-DD`.
- Errors must be terse and shape-specific.
- Output should show overall totals first, then per-repo sections.

## Implementation Guardrails
- Use the authenticated `gh` CLI account instead of asking for tokens directly.
- Count pushed commits from GitHub push events, then fetch commit stats for those SHAs.
- De-duplicate commits per repo so repeated pushes of the same SHA do not inflate totals.
- If GitHub API limits or event truncation weaken accuracy, surface that explicitly in output instead of guessing silently.
