# jsmerge

Sort, merge, and diff Juniper JUNOS configurations into canonical `show configuration` order for meaningful diffs and automation pipelines.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for design details.

## Installation

### Easy install

```bash
pipx install -e .
```
After cloning the repo

You should then be able to run `jsmerge` directly from anywhere without remembering to do the virtualenv activation.

### For developers / contributors

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

This gives you the `jsmerge` CLI with the core sort/merge/reverse-merge commands.

## Quick Start

```bash
jsmerge --help
```

### Sort a configuration

```bash
jsmerge sort router.conf -o sorted.conf --schema auto
```

- `--schema auto` auto-detects the Junos version from the `version` statement (or falls back to latest cached EVO bundle).
- Use `--filter 'protocols bgp'` to extract only matching subtrees.
- `--strip-comments` / `--strip-replace` clean the output.

### Merge multiple fragments

```bash
jsmerge merge base.conf services.conf interfaces.conf -o merged.conf
```

Later files win on conflicts (overlay semantics). The result is automatically sorted.

### Extract drift (reverse merge)

```bash
jsmerge reverse-merge --base generated.conf --live live.conf -o delta.conf
```

Produces the minimal overrides present on the live router that differ from the generated baseline. Perfect for detecting configuration drift.

## Available Commands

### `jsmerge sort`

Sort a single config into canonical order.

Supports `--format set|curly` output, `--strict` schema validation, auto-detection of set vs. curly input, and all filter/strip options.

### `jsmerge merge`

Overlay-merge multiple configs (later wins), then sort.

Supports `--report-conflicts` (opt-in reporting of value overrides), `--format set|curly` (output format), `--strict` schema validation, and auto-detects set-format or curly-brace input.

### `jsmerge reverse-merge`

Extract minimal delta between a generated base and live router config.

### `jsmerge schema build`

Compile Juniper YANG models into a versioned schema index (used by sort/merge).

```bash
jsmerge schema build --version 25.4R1-EVO -o schemas/25.4R1-EVO.json
```

## Python API

```python
from jsmerge.api import sort_config

sorted_text = sort_config(
    open("input.conf").read(),
    schema="auto",
    filters=["interfaces", "policy-options"],
    strip_comments=True,
)
```

## Features

- Curly-brace parse/render with full comment and `replace:` preservation
- Schema-driven sort for `interfaces`, `policy-options`, `firewall`, etc.
- Special interface name comparator (`ge-0/0/0`, `xe-1/2/3`, …)
- `--schema auto` resolves from `version` statement or latest EVO bundle
- Filter, strip-comments, and strip-replace utilities
- Merge engine with overlay semantics + post-merge sort, schema-driven singleton/list detection, optional conflict reporting (`--report-conflicts`)
- Reverse-merge for drift detection
- Set-format (display set) input/output support including `activate`/`deactivate`
- Strict schema validation mode (`--strict`) with user-defined list key handling
- Top-level ordering that matches real `show configuration` output (`--order cli`)

## Development

```bash
pip install -e ".[dev]"
pytest

# Regenerate schema from Juniper YANG on GitHub (cached under ~/.cache/jsmerge/yang/)
jsmerge schema build --version 25.4R1-EVO -o schemas/25.4R1-EVO.json

# Or from a local YANG checkout
jsmerge schema build /path/to/yang/models --version 25.4R1-EVO -o schemas/25.4R1-EVO.json
```

Pre-built schemas live in the `schemas/` directory of the package.