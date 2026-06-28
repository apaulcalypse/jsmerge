"""Schema build orchestration."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from jsmerge.schema.builder import build_schema_index, write_schema_index
from jsmerge.schema.yang_fetch import fetch_yang_models, parse_junos_version


def resolve_yang_dir(
    *,
    version: str,
    yang_dir: Path | None = None,
    github_ref: str = "master",
    force_fetch: bool = False,
    cache_dir: Path | None = None,
) -> Path:
    if yang_dir is not None:
        if not yang_dir.is_dir():
            raise FileNotFoundError(f"YANG directory not found: {yang_dir}")
        return yang_dir
    return fetch_yang_models(
        version,
        ref=github_ref,
        force=force_fetch,
        dest_dir=cache_dir,
    )


def build_schema_from_release(
    output: Path,
    *,
    version: str,
    yang_dir: Path | None = None,
    platform: Literal["evo", "classic"] | None = None,
    github_ref: str = "master",
    force_fetch: bool = False,
    focus_only: bool = True,
    cache_dir: Path | None = None,
) -> Path:
    release = parse_junos_version(version)
    resolved_platform = platform or release.platform
    modules_dir = resolve_yang_dir(
        version=version,
        yang_dir=yang_dir,
        github_ref=github_ref,
        force_fetch=force_fetch,
        cache_dir=cache_dir,
    )
    write_schema_index(
        modules_dir,
        output,
        version=version,
        platform=resolved_platform,
        focus_only=focus_only,
    )
    return modules_dir
