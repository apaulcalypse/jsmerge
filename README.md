# jsmerge

Sort Juniper Junos configurations into canonical `show configuration` order for meaningful diffs and automation pipelines.

```bash
pip install -e ".[dev]"
jsmerge sort input.conf -o sorted.conf --schema auto
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for design details.

## Phase 1 (current)

- Curly-brace parse and render with comment preservation
- Schema-driven sort for `interfaces`, `policy-options`, and `firewall`
- Interface name comparator (`ge-0/0/0`, `xe-1/2/3`, …)
- `--schema auto` resolves from `version` statement or latest EVO bundle

## Development

```bash
pip install -e ".[dev]"
pytest

# Regenerate schema from Juniper YANG on GitHub (cached under ~/.cache/jsmerge/yang/)
jsmerge schema build --version 25.4R1-EVO -o schemas/25.4R1-EVO.json

# Or from a local YANG checkout
jsmerge schema build /path/to/yang/models --version 25.4R1-EVO -o schemas/25.4R1-EVO.json
```
