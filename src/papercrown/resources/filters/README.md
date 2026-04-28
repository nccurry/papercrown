# Paper Crown Lua Filters

This directory contains the Pandoc Lua filters that normalize Markdown into
Paper Crown's rendered HTML contract. These filters are package resources, so
they must remain dependency-free and loadable from an installed wheel.

## Shared Library

Filters share helpers from `lib/papercrown.lua`. Load the helper from a filter
with the current `PANDOC_SCRIPT_FILE` and `dofile`:

```lua
local script_path = PANDOC_SCRIPT_FILE or debug.getinfo(1, "S").source:sub(2)
local filter_dir = script_path:match("^(.*)[/\\][^/\\]+$") or "."
local pc = dofile(filter_dir .. "/lib/papercrown.lua")
```

Use this pattern rather than a relative `require`; it works for source checkouts,
installed wheels, and Windows paths.

The library is intentionally small:

- `pc.text` handles Pandoc text extraction and inline text construction.
- `pc.class` handles class lookup, insertion, de-duplication, and filtering.
- `pc.block` builds attributes and divs around Pandoc block lists.
- `pc.link` owns shared link slug/path helpers and internal-ref marking.
- `pc.section` wraps heading-led sections.
- `pc.component` builds the common component wrapper and named parts.

Keep behavior-specific logic in the owning filter. Move code into
`lib/papercrown.lua` only when two or more filters need the same Pandoc plumbing
or generated-contract helper.

## Filter Order

The active filter order is declared in `src/papercrown/resources.py`:

1. `internal-links.lua`
2. `strip-links.lua`
3. `callouts.lua`
4. `rules-widgets.lua`
5. `stat-blocks.lua`
6. `highlight-level-headings.lua`
7. `minor-sections.lua`

Order matters:

- `internal-links.lua` runs before `strip-links.lua` so resolvable Markdown and
  wikilinks become local anchors before unresolved note links are flattened.
- `rules-widgets.lua` runs before `stat-blocks.lua`, allowing widget bodies to
  keep normal Markdown behavior inside their component body.
- `highlight-level-headings.lua` runs before `minor-sections.lua` so wrapped
  minor sections inherit level-heading classes on their heading blocks.

When adding a filter, update `resources.LUA_FILTERS` and add a focused test for
the ordering assumption.

## Rendered Contract

Generated HTML should use the Paper Crown component contract:

- Internal refs: `pc-ref pc-ref-internal`
- Callouts: `pc-callout`, `pc-callout-title`, `pc-callout-body`,
  `pc-callout-{kind}`
- Stat blocks: `pc-stat-block`, `pc-stat-line`
- Level headings: `pc-level-heading`
- Minor sections: `pc-section pc-section-minor pc-section-level-N`
- Rules widgets: `pc-component pc-feature`, `pc-component pc-ability`, or
  `pc-component pc-procedure`, with `pc-component-header`,
  `pc-component-title`, `pc-component-meta`, and `pc-component-body`

Python-side typed TTRPG blocks remain separate from the Lua filters, but their
rendered links and component-like wrappers participate in the same `pc-*`
styling contract where the surfaces overlap.

Do not add compatibility aliases for old generated classes unless there is a
concrete migration need. Paper Crown is the only consumer of this contract, and
clean generated classes are preferred over preserving old internal names.

## Authoring Surfaces

Most filters preserve existing author Markdown:

- Obsidian callouts remain authored as block quotes such as `[!tip]`.
- Stat lines remain ordinary bold-label paragraphs or lists.
- Markdown links and wikilinks remain ordinary Markdown/Obsidian links.
- Level headings remain normal headings such as `Level 1`.

Rules widgets are the only `pc-*` authoring surface in this directory. They use
Pandoc fenced divs directly:

```markdown
:::: {.pc-feature title="Sneak Attack" level="1" tags="rogue,damage"}
Once per turn, add extra damage.
::::
```

User-facing documentation for these widgets lives in
`docs/vault/Markdown Components.md`.

## Testing

Use focused HTML tests for behavior and snapshots for fixture-level contract
changes:

```sh
uv run pytest tests/html/test_html_snapshots.py::TestLuaFilterRendering
uv run pytest tests/html
uv run pytest tests/unit
```

Resource/package coverage lives in `tests/unit/test_generate.py`; it should
continue to assert that `resources/**/*.lua` packages `filters/lib`.
