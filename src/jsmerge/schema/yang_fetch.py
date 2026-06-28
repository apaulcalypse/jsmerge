"""Fetch Juniper YANG models from the public GitHub repository."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

JUNIPER_YANG_REPO = "Juniper/yang"
DEFAULT_GITHUB_REF = "master"

# Directories under .../native/conf-and-rpcs/ that contain modules pyang needs.
YANG_SOURCE_DIRS = (
    "conf/models",
    "common/models",
)

_VERSION_RE = re.compile(r"^(?P<major_minor>\d+\.\d+)(?P<rest>R.+)$", re.IGNORECASE)


@dataclass(frozen=True)
class JunosRelease:
    """Parsed Junos release identifier."""

    version: str
    major_minor: str
    platform: Literal["evo", "classic"]
    github_conf_root: str

    @property
    def cache_key(self) -> str:
        return self.version


def parse_junos_version(version: str) -> JunosRelease:
    """
    Parse a Junos release string into GitHub path components.

    Examples:
        25.4R1-EVO  -> 25.4/25.4R1-EVO/native/conf-and-rpcs
        25.4R1      -> 25.4/25.4R1/native/conf-and-rpcs
        24.4R2-EVO  -> 24.4/24.4R2-EVO/native/conf-and-rpcs
    """
    version = version.strip()
    platform: Literal["evo", "classic"] = "evo" if version.upper().endswith("-EVO") else "classic"
    match = _VERSION_RE.match(version)
    if not match:
        raise ValueError(
            f"Cannot parse Junos version {version!r}; expected format like 25.4R1 or 25.4R1-EVO"
        )
    major_minor = match.group("major_minor")
    github_conf_root = f"{major_minor}/{version}/native/conf-and-rpcs"
    return JunosRelease(
        version=version,
        major_minor=major_minor,
        platform=platform,
        github_conf_root=github_conf_root,
    )


def default_cache_dir() -> Path:
    return Path.home() / ".cache" / "jsmerge" / "yang"


def yang_cache_dir(version: str, *, cache_root: Path | None = None) -> Path:
    release = parse_junos_version(version)
    return (cache_root or default_cache_dir()) / release.cache_key


def _api_contents_url(repo_path: str, ref: str) -> str:
    return f"https://api.github.com/repos/{JUNIPER_YANG_REPO}/contents/{repo_path}?ref={ref}"


def _raw_url(repo_path: str, ref: str) -> str:
    return f"https://raw.githubusercontent.com/{JUNIPER_YANG_REPO}/{ref}/{repo_path}"


def _github_get_json(url: str) -> list | dict:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "jsmerge-schema-builder",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def _download_file(repo_path: str, dest: Path, ref: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(
        _raw_url(repo_path, ref),
        headers={"User-Agent": "jsmerge-schema-builder"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        dest.write_bytes(response.read())


def _fetch_directory(
    repo_path: str,
    dest_dir: Path,
    ref: str,
    *,
    on_file=None,
) -> int:
    """Recursively download .yang files; return count downloaded."""
    try:
        entries = _github_get_json(_api_contents_url(repo_path, ref))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return 0
        raise RuntimeError(f"GitHub API error fetching {repo_path}: HTTP {exc.code}") from exc

    if not isinstance(entries, list):
        raise RuntimeError(f"Unexpected GitHub API response for {repo_path}")

    count = 0
    for entry in entries:
        name = entry["name"]
        entry_path = entry["path"]
        if entry["type"] == "file" and name.endswith(".yang"):
            _download_file(entry_path, dest_dir / name, ref)
            count += 1
            if on_file is not None:
                on_file(name, count)
        elif entry["type"] == "dir":
            count += _fetch_directory(entry_path, dest_dir / name, ref, on_file=on_file)
    return count


def fetch_yang_models(
    version: str,
    *,
    dest_dir: Path | None = None,
    ref: str = DEFAULT_GITHUB_REF,
    force: bool = False,
    progress=None,
) -> Path:
    """
    Download YANG modules for a Junos release into a local directory.

    Returns the directory containing all downloaded ``.yang`` files (flat layout).
    """
    release = parse_junos_version(version)
    cache_dir = dest_dir or yang_cache_dir(version)
    yang_dir = cache_dir / "modules"

    if not force and any(yang_dir.glob("*.yang")):
        cached_count = sum(1 for _ in yang_dir.glob("*.yang"))
        if progress is not None:
            progress.finish(f"Using cached YANG modules ({cached_count} files)")
        return yang_dir

    if progress is not None:
        progress.step(f"Downloading YANG models for {version} from GitHub")

    yang_dir.mkdir(parents=True, exist_ok=True)
    for stale in yang_dir.glob("*.yang"):
        stale.unlink()

    def on_file(name: str, count: int) -> None:
        if progress is not None:
            progress.update(f"Downloading YANG models for {version} ({count} files, latest: {name})")

    total = 0
    for subdir in YANG_SOURCE_DIRS:
        repo_path = f"{release.github_conf_root}/{subdir}"
        target = yang_dir
        total += _fetch_directory(repo_path, target, ref, on_file=on_file)

    if total == 0:
        raise RuntimeError(
            f"No YANG modules found at {release.github_conf_root} in {JUNIPER_YANG_REPO} (ref={ref}). "
            "Check the version string matches the GitHub directory layout."
        )

    if progress is not None:
        progress.finish(f"Downloaded {total} YANG modules")

    return yang_dir


def github_url_for_version(version: str, ref: str = DEFAULT_GITHUB_REF) -> str:
    release = parse_junos_version(version)
    return f"https://github.com/{JUNIPER_YANG_REPO}/tree/{ref}/{release.major_minor}"
