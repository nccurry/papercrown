# Paper Crown Lua Filters

Filters share helpers from `lib/papercrown.lua`. Load the helper from a filter
with the current `PANDOC_SCRIPT_FILE` and `dofile`:

```lua
local script_path = PANDOC_SCRIPT_FILE or debug.getinfo(1, "S").source:sub(2)
local filter_dir = script_path:match("^(.*)[/\\][^/\\]+$") or "."
local pc = dofile(filter_dir .. "/lib/papercrown.lua")
```

The library is intentionally small and dependency-free:

- `pc.text` handles Pandoc text extraction and inline text construction.
- `pc.class` handles class lookup, insertion, de-duplication, and filtering.
- `pc.block` builds attributes and divs around Pandoc block lists.
- `pc.link` owns shared link slug/path helpers and internal-ref marking.
- `pc.section` wraps heading-led sections.
- `pc.component` builds the common component wrapper and named parts.

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
