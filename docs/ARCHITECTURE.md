# jsmerge — Architecture & Design

Juniper (Junos) configuration **sort** and **merge** tooling. The goal is to normalize curly-brace configs so they match the order produced by `show configuration` on the router, enabling meaningful diffs and clean combination of config fragments produced by different automation pipelines.

**Language:** Python 3.11+ (consistent with existing config automation tooling).

---

## Problem Statement

Junos configs arrive from many sources — automation templates, hand edits, one-off hacks — and statement order is often arbitrary at input time. For most of the hierarchy, Junos reorders statements into a fixed display order when you run `show configuration`. For a smaller set of constructs (policy terms, firewall filter terms, route-filter entries, etc.), order is **semantically significant** and must be preserved exactly.

Without normalization:

- `diff` reports massive false positives (reordering only)
- Merging fragments from different tools produces unpredictable output
- Reviewing automation output against a router baseline is painful

jsmerge solves this with two operations built on a shared core:

| Tool | Purpose |
|------|---------|
| **sort** | Reorder a single config to canonical `show configuration` order |
| **merge** | Combine multiple config fragments into one tree, then sort |

Both depend on the same parsed config tree and the same schema-derived ordering rules.

---

## Ordering Semantics (What We're Matching)

Junos configuration display order comes from three regimes. [Juniper's published YANG models](https://github.com/Juniper/yang) (e.g. `24.4/24.4R2-EVO/native/conf-and-rpcs/conf/models`) are the authoritative source for which regime applies where.

| Regime | YANG signal | Sort behavior | Examples |
|--------|-------------|---------------|----------|
| **Schema-fixed** | Container child statement order | Children appear in YANG definition order | `policy-options` children: `prefix-list`, then `policy-statement`, … |
| **System-ordered lists** | `list` with `key`, no `ordered-by user` | Sorted by key (with type-specific comparators) | `policy-statement` names, `prefix-list` names |
| **User-ordered lists** | `ordered-by user` | Preserve insertion order — reordering changes behavior | `policy-statement <name> term <name>`, firewall `term`, route-filter entries |

**Special case — interfaces:** Documented Junos behavior sorts interfaces by type (e.g. `et`, `ge`, `xe`), then numerically by FPC slot, PIC, and port. This is not plain lexicographic string sort and requires a dedicated comparator even though some interface lists are marked `ordered-by user` in YANG.

**What we do not reorder:** Any list marked `ordered-by user`. Sorting these alphabetically would change device behavior and would not match the router.

**Top-level ordering (`--order`):**  
Real `show configuration` output does not follow the strict YANG `child_order` at the root. Therefore jsmerge defaults to `--order cli`, which uses a stable, observed order that closely matches what routers actually emit (`version → groups → apply-groups → system → chassis → services → security → interfaces → …`).  
`--order yang` restores the old strict YANG behavior.  
`--order source` preserves the input order for top-level statements (useful when the input is already in the desired sequence).

---

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Inputs                                   │
│   curly-brace config(s)  ·  optional set-format  ·  manifest    │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  Parser                                                          │
│  text → ConfigNode tree (faithful to input; no reordering)      │
└────────────────────────────┬────────────────────────────────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
┌──────────────────┐ ┌──────────────┐ ┌──────────────────┐
│  MergeEngine     │ │  SortEngine  │ │  (future: diff)  │
│  (merge only)    │ │              │ │                  │
└────────┬─────────┘ └──────┬───────┘ └──────────────────┘
         │                  │
         └────────┬─────────┘
                  ▼
┌─────────────────────────────────────────────────────────────────┐
│  Renderer                                                        │
│  ConfigNode tree → canonical curly-brace text                   │
└─────────────────────────────────────────────────────────────────┘

         SchemaIndex (pre-compiled from YANG, loaded at runtime)
              ▲
              │
┌─────────────────────────────────────────────────────────────────┐
│  Schema Builder (offline / CLI subcommand)                       │
│  Junos YANG modules → versioned JSON ordering index             │
└─────────────────────────────────────────────────────────────────┘
```

### Shared artifacts

All components share three core types:

1. **ConfigNode** — parsed config as a typed tree (not lines of text)
2. **SchemaIndex** — pre-compiled ordering rules for a specific Junos version
3. **SortEngine** — recursive ordering using SchemaIndex + special comparators

---

## Core Data Model

### ConfigNode

Parsed representation of one node in the config hierarchy.

```python
@dataclass
class ConfigNode:
    name: str
    raw_tail: list[str] | None = None   # raw tokens after the statement name (primary representation)
    props: dict[str, str] = field(default_factory=dict)
    flags: set[str] = field(default_factory=set)
    children: list[ConfigNode] = field(default_factory=list)
    source_index: int = 0
    comments: list[str] = field(default_factory=list)

    @property
    def value(self) -> str | None:
        """Legacy view: first element of raw_tail when it has exactly one item."""
        if self.raw_tail and len(self.raw_tail) == 1:
            return self.raw_tail[0]
        return None
```

**Design note on values:**
Instead of storing a single `value` string (and guessing when to add/remove quotes), nodes store `raw_tail: list[str]`. Multi-part statements (e.g. `as-path NAME "regex"`, `route-filter X/Y/Z upto /24`) keep their tokens exactly as parsed. The renderer simply emits `" ".join(raw_tail)`. This eliminates an entire class of quoting/escaping bugs and makes round-tripping of real `show configuration` output reliable.

**Parser responsibilities:**

- Braced hierarchies and trailing semicolons
- `inactive:` prefix (stored in `flags`)
- `apply-groups` / `apply-groups-except` (preserved as nodes; not expanded)
- `replace:` and similar annotations (preserved for faithful round-trip)
- Block comments (`/* … */`) — **preserved** and attached to the nearest following statement node
- Set-format lines (`set …`, `delete …`) — parsed into the same tree (see [Set/Delete Format](#setdelete-format))

**Parser non-goals (initially):**

- Expanding `apply-groups` inheritance (committed config ≠ post-inheritance view)
- Validating values against YANG types

### SchemaPath

Tuple of node names from `/configuration` downward:

```python
SchemaPath = tuple[str, ...]
# e.g. ("policy-options", "policy-statement", "term")
```

### SchemaIndex

Pre-compiled ordering rules, loaded from JSON at runtime.

```python
@dataclass
class ListRule:
    ordered_by: Literal["user", "system"]
    keys: list[str]                    # ["name"] or compound keys
    comparator: str = "default"        # "default" | "interface" | "prefix" | "numeric"

@dataclass
class NodeRule:
    child_order: list[str]             # ordered child names at this path
    lists: dict[str, ListRule]         # child name → list metadata

@dataclass
class SchemaIndex:
    version: str                       # e.g. "24.4R2-EVO"
    platform: Literal["evo", "classic"]
    nodes: dict[SchemaPath, NodeRule]
```

### Schema sources

- **Primary:** [Juniper/yang](https://github.com/Juniper/yang) GitHub repo, versioned per release
- **Exact match:** `show system schema format yang module all-conf output-directory <dir>` from a target device
- **Shipped bundles:** one JSON file per release **and platform**, e.g. `schemas/24.4R2-EVO.json` and `schemas/24.4R2.json`, committed or distributed with the package

### EVO vs classic Junos

Junos OS Evolved and classic Junos can diverge in YANG schema (different modules, child order, or feature sets) even at the same release number. We ship **separate schema bundles** for each platform when Juniper publishes distinct YANG trees.

| Platform | YANG path pattern (Juniper GitHub) | Bundle naming |
|----------|----------------------------------|---------------|
| EVO | `…/24.4R2-EVO/native/…` | `24.4R2-EVO.json` |
| Classic | `…/24.4R2/native/…` | `24.4R2.json` |

The schema builder compares outputs across platforms and only publishes both bundles when they differ; if identical for a given release, a single bundle may be shared with both platform tags (implementation detail — prefer explicit separate files when in doubt).

### Schema resolution (`--schema`)

| `--schema` value | Resolution |
|------------------|------------|
| Explicit version, e.g. `24.4R2-EVO` | Load that bundle directly |
| `auto` + `version` statement in config | Match `version` to nearest schema bundle (prefer platform suffix if present in version string) |
| `auto` + no `version` statement | Use the **most recent shipped schema**, defaulting to the **latest EVO** release |

When auto-resolution picks a schema newer than the config's actual Junos version, unknown-node warnings are expected and acceptable. Users targeting classic-only devices should pass an explicit `--schema` or include a `version` statement in the config.

---

## Component Design

### 1. Parser (`jsmerge.parser`)

**Input formats:**

| Format | Priority | Notes |
|--------|----------|-------|
| Curly-brace (hierarchical) | Phase 1 | Primary format; matches `show configuration` |
| Set/delete format (`display set`) | Phase 2 | Small snippets; `set` and `delete` lines → same tree |

**Design notes:**

- Use a lexer + recursive descent parser (not regex-based — configs nest deeply and carry edge cases)
- Preserve `source_index` on every child for stable user-ordered list handling
- Attach block comments to the statement node they precede; carry through sort/merge/render
- Emit parse errors with line/column for actionable messages
- Do **not** sort during parse

#### Set/delete format

Many operators write tactical changes as `set` or `delete` one-liners. These parse into the same `ConfigNode` tree as curly-brace input:

```
set interfaces ge-0/0/0 unit 0 family inet address 10.0.0.1/24
delete policy-options policy-statement OLD-POLICY
```

- `set` lines build or merge nodes along the path
- `delete` lines mark nodes (or subtrees) for removal during merge; a standalone `delete` input can express intent without a full hierarchical config
- Renderer can emit either curly-brace (default) or set format (`--output-format set`)
- Inline `/* … */` comments on set lines are preserved on the leaf node they annotate

### Schema Builder (`jsmerge.schema.builder`)

Offline tool that compiles YANG → `SchemaIndex` JSON.

**YANG sources (in priority order):**

1. **GitHub (default)** — [Juniper/yang](https://github.com/Juniper/yang) via `--version 25.4R1-EVO`
2. **Local directory** — optional positional `yang_dir` argument
3. **Device export** — `show system schema format yang module all-conf output-directory <dir>`

```bash
# Fetch 25.4R1-EVO models from GitHub, cache, and build
jsmerge schema build --version 25.4R1-EVO -o schemas/25.4R1-EVO.json

# Classic Junos (no -EVO suffix)
jsmerge schema build --version 25.4R1 -o schemas/25.4R1.json

# Force re-download
jsmerge schema build --version 25.4R1-EVO -o schemas/25.4R1-EVO.json --refresh
```

Version strings map to GitHub paths using Juniper's stable layout:

| `--version` | GitHub path | Platform (inferred) |
|-------------|-------------|---------------------|
| `25.4R1-EVO` | `25.4/25.4R1-EVO/native/conf-and-rpcs/` | `evo` |
| `25.4R1` | `25.4/25.4R1/native/conf-and-rpcs/` | `classic` |

The `-EVO` suffix selects the EVO directory and sets the bundle's `platform` metadata. `--platform` is only needed to override that tag (rare).

YANG files are cached under `~/.cache/jsmerge/yang/<version>/modules/`.

**Pipeline:**

```
junos-conf-*.yang  (+ imports, augments)
    → resolve with pyang or libyang
    → walk resolved schema tree
    → emit schemas/<version>[-EVO].json   # platform tag in filename
```

CLI: `jsmerge schema build --version 25.4R1-EVO -o schemas/25.4R1-EVO.json`

**What to extract at each schema path:**

1. **Child order** — YANG statement order after resolving `uses`, `grouping`, and `augment`
2. **List metadata** — `key` fields, `ordered-by user` vs default (`system`)
3. **Choices** — inline `choice`/`case` children at the choice's position in the parent (not merged early). This is what places `accept`/`reject` after `metric` in policy `then` blocks, and similarly across the tree wherever YANG uses choices.

**The sort engine should not hard-code per-path ordering rules.** Child order comes from the schema bundle; the engine only applies a small set of **comparator** overrides where YANG keys do not match Junos display semantics (see below).

**Example** (from `junos-conf-policy-options`):

| Path | Rule |
|------|------|
| `("policy-options",)` | Children in YANG order: `satellite-policies`, `prefix-list`, `mac-list`, `policy-statement`, … |
| `("policy-options", "policy-statement")` | System-ordered list; key = `name` |
| `("policy-options", "policy-statement", "term")` | User-ordered list; key = `name` |

**Why pre-compile instead of runtime YANG parsing:**

- YANG import/augment resolution is slow and complex
- Ordering rules change only with Junos version, not per invocation
- CI can validate schema bundles independently
- Runtime stays fast and dependency-light (JSON load only)

**Python libraries:**

- **pyang** — mature, pure Python; good for extraction scripts
- **libyang** (optional) — faster, stricter; useful for validation later

### 3. Sort Engine (`jsmerge.sort`)

Recursive tree walk applying `SchemaIndex` rules.

```
sort(node, schema_path):
    1. Look up NodeRule for schema_path (or fallback rule)
    2. Classify children by name
    3. For each child group:
         - list instances → apply ListRule
         - containers     → recurse
    4. Emit children in child_order
    5. Within each list, apply ordering rule
```

#### System-ordered lists

Sort instances by composite key using the appropriate comparator:

```python
def compare_keys(a: ConfigNode, b: ConfigNode, rule: ListRule) -> int:
    match rule.comparator:
        case "interface":
            return compare_interface(a.value, b.value)
        case "ip_prefix":
            return compare_ip_prefix(a.value, b.value)
        case _:
            return compare_lexicographic(extract_keys(a, rule.keys))
```

#### User-ordered lists

Stable sort by `source_index`. Never reorder alphabetically.

#### Comments

Comments do not participate in ordering. When sorting moves a node, its attached `comments` travel with it. When merging duplicate paths, comments from all sources are concatenated (deduplicated, source order preserved) so JIRA tickets, bug IDs, and tactical-change notes survive the merge.

#### Within a list entry

Recurse into children and sort their children normally. A `term` block keeps its term order, but `from` / `then` children inside it follow schema order.

#### Special comparators

| Comparator | Why needed |
|------------|------------|
| `interface` | `ge-0/0/10` sorts after `ge-0/0/2`; type ordering (`et` < `ge` < `xe`) |
| `ip_prefix` | Prefix-length-aware ordering for route filters |
| `unit` | Logical unit numbering within an interface |
| `default` | Lexicographic on composite string keys |

Build incrementally; `interface` + `default` cover the majority of real-world diff pain.

#### Engine rules vs schema rules

| Concern | Source | Notes |
|---------|--------|-------|
| Container child order | YANG `i_children` order → schema `child_order` | Includes inlined `choice` cases |
| List sort order | YANG `ordered-by` + `key` → schema `lists` | `user` preserves `source_index`; `system` sorts by key |
| Interface names | `interface` comparator | YANG does not encode slot/PIC/port sort |
| Bare `ge-0/0/0` under `interfaces` | `normalize.py` | CLI shorthand, not schema |
| Unknown schema paths | Alphabetical fallback | Warn in normal mode; error with `--strict` |

Rebuild the schema bundle after YANG builder fixes — do not add sort-engine exceptions for individual statement names.

#### Unknown / unschema'd nodes

When config contains nodes absent from the schema (new feature, version mismatch):

- **Default:** alphabetical by node name; treat lists as system-ordered by identifier
- **`--strict`:** error on unknown paths
- **Log warnings** in normal mode so gaps are visible

### 4. Merge Engine (`jsmerge.merge`)

Tree union with path-aware conflict rules, followed by `sort()`.

#### Merge modes

**Partition merge** (recommended for automation pipelines)

Each input owns disjoint path prefixes. No conflicts by construction.

```yaml
# merge-manifest.yaml
sources:
  - file: base.conf
    paths:
      - system
      - snmp
  - file: interfaces.conf
    paths:
      - interfaces
  - file: routing.conf
    paths:
      - policy-options
      - routing-options
```

**Overlay merge** (base + patch)

```
result = merge(base, overlay, strategy="overlay")
```

| Node type | Rule |
|-----------|------|
| Scalar leaf | Overlay wins |
| System-ordered list | Union by key; overlay entry replaces base entry with same key |
| User-ordered list | Strategy-dependent (see below) |
| Container | Recurse |

**User-ordered list strategies** (overlay / n-way):

| Strategy | Behavior |
|----------|----------|
| `preserve_base` | Keep base order; append new entries from overlay |
| `preserve_overlay` | Overlay order wins entirely |
| `insert_by_name` | Merge by name; new names appended at end |
| `fail_on_overlap` | Duplicate entry names → conflict error |

**N-way union**

Union all input trees; detect conflicts where the same path + key has different scalar values.

#### Conflict reporting

```json
{
  "path": "policy-options/policy-statement/EXPORT-DEFAULT/term/local-pref",
  "sources": {
    "base.conf": "then { local-pref 100; }",
    "routing.conf": "then { local-pref 200; }"
  }
}
```

#### Merge algorithm (sketch)

```
merge(trees: list[ConfigNode]) -> ConfigNode:
    result = empty root
    for tree in trees:
        deep_merge(result, tree)
    return sort(result)
```

At each path:

| Node type | Merge rule |
|-----------|------------|
| Leaf / scalar | Equal → keep; different → conflict (or overlay wins) |
| Container | Recurse merge all children |
| System-ordered list | Index by key; merge matching entries recursively; add new keys |
| User-ordered list | Apply selected strategy |

### 4.5 Reverse Merge / Drift Extraction (first-class feature)

**Purpose:** Given a clean generated baseline and a live router config (with drift, cruft, and tactical overrides), emit a minimal, mergeable Junos config fragment containing *only* the differences. This fragment can be stored alongside the generated config and merged at render time, giving a clear, auditable view of all non-standard configuration.

**Default behavior:** `--include-comments` (comments from the live side are preserved on differing nodes so the "why" travels with the override).

**Typical usage:**

```bash
jsmerge reverse-merge \
  --base generated.conf \
  --live $(ssh router 'show configuration') \
  -o overrides.conf
```

The resulting `overrides.conf` is then part of the normal merge pipeline:

```bash
jsmerge merge --manifest merge.yaml -o final.conf   # merge.yaml includes overrides.conf
```

**Algorithm sketch (reuses MergeEngine + new diff primitives):**

```
reverse_merge(base, live) -> delta:
    base_tree = sort(parse(base))
    live_tree = sort(parse(live))
    delta = diff_trees(base_tree, live_tree)   # returns ConfigNode subtree of changes only
    # For each differing path:
    #   - scalar leaf differs → emit the live value (with comment if present)
    #   - container differs → emit only the changed subtree
    #   - system list: emit only added/changed/deleted keyed entries
    #   - user-ordered list: emit whole differing block (order is semantic)
    #   - presence-only nodes (e.g. "inactive: foo;") → emit with flag
    return render(delta, include_comments=True)
```

**Key behaviors & edge cases:**

- Comments from live are attached to the delta nodes by default.
- Deletions on-box (statements present in base but absent in live) are expressed either as `delete` statements or as absence in the overlay (depending on strategy flag).
- User-ordered lists (terms, route-filters) are emitted in full when they differ — partial term diffs are not attempted.
- Unknown schema paths fall back to alphabetical; warnings emitted unless `--strict`.
- The delta is always rendered through the normal SortEngine so it is in canonical order and ready to merge.
- Reverse-merge output is a valid input to the normal `merge` command (overlay strategy).

This makes reverse-merge the "generate the tactical layer" companion to the normal merge flow.

### 5. Renderer (`jsmerge.render`)

Walk sorted `ConfigNode` tree → emit curly-brace text.

**Formatting rules (match Junos conventions):**

- 4-space indent per level
- Trailing semicolons on leaf statements
- `inactive:` prefix on flagged nodes
- One statement per line
- Block comments rendered immediately before the node they are attached to (`/* … */` on its own line, same indent as the statement)
- Optional blank line between major top-level stanzas

**Output formats:**

| Format | Flag | Use case |
|--------|------|----------|
| Curly-brace (default) | `--output-format hierarchical` | Match `show configuration` |
| Set | `--output-format set` | Automation-friendly `set` lines |

Formatting normalization alone improves diff readability even before semantic sorting is complete.

---

## CLI Design

Using **Typer** (or Click) for the CLI interface.

```bash
# Sort a single config to canonical order
jsmerge sort input.conf -o sorted.conf --schema 24.4R2-EVO

# Auto-detect schema: use 'version' statement if present, else latest EVO
jsmerge sort input.conf -o sorted.conf --schema auto

# Sort a set-format snippet and emit set-format output
jsmerge sort patch.conf -o patch-sorted.conf --output-format set

# Merge with partition manifest
jsmerge merge --manifest merge.yaml -o merged.conf --schema 24.4R2-EVO

# Overlay merge
jsmerge merge base.conf overlay.conf -o merged.conf --strategy overlay

# Build schema index from a YANG models directory
jsmerge schema build /path/to/yang/models -o schemas/24.4R2-EVO.json

# Validate round-trip against router output
jsmerge sort candidate.conf | diff - router-show.conf
```

**Global flags:**

| Flag | Purpose |
|------|---------|
| `--schema <version\|auto>` | Select schema bundle; `auto` reads `version` from config or falls back to latest EVO |
| `--output-format <hierarchical\|set>` | Render as curly-brace or `set` lines |
| `--strict` | Error on unknown schema paths |
|| `--order cli|yang|source` | Top-level ordering strategy (`cli` is default) |
| `--verbose` | Log comparator fallbacks, schema misses, and auto-resolution choice |

---

## Project Layout

```
jsmerge/
├── pyproject.toml
├── README.md
├── docs/
│   └── ARCHITECTURE.md          # this document
├── src/
│   └── jsmerge/
│       ├── __init__.py
│       ├── parser/              # curly-brace (and later set) → ConfigNode
│       │   ├── lexer.py
│       │   └── parser.py
│       ├── schema/              # SchemaIndex types + loader
│       │   ├── models.py
│       │   ├── loader.py
│       │   └── builder.py       # YANG → JSON (offline)
│       ├── sort/                # SortEngine + comparators
│       │   ├── engine.py
│       │   └── comparators.py
│       ├── merge/               # MergeEngine + strategies
│       │   ├── engine.py
│       │   └── strategies.py
│       ├── render/              # ConfigNode → text
│       │   └── renderer.py
│       └── cli/                 # Typer entry points
│           └── main.py
├── schemas/                     # pre-built JSON per release + platform
│   ├── 24.4R2-EVO.json
│   └── 24.4R2.json
└── tests/
    ├── golden/                  # router-captured show configuration fixtures
    ├── permuted/                # shuffled-order variants of golden configs
    ├── test_sort.py
    ├── test_merge.py
    └── test_parser.py
```

---

## Dependencies

| Package | Role |
|---------|------|
| **typer** | CLI |
| **pyang** | YANG schema compilation (build-time / `schema build` subcommand) |
| **libyang** | Optional; stricter validation in later phases |
| **pytest** | Test runner |
| **pyyaml** | Merge manifest parsing |

Runtime dependencies stay minimal — the sort/merge path only needs the JSON schema bundle and the standard library plus Typer.

**Python:** 3.11+ required (`list[str]`, `str | None`, `match` statements, modern stdlib).

---

## Testing Strategy

Correctness is proven by matching real router output, not by internal consistency alone.

### Golden tests

Capture fixtures from production or lab routers:

```bash
show configuration | no-more > tests/golden/router-policy-heavy.conf
```

Assert: `sort(parse(golden)) == golden` (after normalizing whitespace if needed).

### Permutation tests

Take a golden config, programmatically shuffle child order at every node, then:

```python
assert sort(shuffle(golden)) == golden
```

This is the most important test — it proves sort matches Junos, not just that we're self-consistent.

### Merge tests

1. Decompose a golden config into fragments (by top-level stanza or manifest paths)
2. `merge(fragments) → sort`
3. Assert output equals golden

### Cross-version tests

Same config sorted against two schema versions; document and test expected differences for version-skew scenarios.

### CI

- Schema builder runs on pinned YANG release tags
- Golden + permutation tests run on every PR
- Optional: `--strict` mode test suite to catch schema coverage gaps

---

## Implementation Phases

### Phase 1 — MVP (sort, high-value stanzas)

- [x] `ConfigNode` datamodel (including `comments`)
- [x] Curly-brace parser + renderer with comment preservation
- [x] Schema builder for `interfaces`, `policy-options`, `firewall` (EVO + classic)
- [x] SortEngine with `default` + `interface` comparators
- [x] Schema auto-resolution (`version` statement → bundle; fallback → latest EVO)
- [x] `jsmerge sort` CLI
- [x] Golden + permutation tests for Phase 1 stanzas

**Exit criteria:** `sort(shuffle(router_dump)) == router_dump` for at least one real device capture covering interfaces, policies, and filters.

### Phase 2 — Merge + set/delete format + Reverse Merge

- [ ] Overlay merge with conflict reporting
- [ ] User-ordered list merge strategies
- [ ] Set/delete format parser and renderer
- [ ] Comment preservation through merge (default: `--include-comments`)
- [ ] `jsmerge merge` CLI
- [ ] `jsmerge reverse-merge` (first-class): generated + live → minimal overrides config
- [ ] Tree-diff primitives usable by both merge and reverse-merge flows

### Phase 3 — Full schema coverage + Partition merge

- [ ] Partition merge (YAML manifest)
- [ ] Schema builder for all `junos-conf-*.yang` modules (EVO and classic bundles)
- [ ] `logical-systems`, `routing-instances`, `groups`
- [ ] `inactive:` / `apply-groups` / `replace:` full fidelity

### Phase 4 — Diff integration

- [ ] `jsmerge diff` operating on sorted trees (traditional structural/line diff)
- [ ] Order-sensitive section handling (policy/firewall terms)
- [ ] Optional integration with external tools (e.g. diffnc-style output)
- [ ] Reverse-merge output usable as the "actionable patch" form of a diff

---

## Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Language | **Python 3.11+** | Matches existing config automation; pyang ecosystem; modern typing |
| Runtime YANG parsing | **No** — pre-compile to JSON | Fast, simple runtime; versioned bundles |
| User-ordered list handling | **Preserve source order** | Matches router; reordering changes behavior |
| Comments | **Preserve** through parse, sort, merge, render | Tactical changes often annotated with JIRA/bug IDs |
| EVO vs classic schema | **Separate bundles** when YANG differs | Platforms diverge even at the same release number |
| `--schema auto` fallback | **Latest shipped EVO** when no `version` statement | Sensible default for greenfield configs and snippets |
| Set/delete format | **Supported** (Phase 2) | Common format for small snippets and tactical patches |
| `apply-groups` expansion | **No** (default) | `show configuration` shows committed config |
| Schema version selection | CLI flag + auto-detect from `version` statement | Explicit control with sensible default |
| Unknown nodes | Warn + alphabetical fallback; `--strict` to error | Robust across version skew |

---

## Known Hard Problems

Plan for these explicitly; don't discover them during golden test failures.

1. **YANG `uses` / `augment` resolution** — hardest part of the schema builder; the sort engine itself is straightforward tree walking once the index exists
2. **Interface naming** — dedicated parser for `ge-0/0/0`, `ae0`, `lo0`, `irb.100`, channelized interfaces, etc.
3. **Multi-key lists** — e.g. `route-filter-list` / `rf_list` keyed by `address choice-ident choice-value`
4. **Version drift** — new YANG features on older configs; graceful fallback required
5. **`groups` block** — `groups { … }` is user-ordered at the top level; members inside follow normal rules
6. **Logical-systems / routing-instances** — nested configuration trees that repeat the same schema under different roots

---

## Related Work

- **[diffnc](https://pypi.org/project/diffnc/)** — network config diff tool with Junos order-sensitive path awareness; useful reference for diff phase and for understanding which paths treat order as semantic
- **[Juniper/yang](https://github.com/Juniper/yang)** — official YANG models per Junos release
- **NSO Juniper NED** — documents Juniper-specific ordered-by-user edit behavior and `diff-dependencies` annotations for device bugs

---

## Resolved Design Questions

| Question | Decision |
|----------|----------|
| Strip or preserve comments? | **Preserve.** Comments attach to nodes, travel through sort/merge, and render before their statement. |
| EVO vs classic schema bundles? | **Both.** Separate JSON bundles per platform when YANG trees differ. |
| `--schema auto` without `version` statement? | Use the **most recent shipped schema**, defaulting to **latest EVO**. |
| Support `set` / `delete` format? | **Yes** — Phase 2. Parse into the same tree; render back to set format when requested. |
| Minimum Python version? | **3.11+** |
