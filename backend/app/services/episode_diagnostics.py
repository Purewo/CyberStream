from __future__ import annotations

from collections import Counter, defaultdict


EPISODE_DIAGNOSTIC_ISSUES = {
    "episode_number_missing": {
        "label": "Episode Number Missing",
        "severity": "medium",
    },
    "duplicate_episode_numbers": {
        "label": "Duplicate Episode Numbers",
        "severity": "medium",
    },
    "missing_episode_numbers": {
        "label": "Missing Episode Numbers",
        "severity": "high",
    },
    "episode_count_mismatch": {
        "label": "Episode Count Mismatch",
        "severity": "medium",
    },
}


def normalize_expected_episode_count(value):
    try:
        expected = int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
    return expected if expected and expected > 0 else None


def build_season_episode_diagnostics(resources, expected_episode_count=None):
    episode_resources = defaultdict(list)
    unnumbered_resource_ids = []

    for resource in resources:
        if getattr(resource, "episode", None) is None:
            unnumbered_resource_ids.append(resource.id)
            continue
        try:
            episode = int(resource.episode)
        except (TypeError, ValueError):
            unnumbered_resource_ids.append(resource.id)
            continue
        if episode <= 0:
            unnumbered_resource_ids.append(resource.id)
            continue
        episode_resources[episode].append(resource.id)

    available_episode_numbers = sorted(episode_resources.keys())
    duplicate_episode_resources = [
        {
            "episode": episode,
            "resource_ids": resource_ids,
        }
        for episode, resource_ids in sorted(episode_resources.items())
        if len(resource_ids) > 1
    ]
    duplicate_episode_numbers = [item["episode"] for item in duplicate_episode_resources]

    expected_episode_count = normalize_expected_episode_count(expected_episode_count)
    first_episode = available_episode_numbers[0] if available_episode_numbers else None
    last_episode = available_episode_numbers[-1] if available_episode_numbers else None
    expected_source = "metadata" if expected_episode_count else None
    if expected_episode_count is None and last_episode is not None:
        expected_episode_count = last_episode
        expected_source = "number_range"

    missing_episode_numbers = []
    if expected_episode_count is not None:
        available_set = set(available_episode_numbers)
        missing_episode_numbers = [
            episode
            for episode in range(1, expected_episode_count + 1)
            if episode not in available_set
        ]

    issue_codes = []
    if unnumbered_resource_ids:
        issue_codes.append("episode_number_missing")
    if duplicate_episode_numbers:
        issue_codes.append("duplicate_episode_numbers")
    if missing_episode_numbers:
        issue_codes.append("missing_episode_numbers")
    if (
        expected_source == "metadata"
        and expected_episode_count is not None
        and len(available_episode_numbers) != expected_episode_count
    ):
        issue_codes.append("episode_count_mismatch")

    if issue_codes:
        status = "needs_attention"
    elif resources:
        status = "ok"
    else:
        status = "unknown"

    if expected_episode_count is None:
        coverage_status = "unknown"
    elif missing_episode_numbers:
        coverage_status = "incomplete"
    else:
        coverage_status = "complete"

    completion_ratio = None
    if expected_episode_count:
        completion_ratio = round(len(available_episode_numbers) / expected_episode_count, 4)

    return {
        "status": status,
        "coverage_status": coverage_status,
        "issue_codes": issue_codes,
        "expected_episode_count": expected_episode_count,
        "expected_source": expected_source,
        "available_episode_count": len(available_episode_numbers),
        "available_episode_numbers": available_episode_numbers,
        "missing_episode_numbers": missing_episode_numbers,
        "duplicate_episode_numbers": duplicate_episode_numbers,
        "duplicate_episode_resources": duplicate_episode_resources,
        "unnumbered_resource_ids": unnumbered_resource_ids,
        "first_episode": first_episode,
        "last_episode": last_episode,
        "completion_ratio": completion_ratio,
    }


def build_episode_diagnostics_summary(season_diagnostics):
    issue_counter = Counter()
    seasons_needing_attention = []
    coverage_statuses = []

    for season, diagnostics in sorted(season_diagnostics.items()):
        diagnostics = diagnostics or {}
        coverage_statuses.append(diagnostics.get("coverage_status") or "unknown")
        issue_codes = diagnostics.get("issue_codes") or []
        if issue_codes:
            seasons_needing_attention.append(season)
        issue_counter.update(issue_codes)

    if not season_diagnostics:
        status = "unknown"
        coverage_status = "unknown"
    elif seasons_needing_attention:
        status = "needs_attention"
        coverage_status = "incomplete" if "incomplete" in coverage_statuses else "unknown"
    else:
        status = "ok"
        coverage_status = "complete" if "complete" in coverage_statuses else "unknown"

    return {
        "status": status,
        "coverage_status": coverage_status,
        "issue_count": sum(issue_counter.values()),
        "issue_code_counts": dict(issue_counter),
        "season_count": len(season_diagnostics),
        "seasons_needing_attention": seasons_needing_attention,
    }


def build_movie_episode_diagnostics(resources, expected_episode_counts=None):
    expected_episode_counts = expected_episode_counts or {}
    season_resources = defaultdict(list)
    for resource in resources:
        season = getattr(resource, "season", None)
        if season is None:
            continue
        season_resources[season].append(resource)

    diagnostics = {}
    for season, items in sorted(season_resources.items()):
        diagnostics[season] = build_season_episode_diagnostics(
            items,
            expected_episode_count=expected_episode_counts.get(season),
        )

    return {
        "seasons": diagnostics,
        "summary": build_episode_diagnostics_summary(diagnostics),
    }
