# Markdown Components

Paper Crown supports ordinary Markdown first. Use these optional components
when a rule needs to stand out as a reusable game object rather than a plain
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
