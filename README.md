# loc

`loc` counts the lines you pushed to GitHub today across your repos.

It reads GitHub push events for the current local date, resolves the pushed
commit SHAs through `gh api`, then sums additions and deletions into one
cumulative total. GitHub account aliases live in an app-owned config file
instead of depending on shell wrappers.

This exists because "how much code did I actually ship today?" should be a one-command answer, not a tab safari.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/ryangerardwilson/loc/main/install.sh | bash
```

The installer keeps app files under `~/.loc/` and publishes the public launcher
at `~/.local/bin/loc`.

If `~/.local/bin` is not already on your `PATH`, add this once:

```bash
export PATH="$HOME/.local/bin:$PATH"
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
loc personal
loc wiom
loc add personal ghp_xxx
loc conf
loc -h
loc -u
loc -v
```

No-arg output is dense and cumulative across every configured alias:

```text
scope      : all aliases
aliases    : 2
date       : 2026-03-09
repos      : 8
pushes     : 3
commits    : 5
added      : 241
deleted    : 62
net        : 179
```

Per-alias output is the same shape, but scoped:

```text
scope      : wiom
login      : ryangerardwilson-wiom
date       : 2026-03-09
repos      : 3
pushes     : 1
commits    : 2
added      : 91
deleted    : 14
net        : 77
```

## Config

`loc` stores GitHub aliases in:

```text
~/.config/loc/config.json
```

Add or replace an alias from the CLI:

```bash
loc add personal ghp_xxx
loc add wiom ghp_xxx
```

If you omit the token, `loc add <alias>` prompts for it.

The config file shape is:

```json
{
  "aliases": {
    "personal": {
      "token": "ghp_xxx"
    },
    "wiom": {
      "token": "ghp_xxx"
    }
  }
}
```

## Notes

- `loc` uses the local machine timezone when deciding what "today" means.
- `loc` with no args prints today's cumulative totals across every configured alias.
- `loc <alias>` prints totals only for that alias.
- `loc` sets `GH_TOKEN` / `GITHUB_TOKEN` per alias when it calls `gh api`.
- It counts pushed commit stats from GitHub, not local unpushed work.
- Re-pushing the same commit SHA in the same repo on the same day is de-duplicated.
- If GitHub event payloads are truncated or an API compare lookup fails, `loc` prints a warning instead of silently inflating the total.
