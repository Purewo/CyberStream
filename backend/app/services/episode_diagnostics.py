from __future__ import annotations

from collections import Counter, defaultdict
import re


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


_MULTI_EPISODE_PATTERN = re.compile(
    r'(?i)(?<![A-Z0-9])S(?P<season>\d{1,2})[\s._-]*E(?P<first>\d{1,3})'
    r'(?P<tail>(?:(?:[\s._-]*E|[\s._-]*-[\s._-]*E?)\d{1,3})+)'
)


def normalize_expected_episode_count(value):
    try:
        expected = int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
    return expected if expected and expected > 0 else None


def _normalize_episode_number(value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if 1 <= number <= 200 else None


def _dedupe_episode_numbers(values):
    numbers = []
    seen = set()
    for value in values:
        number = _normalize_episode_number(value)
        if number is None or number in seen:
            continue
        seen.add(number)
        numbers.append(number)
    return sorted(numbers)


def _declared_episode_numbers_from_specs(specs):
    if not isinstance(specs, dict):
        return []

    candidates = []
    for key in ("episode_numbers", "episodes"):
        raw_value = specs.get(key)
        if isinstance(raw_value, (list, tuple, set)):
            candidates.extend(raw_value)

    analysis = specs.get("analysis") if isinstance(specs.get("analysis"), dict) else {}
    path_cleaning = analysis.get("path_cleaning") if isinstance(analysis.get("path_cleaning"), dict) else {}
    raw_value = path_cleaning.get("episode_numbers")
    if isinstance(raw_value, (list, tuple, set)):
        candidates.extend(raw_value)

    return _dedupe_episode_numbers(candidates)


def extract_multi_episode_numbers(text, season=None):
    match = _MULTI_EPISODE_PATTERN.search(str(text or ""))
    if not match:
        return []

    matched_season = _normalize_episode_number(match.group("season"))
    expected_season = _normalize_episode_number(season)
    if expected_season is not None and matched_season != expected_season:
        return []

    numbers = [_normalize_episode_number(match.group("first"))]
    tail = match.group("tail") or ""
    numbers.extend(
        _normalize_episode_number(item.group("episode"))
        for item in re.finditer(
            r'(?i)(?:[\s._-]*E|[\s._-]*-[\s._-]*E?)(?P<episode>\d{1,3})',
            tail,
        )
    )
    numbers = _dedupe_episode_numbers(numbers)
    if len(numbers) == 2 and "-" in tail and numbers[0] < numbers[1]:
        return list(range(numbers[0], numbers[1] + 1))
    return numbers


def episode_numbers_for_resource(resource):
    declared_numbers = _declared_episode_numbers_from_specs(getattr(resource, "tech_specs", None))
    if declared_numbers:
        return declared_numbers

    season = getattr(resource, "season", None)
    filename_numbers = []
    for text in (getattr(resource, "filename", None), getattr(resource, "path", None)):
        filename_numbers = extract_multi_episode_numbers(text, season=season)
        if filename_numbers:
            break
    if filename_numbers:
        return filename_numbers

    episode = _normalize_episode_number(getattr(resource, "episode", None))
    return [episode] if episode is not None else []


def format_episode_label(season, episode_numbers=None, episode=None):
    numbers = _dedupe_episode_numbers(episode_numbers or [])
    if not numbers and episode is not None:
        number = _normalize_episode_number(episode)
        if number is not None:
            numbers = [number]

    if season is not None and numbers:
        season_number = int(season)
        if len(numbers) == 1:
            return f"S{season_number:02d}E{numbers[0]:02d}"
        if numbers == list(range(numbers[0], numbers[-1] + 1)):
            return f"S{season_number:02d}E{numbers[0]:02d}-E{numbers[-1]:02d}"
        suffix = "+".join(f"E{number:02d}" for number in numbers)
        return f"S{season_number:02d}{suffix}"
    if numbers:
        if len(numbers) == 1:
            return f"EP{numbers[0]:02d}"
        if numbers == list(range(numbers[0], numbers[-1] + 1)):
            return f"EP{numbers[0]:02d}-EP{numbers[-1]:02d}"
        return "+".join(f"EP{number:02d}" for number in numbers)
    if season is not None:
        return f"S{int(season):02d}"
    return None


def build_season_episode_diagnostics(resources, expected_episode_count=None):
    episode_resources = defaultdict(list)
    unnumbered_resource_ids = []

    for resource in resources:
        episode_numbers = episode_numbers_for_resource(resource)
        if not episode_numbers:
            unnumbered_resource_ids.append(resource.id)
            continue
        for episode in episode_numbers:
            episode_resources[episode].append(resource.id)

    available_episode_numbers = sorted(episode_resources.keys())
    duplicate_episode_candidates = [
        {
            "episode": episode,
            "resource_ids": resource_ids,
        }
        for episode, resource_ids in sorted(episode_resources.items())
        if len(resource_ids) > 1
    ]

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

    duplicate_episode_resources = []
    alternate_episode_resources = []
    if duplicate_episode_candidates:
        duplicates_need_review = bool(unnumbered_resource_ids or missing_episode_numbers)
        if (
            not duplicates_need_review
            and expected_source == "metadata"
            and expected_episode_count is not None
            and len(available_episode_numbers) != expected_episode_count
        ):
            duplicates_need_review = True
        if duplicates_need_review:
            duplicate_episode_resources = duplicate_episode_candidates
        else:
            alternate_episode_resources = duplicate_episode_candidates

    duplicate_episode_numbers = [item["episode"] for item in duplicate_episode_resources]
    alternate_episode_numbers = [item["episode"] for item in alternate_episode_resources]

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
        "alternate_episode_numbers": alternate_episode_numbers,
        "alternate_episode_resources": alternate_episode_resources,
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
