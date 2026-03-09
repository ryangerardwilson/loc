from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any

from github_client import GitHubCLIError, GitHubClient


def _parse_github_timestamp(value: str, tzinfo) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(tzinfo)


def day_window(target_day: date, tzinfo) -> tuple[datetime, datetime]:
    start = datetime.combine(target_day, time.min, tzinfo=tzinfo)
    end = start + timedelta(days=1)
    return start, end


@dataclass
class RepoTotals:
    repo: str
    pushes: int = 0
    commits: int = 0
    additions: int = 0
    deletions: int = 0
    branches: set[str] = field(default_factory=set)

    @property
    def net(self) -> int:
        return self.additions - self.deletions


@dataclass
class LocReport:
    login: str
    label: str
    window_start: datetime
    window_end: datetime
    generated_at: datetime
    repos: dict[str, RepoTotals]
    pushes: int
    commits: int
    additions: int
    deletions: int
    warnings: list[str]

    @property
    def net(self) -> int:
        return self.additions - self.deletions


@dataclass
class PushResolution:
    shas: list[str]
    additions: int | None = None
    deletions: int | None = None
    warning: str | None = None


def _branch_name(ref: str | None) -> str:
    if not ref:
        return "unknown"
    prefix = "refs/heads/"
    return ref[len(prefix) :] if ref.startswith(prefix) else ref


def _extract_commit_shas(
    client: GitHubClient,
    repo: str,
    before: str | None,
    head: str | None,
    payload_commits: list[dict[str, Any]],
    payload_size: int | None,
) -> PushResolution:
    if before and head and before != ("0" * 40):
        try:
            compare = client.api(f"repos/{repo}/compare/{before}...{head}")
            commits = compare.get("commits", [])
            shas = [
                item["sha"]
                for item in commits
                if isinstance(item, dict) and isinstance(item.get("sha"), str)
            ]
            files = compare.get("files", [])
            additions = 0
            deletions = 0
            if isinstance(files, list):
                for item in files:
                    if not isinstance(item, dict):
                        continue
                    file_additions = item.get("additions", 0)
                    file_deletions = item.get("deletions", 0)
                    if isinstance(file_additions, int):
                        additions += file_additions
                    if isinstance(file_deletions, int):
                        deletions += file_deletions
            warning = None
            if isinstance(files, list) and len(files) == 300:
                warning = f"{repo}: compare file list hit 300-file API cap; totals may be low"
            return PushResolution(
                shas=shas,
                additions=additions,
                deletions=deletions,
                warning=warning,
            )
        except Exception as exc:
            return PushResolution(
                shas=[],
                warning=f"{repo}: compare lookup failed ({exc})",
            )

    shas = [
        item["sha"]
        for item in payload_commits
        if isinstance(item, dict) and isinstance(item.get("sha"), str)
    ]
    warning = None
    if not shas and head:
        shas = [head]
    if before == ("0" * 40):
        warning = f"{repo}: branch-creation push fell back to payload commit list"
    elif payload_size is not None and payload_size > len(payload_commits):
        warning = (
            f"{repo}: push payload was truncated; totals may be incomplete for one event"
        )
    elif len(payload_commits) == 0:
        warning = f"{repo}: push event exposed no commit list"
    return PushResolution(shas=shas, warning=warning)


def _commit_totals(client: GitHubClient, repo: str, sha: str) -> tuple[int, int]:
    payload = client.api(f"repos/{repo}/commits/{sha}")
    stats = payload.get("stats")
    if not isinstance(stats, dict):
        return 0, 0
    additions = stats.get("additions", 0)
    deletions = stats.get("deletions", 0)
    if not isinstance(additions, int) or not isinstance(deletions, int):
        return 0, 0
    return additions, deletions


def build_report(
    client: GitHubClient,
    *,
    label: str,
    window_start: datetime,
    window_end: datetime,
    now: datetime,
) -> LocReport:
    login = client.viewer_login()
    tzinfo = now.tzinfo
    if tzinfo is None:
        raise ValueError("now must be timezone-aware")
    repos: dict[str, RepoTotals] = {}
    warnings: list[str] = []
    seen_commits: set[tuple[str, str]] = set()
    pending_commits: list[tuple[str, str]] = []
    push_inputs: list[
        tuple[str, str | None, str | None, list[dict[str, Any]], int | None]
    ] = []
    pushes = 0
    exhausted_recent_event_history = False

    for page in range(1, 4):
        try:
            events = client.api(f"users/{login}/events?per_page=100&page={page}")
        except GitHubCLIError as exc:
            if "HTTP 422" in str(exc):
                break
            raise
        if not isinstance(events, list) or not events:
            break
        if page == 3:
            exhausted_recent_event_history = True

        saw_event_in_window = False
        all_older = True

        for event in events:
            if not isinstance(event, dict):
                continue
            created_at = event.get("created_at")
            if not isinstance(created_at, str):
                continue
            created_dt = _parse_github_timestamp(created_at, tzinfo)
            if created_dt < window_start:
                continue
            all_older = False
            if created_dt >= window_end:
                continue
            saw_event_in_window = True
            if event.get("type") != "PushEvent":
                continue

            repo_info = event.get("repo")
            payload = event.get("payload")
            if not isinstance(repo_info, dict) or not isinstance(payload, dict):
                continue
            repo_name = repo_info.get("name")
            if not isinstance(repo_name, str) or not repo_name:
                continue

            repo_totals = repos.setdefault(repo_name, RepoTotals(repo=repo_name))
            repo_totals.pushes += 1
            repo_totals.branches.add(_branch_name(payload.get("ref")))
            pushes += 1

            push_inputs.append(
                (
                    repo_name,
                    payload.get("before"),
                    payload.get("head"),
                    payload.get("commits", []),
                    payload.get("size"),
                )
            )

        if not saw_event_in_window and all_older:
            break

    with ThreadPoolExecutor(max_workers=8) as executor:
        future_map = {
            executor.submit(
                _extract_commit_shas,
                client,
                repo_name,
                before,
                head,
                payload_commits,
                payload_size,
            ): (repo_name, before, head)
            for repo_name, before, head, payload_commits, payload_size in push_inputs
        }
        for future in as_completed(future_map):
            repo_name, _, _ = future_map[future]
            repo_totals = repos[repo_name]
            try:
                resolution = future.result()
            except Exception as exc:
                warnings.append(f"{repo_name}: push resolution failed ({exc})")
                continue
            if resolution.warning:
                warnings.append(resolution.warning)

            unseen_shas: list[str] = []
            overlap_found = False
            for sha in resolution.shas:
                key = (repo_name, sha)
                if key in seen_commits:
                    overlap_found = True
                    continue
                unseen_shas.append(sha)

            if (
                unseen_shas
                and not overlap_found
                and resolution.additions is not None
                and resolution.deletions is not None
            ):
                repo_totals.commits += len(unseen_shas)
                repo_totals.additions += resolution.additions
                repo_totals.deletions += resolution.deletions
                for sha in unseen_shas:
                    seen_commits.add((repo_name, sha))
                continue

            for sha in unseen_shas:
                key = (repo_name, sha)
                seen_commits.add(key)
                pending_commits.append(key)

    with ThreadPoolExecutor(max_workers=8) as executor:
        future_map = {
            executor.submit(_commit_totals, client, repo_name, sha): (repo_name, sha)
            for repo_name, sha in pending_commits
        }
        for future in as_completed(future_map):
            repo_name, sha = future_map[future]
            repo_totals = repos[repo_name]
            try:
                additions, deletions = future.result()
            except Exception as exc:
                warnings.append(f"{repo_name}: commit stats failed for {sha[:7]} ({exc})")
                continue
            repo_totals.commits += 1
            repo_totals.additions += additions
            repo_totals.deletions += deletions

    total_additions = sum(item.additions for item in repos.values())
    total_deletions = sum(item.deletions for item in repos.values())
    total_commits = sum(item.commits for item in repos.values())
    if exhausted_recent_event_history and pushes == 0:
        warnings.append("GitHub only exposes recent push events here; older windows may be incomplete")

    return LocReport(
        login=login,
        label=label,
        window_start=window_start,
        window_end=window_end,
        generated_at=now,
        repos=dict(sorted(repos.items())),
        pushes=pushes,
        commits=total_commits,
        additions=total_additions,
        deletions=total_deletions,
        warnings=warnings,
    )
