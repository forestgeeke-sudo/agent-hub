"""Approved-folder allowlist and path safety checks."""

from __future__ import annotations

from pathlib import Path

from orchestrator.io.state_files import SafetyRulesFile, WriteGuardError, hub_root


def folder_is_approved(target_folder: str, approved_folders: list[str]) -> bool:
    """Check whether *target_folder* sits under an approved top-level folder."""
    normalized = target_folder.replace("\\", "/").strip("/")
    for folder in approved_folders:
        f = folder.strip("/")
        if normalized == f or normalized.startswith(f + "/"):
            return True
    return False


def path_has_forbidden_substring(
    path: str, forbidden: list[str]
) -> str | None:
    lowered = path.lower()
    for sub in forbidden:
        if sub.lower() in lowered:
            return sub
    return None


def check_target_folder(
    target_folder: str,
    safety: SafetyRulesFile,
) -> tuple[bool, str | None]:
    if not folder_is_approved(target_folder, safety.approved_folders):
        return False, f"target_folder '{target_folder}' not in approved folders"
    hit = path_has_forbidden_substring(
        target_folder, safety.tier2_preconditions.forbid_path_substrings
    )
    if hit:
        return False, f"target_folder contains forbidden substring '{hit}'"
    return True, None


def assert_path_writable(
    path: Path,
    approved_folders: list[str],
    root: Path | None = None,
) -> None:
    from orchestrator.io.state_files import assert_write_allowed

    root = hub_root(root)
    assert_write_allowed(path, approved_folders, root)


def check_stop(root: Path | None = None) -> bool:
    from orchestrator.io.state_files import stop_requested

    return stop_requested(root)
