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

### Build a schema

Sort and merge need a versioned schema index. Ship one with the package, or build the full index for your Junos release from Juniper's public YANG repo (cached under `~/.cache/jsmerge/yang/`):

```bash
jsmerge schema build --version 25.4R1-EVO -o schemas/25.4R1-EVO.json
```

Use a classic release string (e.g. `25.4R1`) for non-EVO. Pass a local YANG directory as the first argument if you already have the models.

### Sort a configuration

```bash
jsmerge sort router.conf -o sorted.conf --schema auto
```

- `--schema auto` auto-detects the Junos version from the `version` statement (or falls back to the latest bundled EVO schema).
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

### Sort

```python
from pathlib import Path
from jsmerge.api import sort_config

sorted_text = sort_config(
    Path("router.conf").read_text(),
    schema="auto",
    filters=["interfaces", "policy-options"],
    strip_comments=True,
)
```

`schema="auto"` picks a bundle from the config's `version` statement (or the latest bundled EVO schema). Pass a path or bundle name (e.g. `"25.4R1-EVO"`) to pin one.

### Overlay merge

```python
from pathlib import Path
from jsmerge.merge import MergeEngine
from jsmerge.normalize import denormalize_tree, normalize_tree
from jsmerge.parser import parse_config
from jsmerge.render import render_config
from jsmerge.schema.loader import load_schema_index, resolve_schema_path
from jsmerge.sort import SortEngine
from jsmerge.sort.ordering import apply_top_level_order

trees = [
    normalize_tree(parse_config(Path(p).read_text()))
    for p in ("base.conf", "services.conf", "interfaces.conf")
]
schema = load_schema_index(resolve_schema_path("auto"))
merged = MergeEngine(schema_index=schema).merge(trees)
sorted_root = denormalize_tree(SortEngine(schema).sort(merged))
apply_top_level_order(sorted_root, "cli")
print(render_config(sorted_root), end="")
```

Later trees win on conflicts. Pass `report_conflicts=True` to `MergeEngine` if you want override diagnostics.

### Reverse merge (drift)

```python
from pathlib import Path
from jsmerge.merge import reverse_merge
from jsmerge.normalize import normalize_tree
from jsmerge.parser import parse_config
from jsmerge.render import render_config
from jsmerge.schema.loader import load_schema_index, resolve_schema_path
from jsmerge.sort import SortEngine
from jsmerge.sort.ordering import apply_top_level_order

base = normalize_tree(parse_config(Path("generated.conf").read_text()))
live = normalize_tree(parse_config(Path("live.conf").read_text()))
schema = load_schema_index(resolve_schema_path("auto"))
engine = SortEngine(schema)

delta = reverse_merge(engine.sort(base), engine.sort(live))
delta = engine.sort(delta)
apply_top_level_order(delta, "cli")
print(render_config(delta), end="")
```

For set-format input/output, use `parse_set_config` / `render_set` instead of the curly-brace helpers.

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