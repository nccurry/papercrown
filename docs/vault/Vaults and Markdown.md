# Vaults and Markdown

:::: {.flourish-note .flourish-folder}
Vaults are named content roots. They let a recipe assemble Markdown from one or
more folders without moving the source into Paper Crown or into the repository.
::::

Markdown stays ordinary first. Paper Crown adds source resolution, Obsidian-style
links, embedded images, and optional TTRPG components when a book needs richer
game objects.

<div class="art-rule art-rule-folder" aria-hidden="true"></div>

## How to Use It

Give each content root an alias in the recipe:

```yaml
vaults:
  rules: ../vault
  setting: ../setting-notes
```

Then refer to files through that alias:

```yaml
chapters:
  - kind: file
    title: Primer
    source: rules:Primer.md
```

Keep source Markdown readable outside Paper Crown. Headings, lists, tables,
code blocks, images, and links should still make sense in your editor.

## How to Adapt It

Use multiple vaults when a book combines reusable rules, campaign-specific
setting material, or local overrides. Use a single vault when the project is a
small book and the extra naming would not buy clarity.

Paper Crown supports ordinary Markdown first. Use optional components when a
rule needs to stand out as a reusable game object rather than a plain
paragraph, list, or table.

## Rules Widgets

Rules widgets use Pandoc fenced divs. They work in the same source Markdown as
the rest of your book and do not require recipe changes.

### Feature

Use `pc-feature` for class features, ancestry features, rule features, or
notable abilities.

```markdown
:::: {.pc-feature title="Sneak Attack" level="1" tags="rogue,damage"}
Once per turn, add extra damage when you have advantage or an ally is adjacent.
::::
```

### Ability

Use `pc-ability` for action, spell, power, move, or technique cards. Optional
metadata can describe cost, trigger, duration, usage, or recharge.

```markdown
:::: {.pc-ability title="Overcharge" cost="1 Charge" duration="Instant"}
Push the engine past its limit, then mark heat.
::::
```

```markdown
:::: {.pc-ability title="Guardian Intercept" trigger="An ally is hit" usage="Reaction"}
Move up to your speed toward the ally and become the target instead.
::::
```

### Procedure

Use `pc-procedure` for ordered rules processes such as combat loops, travel
turns, downtime, clocks, or scene procedures.

```markdown
:::: {.pc-procedure title="Recovery Turn" usage="Downtime"}
1. Clear temporary conditions.
2. Spend resources on repairs, healing, or research.
3. Advance faction and threat clocks.
::::
```

If a widget does not have a `title` attribute, Paper Crown uses the first
heading inside the fenced div as the title:

```markdown
:::: {.pc-procedure usage="Travel"}
### Overland Watch

1. Choose pace.
2. Check for discoveries.
3. Roll for hazards.
::::
```

## Metadata

Supported metadata fields are:

| Field | Common use |
| --- | --- |
| `title` | Display title for the widget |
| `level` | Feature level or tier |
| `cost` | Resource, action, slot, or price |
| `trigger` | Timing condition |
| `duration` | How long the effect lasts |
| `usage` | At-will, reaction, downtime, travel, per rest, or similar |
| `recharge` | Recharge rule or refresh condition |
| `tags` | Comma-separated labels for the author or theme |

Keep metadata short. Put rulings, exceptions, examples, and table text in the
body of the widget.

## How It Works

During assembly, Paper Crown resolves each chapter source through the configured
vault aliases, exports Obsidian-style content when needed, normalizes headings,
and runs the Markdown filters used by both PDF and web renderers. The same
assembled HTML then flows into the selected theme.
