# loc

`loc` counts the lines you pushed to GitHub today across your repos.

It uses your authenticated `gh` session, reads your GitHub push events for the current local date, resolves the pushed commit SHAs, then sums commit additions and deletions into one cumulative total.

This exists because "how much code did I actually ship today?" should be a one-command answer, not a tab safari.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/ryangerardwilson/loc/main/install.sh | bash
```

## Source Run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

## Usage

```bash
loc
loc -h
```

Text output is dense and cumulative:

```text
date       : 2026-03-09
repos      : 8
pushes     : 3
commits    : 5
added      : 241
deleted    : 62
net        : 179
```

## Notes

- `loc` uses the local machine timezone when deciding what "today" means.
- `loc` with no args prints today's cumulative totals.
- It counts pushed commit stats from GitHub, not local unpushed work.
- Re-pushing the same commit SHA in the same repo on the same day is de-duplicated.
- If GitHub event payloads are truncated or an API compare lookup fails, `loc` prints a warning instead of silently inflating the total.
