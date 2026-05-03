# Vaults and Markdown

:::: {.flourish-note .flourish-folder}
Vaults are named Markdown roots. They let one book pull from reusable rules,
setting notes, campaign material, or local overrides without moving source
files into Paper Crown.
::::

Markdown should stay readable in your editor first. Paper Crown adds source
resolution, Obsidian-style links, embedded images, and optional TTRPG widgets.

<div class="art-rule art-rule-folder" aria-hidden="true"></div>

## How to Use It

Give each content root an alias:

```yaml
vaults:
  rules: ../rules-vault
  setting: ../setting-notes

contents:
  - kind: file
    title: Primer
    source: rules:Primer.md
```

If a source has no vault prefix, Paper Crown searches the vault overlay by path
or stem. Prefer explicit aliases in larger books so moves and overrides are
obvious.

## Markdown

Headings, paragraphs, lists, tables, code blocks, links, and images are normal
Markdown. Internal Markdown links and Obsidian wikilinks are resolved during
assembly when the target exists in the vault set.

Use ordinary Markdown for ordinary rules. Reach for widgets only when the text
is a reusable game object.

## Rules Widgets

Widgets use Pandoc fenced divs.

### Feature

```markdown
:::: {.pc-feature title="Sneak Attack" level="1" tags="rogue,damage"}
Once per turn, add extra damage when you have advantage or an ally is adjacent.
::::
```

### Ability

```markdown
:::: {.pc-ability title="Overcharge" cost="1 Charge" duration="Instant"}
Push the engine past its limit, then mark heat.
::::
```

### Procedure

```markdown
:::: {.pc-procedure title="Recovery Turn" usage="Downtime"}
1. Clear temporary conditions.
2. Spend resources on repairs, healing, or research.
3. Advance faction and threat clocks.
::::
```

If a widget does not have a `title` attribute, Paper Crown uses the first
heading inside it as the title.

## Metadata

Supported widget metadata:

| Field | Common use |
| --- | --- |
| `title` | Display title |
| `level` | Feature level or tier |
| `cost` | Resource, action, slot, or price |
| `trigger` | Timing condition |
| `duration` | How long the effect lasts |
| `usage` | At-will, reaction, downtime, travel, or per rest |
| `recharge` | Refresh rule |
| `tags` | Comma-separated labels for authors or themes |

Keep metadata short and put rulings, examples, and table text in the widget
body.
