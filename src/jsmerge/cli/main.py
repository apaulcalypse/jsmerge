"""jsmerge command-line interface."""

from __future__ import annotations

import logging
from enum import Enum
from pathlib import Path
from typing import Optional

import typer

from jsmerge.normalize import denormalize_tree, normalize_tree
from jsmerge.parser import parse_config
from jsmerge.render import render_config
from jsmerge.progress import NullProgress, TerminalProgress
from jsmerge.schema.build import build_schema_from_release
from jsmerge.schema.loader import load_schema_index, release_schema_memory_cache, resolve_schema_path
from jsmerge.sort import SortEngine
from jsmerge.sort.ordering import apply_top_level_order, CLI_TOP_LEVEL_ORDER
from jsmerge.merge import MergeEngine, reverse_merge
from jsmerge.normalize import denormalize_tree, normalize_tree
from jsmerge.filter import filter_config, strip_comments as do_strip_comments, strip_replace as do_strip_replace

app = typer.Typer(
    name="jsmerge",
    help="Sort and merge Juniper Junos configurations.",
    no_args_is_help=True,
)
schema_app = typer.Typer(help="Schema index commands.")
app.add_typer(schema_app, name="schema")


class Platform(str, Enum):
    evo = "evo"
    classic = "classic"


def _read_input(path: Path | None) -> str:
    if path is None or str(path) == "-":
        import sys

        return sys.stdin.read()
    return path.read_text(encoding="utf-8")


def _config_version(root) -> str | None:
    for child in root.children:
        if child.name == "version" and child.raw_tail:
            return child.raw_tail[0]
    return None


@app.command("sort")
def sort_command(
    input: Path = typer.Argument(..., help="Input config file, or - for stdin."),
    output: Optional[Path] = typer.Option(None, "-o", "--output", help="Output file (default: stdout)."),
    schema: str = typer.Option("auto", "--schema", help="Schema bundle name/path, or 'auto'."),
    order: str = typer.Option("cli", "--order", help="Top-level ordering strategy: cli (recommended), yang, or source."),
    strict: bool = typer.Option(False, "--strict", help="Error on unknown schema paths."),
    filter: list[str] = typer.Option(None, "--filter", help="Extract only the first matching subtree (repeatable, e.g. --filter groups --filter 'protocols bgp')."),
    strip_comments: bool = typer.Option(False, "--strip-comments", help="Remove all comments from the output."),
    strip_replace: bool = typer.Option(False, "--strip-replace", help="Remove 'replace:' tags from the output."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose logging."),
) -> None:
    """Sort a Junos configuration into canonical order."""
    logging.basicConfig(level=logging.DEBUG if verbose else logging.WARNING)

    text = _read_input(input)
    root = normalize_tree(parse_config(text))
    config_version = _config_version(root)
    schema_path = resolve_schema_path(schema, config_version=config_version)
    if verbose:
        typer.echo(f"Using schema: {schema_path}", err=True)
        if config_version:
            typer.echo(f"Config version: {config_version}", err=True)

    # Apply filter(s) first if provided (produces a configuration root with selected subtrees)
    if filter:
        root = filter_config(root, filter)

    if strip_comments:
        root = do_strip_comments(root)
    if strip_replace:
        root = do_strip_replace(root)

    index = load_schema_index(schema_path)
    engine = SortEngine(index, strict=strict)
    sorted_root = denormalize_tree(engine.sort(root))

    apply_top_level_order(sorted_root, order)

    rendered = render_config(sorted_root)

    if output:
        output.write_text(rendered, encoding="utf-8")
    else:
        typer.echo(rendered, nl=False)

    release_schema_memory_cache()


@schema_app.command("build")
def schema_build_command(
    yang_dir: Optional[Path] = typer.Argument(
        None,
        help="Local YANG directory (optional; default: fetch from Juniper/yang on GitHub).",
    ),
    output: Path = typer.Option(..., "-o", "--output", help="Output schema JSON path."),
    version: str = typer.Option(..., "--version", help="Junos release, e.g. 25.4R1-EVO or 25.4R1."),
    platform: Optional[Platform] = typer.Option(
        None,
        "--platform",
        help="Override platform tag in bundle (default: inferred from -EVO suffix).",
    ),
    github_ref: str = typer.Option("master", "--github-ref", help="Git branch/tag in Juniper/yang."),
    refresh: bool = typer.Option(False, "--refresh", help="Re-download YANG even if cached."),
    all_modules: bool = typer.Option(False, "--all-modules", help="Include all modules, not only Phase 1 stanzas."),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress progress output."),
) -> None:
    """Compile YANG modules into a schema ordering index."""
    progress = NullProgress() if quiet else TerminalProgress()
    modules_dir = build_schema_from_release(
        output,
        version=version,
        yang_dir=yang_dir,
        platform=platform.value if platform else None,
        github_ref=github_ref,
        force_fetch=refresh,
        focus_only=not all_modules,
        progress=progress,
    )
    if quiet:
        typer.echo(f"Wrote schema bundle to {output}")
        cache = output.with_name(output.name + ".cache")
        if cache.is_file():
            typer.echo(f"Wrote schema cache to {cache}")
        if yang_dir is None:
            typer.echo(f"YANG modules from GitHub cached at {modules_dir}")


@app.command("merge")
def merge_command(
    inputs: list[Path] = typer.Argument(..., help="Input config files to merge (overlay order: later wins)."),
    output: Optional[Path] = typer.Option(None, "-o", "--output", help="Output file (default: stdout)."),
    schema: str = typer.Option("auto", "--schema", help="Schema bundle name/path, or 'auto'."),
    strict: bool = typer.Option(False, "--strict", help="Error on unknown schema paths."),
    include_comments: bool = typer.Option(True, "--include-comments/--no-include-comments", help="Preserve comments from sources."),
    filter: list[str] = typer.Option(None, "--filter", help="Extract only the first matching subtree from each input."),
    strip_comments: bool = typer.Option(False, "--strip-comments", help="Remove all comments from the inputs."),
    strip_replace: bool = typer.Option(False, "--strip-replace", help="Remove 'replace:' tags from the inputs."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose logging."),
) -> None:
    """Merge multiple configs using overlay strategy."""
    logging.basicConfig(level=logging.DEBUG if verbose else logging.WARNING)

    trees = []
    config_version = None
    for inp in inputs:
        text = _read_input(inp)
        root = normalize_tree(parse_config(text))
        if filter:
            root = filter_config(root, filter)
        if strip_comments:
            root = do_strip_comments(root)
        if strip_replace:
            root = do_strip_replace(root)
        if config_version is None:
            config_version = _config_version(root)
        trees.append(root)

    schema_path = resolve_schema_path(schema, config_version=config_version)
    if verbose:
        typer.echo(f"Using schema: {schema_path}", err=True)

    # For Phase 2 we sort after merge (simple); later use schema for strategies
    engine = MergeEngine(strict=strict)
    merged = engine.merge(trees)
    # sort the result
    index = load_schema_index(schema_path)
    sorted_root = denormalize_tree(SortEngine(index, strict=strict).sort(merged))
    apply_top_level_order(sorted_root, "cli")

    rendered = render_config(sorted_root)
    if output:
        output.write_text(rendered, encoding="utf-8")
    else:
        typer.echo(rendered, nl=False)

    release_schema_memory_cache()


@app.command("reverse-merge")
def reverse_merge_command(
    base: Path = typer.Option(..., "--base", help="Clean generated baseline config."),
    live: Path = typer.Option(..., "--live", help="Live router config (with drift)."),
    output: Optional[Path] = typer.Option(None, "-o", "--output", help="Output delta/overrides file (default: stdout)."),
    schema: str = typer.Option("auto", "--schema", help="Schema bundle name/path, or 'auto'."),
    include_comments: bool = typer.Option(True, "--include-comments/--no-include-comments", help="Include comments from live config."),
    strict: bool = typer.Option(False, "--strict", help="Error on unknown schema paths."),
    filter: list[str] = typer.Option(None, "--filter", help="Extract only the first matching subtree from base and live."),
    strip_comments: bool = typer.Option(False, "--strip-comments", help="Remove all comments from the result."),
    strip_replace: bool = typer.Option(False, "--strip-replace", help="Remove 'replace:' tags from the result."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose logging."),
) -> None:
    """Extract minimal overrides from live router config vs generated base (reverse merge / drift extraction)."""
    logging.basicConfig(level=logging.DEBUG if verbose else logging.WARNING)

    base_text = _read_input(base)
    live_text = _read_input(live)

    base_root = normalize_tree(parse_config(base_text))
    live_root = normalize_tree(parse_config(live_text))

    if filter:
        base_root = filter_config(base_root, filter)
        live_root = filter_config(live_root, filter)
    if strip_comments:
        base_root = do_strip_comments(base_root)
        live_root = do_strip_comments(live_root)
    if strip_replace:
        base_root = do_strip_replace(base_root)
        live_root = do_strip_replace(live_root)

    config_version = _config_version(base_root) or _config_version(live_root)
    schema_path = resolve_schema_path(schema, config_version=config_version)
    if verbose:
        typer.echo(f"Using schema: {schema_path}", err=True)

    index = load_schema_index(schema_path)
    sort_engine = SortEngine(index, strict=strict)

    base_sorted = sort_engine.sort(base_root.clone() if hasattr(base_root, 'clone') else normalize_tree(parse_config(base_text)))
    live_sorted = sort_engine.sort(live_root.clone() if hasattr(live_root, 'clone') else normalize_tree(parse_config(live_text)))

    # ensure denormalized form not required for diff
    delta = reverse_merge(base_sorted, live_sorted, include_comments=include_comments)

    # sort the delta for canonical output (schema order)
    if delta and (delta.children or delta.raw_tail):
        delta = sort_engine.sort(delta)
        apply_top_level_order(delta, "cli")  # match real `show configuration` top-level order

    rendered = render_config(delta)
    if output:
        output.write_text(rendered, encoding="utf-8")
    else:
        typer.echo(rendered, nl=False)

    release_schema_memory_cache()


if __name__ == "__main__":
    app()
