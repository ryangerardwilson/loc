# loc

`loc` counts the lines you pushed to GitHub for a selected window across your repos.

It uses your authenticated `gh` session, reads your GitHub push events for the requested window, resolves the pushed commit SHAs, then sums commit additions and deletions into one cumulative total.

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
loc -h
loc tm 0
loc 2026-03-09
loc tm 1
loc wm 0
loc mm 2
loc jan
loc jan 2024
loc -j
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
- `loc` with no args prints help, per the shared CLI contract.
- `tm <n>` means today minus `n` days.
- `wm <n>` means the current Monday-start calendar week minus `n` weeks.
- `mm <n>` means the current calendar month minus `n` months.
- `jan` ... `dec` target a named month in the current year, or in the supplied year.
- It counts pushed commit stats from GitHub, not local unpushed work.
- Re-pushing the same commit SHA in the same repo on the same day is de-duplicated.
- If GitHub event payloads are truncated or an API compare lookup fails, `loc` prints a warning instead of silently inflating the total.
- GitHub only exposes recent user push events through this path, so older windows can return zero with a warning even when historical activity existed.
