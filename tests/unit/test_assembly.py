"""Unit tests for chapter / book markdown assembly.

These tests don't run Pandoc; they exercise the pure-Python text munging that
glues source files together before the renderer ever sees them.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from papercrown import assembly
from papercrown.manifest import Chapter, ChapterFillerSlot, Splash
from papercrown.vaults import Vault, VaultIndex


def _write(p: Path, body: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# assemble_chapter_markdown
# ---------------------------------------------------------------------------


class TestAssembleChapterMarkdown:
    def test_empty_chapter_emits_placeholder(self):
        ch = Chapter(title="Mystery", slug="mystery")
        out = assembly.assemble_chapter_markdown(ch)
        assert "# Mystery" in out
        assert "*(empty)*" in out

    def test_single_file_passes_through(self, tmp_path):
        f = _write(tmp_path / "a.md", "# A\nbody\n")
        ch = Chapter(title="A", slug="a", source_files=[f])
        out = assembly.assemble_chapter_markdown(ch)
        assert out.startswith("# A")
        assert "body" in out

    def test_demotes_h1_in_subsequent_files(self, tmp_path):
        f1 = _write(tmp_path / "a.md", "# A\nbody A\n")
        f2 = _write(tmp_path / "b.md", "# B\nbody B\n")
        ch = Chapter(title="A", slug="a", source_files=[f1, f2])
        out = assembly.assemble_chapter_markdown(ch)
        # First file's h1 is preserved; second file's h1 -> h2
        assert "# A" in out
        assert "## B" in out
        # Original h1 of B must NOT survive as an h1
        lines = out.splitlines()
        h1_count = sum(1 for ln in lines if ln.startswith("# "))
        assert h1_count == 1

    def test_single_exported_file_turns_later_h1s_into_major_dividers(self, tmp_path):
        f = _write(
            tmp_path / "frames.md",
            """
            # Frames
            intro

            # Baseline Human
            frame family text

            ### Baseline Human (Human)
            variant text
        """,
        )
        ch = Chapter(title="Frames", slug="frames", source_files=[f])
        out = assembly.assemble_chapter_markdown(ch)
        assert out.splitlines().count("# Frames") == 1
        assert 'data-chapter-name="Frames / Baseline Human"' in out
        assert "[Frames](#frames)" in out
        assert "## Baseline Human {.section-divider-title #baseline-human}" in out
        assert "### Baseline Human (Human)" in out
        assert "\n# Baseline Human\n" not in f"\n{out}\n"

    def test_auto_frame_table_marker_derives_rows_from_headings(self, tmp_path):
        f = _write(
            tmp_path / "frames.md",
            """
            # Frames
            intro

            <!-- AUTO_FRAME_TABLE -->

            # Heavyworlder Native

            ### Gravwell Native (Dwarf)
            body

            # Symbiote-Bonded

            ### Deadlink Subject (Lichmarked)
            body
        """,
        )
        ch = Chapter(title="Frames", slug="frames", source_files=[f])
        out = assembly.assemble_chapter_markdown(ch)
        assert "<!-- AUTO_FRAME_TABLE -->" not in out
        assert ":::: {.frame-summary-table}" in out
        assert "| Variant | Frame Family |" in out
        assert (
            "| [Gravwell Native *(Dwarf)*](#gravwell-native-dwarf) "
            "| [Heavyworlder Native](#heavyworlder-native) |"
        ) in out
        assert (
            "| [Deadlink Subject *(Lichmarked)*](#deadlink-subject-lichmarked) "
            "| [Symbiote-Bonded](#symbiote-bonded) |"
        ) in out

    def test_strips_yaml_frontmatter(self, tmp_path):
        f = _write(
            tmp_path / "a.md",
            """
            ---
            title: ignored
            tags: [x, y]
            ---
            # Real Title
            body
        """,
        )
        ch = Chapter(title="Real Title", slug="real-title", source_files=[f])
        out = assembly.assemble_chapter_markdown(ch)
        assert "ignored" not in out
        assert "# Real Title" in out

    def test_prepends_title_when_first_file_has_no_heading(self, tmp_path):
        f = _write(tmp_path / "a.md", "just some body text\n")
        ch = Chapter(title="Pretty Title", slug="pretty-title", source_files=[f])
        out = assembly.assemble_chapter_markdown(ch)
        assert out.startswith("# Pretty Title")

    def test_original_ancestry_size_line_is_normalized(self, tmp_path):
        f = _write(
            tmp_path / "human.md",
            """
            (Small or Medium)

            *An original ancestry description.*
            """,
        )
        ch = Chapter(
            title="Original - Human",
            slug="original-human",
            style="ancestries",
            source_files=[f],
        )
        out = assembly.assemble_chapter_markdown(ch)
        assert "## Small or Medium" in out
        assert "(Small or Medium)" not in out

    def test_non_original_ancestry_size_parenthetical_is_left_alone(self, tmp_path):
        f = _write(
            tmp_path / "human.md",
            """
            (Medium)

            Body.
            """,
        )
        ch = Chapter(
            title="Baseline Human",
            slug="baseline-human",
            style="ancestries",
            source_files=[f],
        )
        out = assembly.assemble_chapter_markdown(ch)
        assert "(Medium)" in out
        assert "**Size:** Medium" not in out
        assert "## Medium" not in out

    def test_inserts_blank_before_tight_heading(self, tmp_path):
        f = _write(
            tmp_path / "a.md",
            """
            Intro paragraph.
            ### Tight Heading
            Body.
        """,
        )
        ch = Chapter(title="A", slug="a", source_files=[f])
        out = assembly.assemble_chapter_markdown(ch)
        assert "Intro paragraph.\n\n### Tight Heading" in out

    def test_sequence_source_title_is_inserted_for_untitled_file(self, tmp_path):
        intro = _write(tmp_path / "intro.md", "# Combat\nintro\n")
        rule = _write(tmp_path / "rule.md", "rule body\n### Subrule\n")
        ch = Chapter(
            title="Combat",
            slug="combat",
            source_files=[intro, rule],
            source_titles=[None, "Combat Structure"],
        )
        out = assembly.assemble_chapter_markdown(ch)
        assert "## Combat Structure" in out
        assert "rule body" in out
        assert "#### Subrule" in out

    def test_sequence_source_title_does_not_duplicate_existing_heading(self, tmp_path):
        intro = _write(tmp_path / "intro.md", "# Combat\nintro\n")
        gear = _write(tmp_path / "gear.md", "## Weapons & Armor\nbody\n")
        ch = Chapter(
            title="Combat",
            slug="combat",
            source_files=[intro, gear],
            source_titles=[None, "Weapons & Armor"],
        )
        out = assembly.assemble_chapter_markdown(ch)
        lines = out.splitlines()
        assert lines.count("### Weapons & Armor") == 1
        assert "## Weapons & Armor" not in lines

    def test_sequence_source_title_accepts_parenthetical_source_link(self, tmp_path):
        intro = _write(tmp_path / "intro.md", "# Combat\nintro\n")
        actions = _write(
            tmp_path / "actions.md",
            "# Heroic Actions ([Heroic Actions](#original-heroic-actions))\nbody\n",
        )
        ch = Chapter(
            title="Combat",
            slug="combat",
            source_files=[intro, actions],
            source_titles=[None, "Heroic Actions"],
        )
        out = assembly.assemble_chapter_markdown(ch)
        lines = out.splitlines()
        assert (
            lines.count(
                "## Heroic Actions ([Heroic Actions](#original-heroic-actions))"
            )
            == 1
        )
        assert "## Heroic Actions" not in lines

    def test_sequence_can_strip_trailing_related_section(self, tmp_path):
        intro = _write(tmp_path / "intro.md", "# Combat\nintro\n")
        rule = _write(
            tmp_path / "rule.md",
            """
            body

            ---

            **Related**

            - [[Heroic Actions]]
        """,
        )
        ch = Chapter(
            title="Combat",
            slug="combat",
            source_files=[intro, rule],
            source_titles=[None, "Combat Structure"],
            source_strip_related=[False, True],
        )
        out = assembly.assemble_chapter_markdown(ch)
        assert "**Related**" not in out
        assert "Heroic Actions" not in out

    def test_export_map_is_followed(self, tmp_path):
        src = _write(tmp_path / "src.md", "# Source\nfrom raw\n")
        exp = _write(tmp_path / "exp.md", "# Source\nfrom export\n")
        ch = Chapter(title="Source", slug="source", source_files=[src])
        out = assembly.assemble_chapter_markdown(
            ch,
            export_map={src.resolve(): exp.resolve()},
        )
        assert "from export" in out
        assert "from raw" not in out

    def test_lossy_exported_embeds_expand_from_source_vault(self, tmp_path):
        vault = tmp_path / "vault"
        src = _write(
            vault / "Magic" / "Spell List.md",
            """
            # Lightning Spells

            ![[Zap]]

            ---
        """,
        )
        _write(
            vault / "Magic" / "Spells" / "Lightning Spells" / "Zap.md",
            """
            *Cantrip Lightning Spell*

            1 Action | Single Target | Range 12

            **Damage:** 2d8.
        """,
        )
        lossy = _write(
            tmp_path / "export" / "Spell List.md",
            """
            # Lightning Spells

            ---
        """,
        )
        ch = Chapter(
            title="Original - Spell Lists",
            slug="original-spell-lists",
            source_files=[src],
        )
        out = assembly.assemble_chapter_markdown(
            ch,
            export_map={src.resolve(): lossy.resolve()},
            vault_index=VaultIndex([Vault("v", vault)]),
        )
        assert "![[Zap]]" not in out
        assert "## Zap" in out
        assert "*Cantrip Lightning Spell*" in out
        assert "**Damage:** 2d8." in out

    def test_expanded_embed_does_not_duplicate_existing_title_heading(self, tmp_path):
        vault = tmp_path / "vault"
        src = _write(
            vault / "Heroes" / "Ancestries List.md",
            """
            # Frames

            ![[Baseline Human]]
        """,
        )
        _write(
            vault / "Heroes" / "Ancestries" / "Baseline Human.md",
            """
            :::: {.frame #baseline-human title="Baseline Human"}

            # Baseline Human

            Baseline intro.
            ::::
        """,
        )
        ch = Chapter(
            title="Frames",
            slug="frames",
            style="ancestries",
            source_files=[src],
        )

        out = assembly.assemble_chapter_markdown(
            ch,
            vault_index=VaultIndex([Vault("v", vault)]),
        )

        assert "\n## Baseline Human\n\n::::" not in f"\n{out}\n"
        divider = "## Baseline Human {.section-divider-title #baseline-human}"
        assert out.count(divider) == 1
        assert out.index(divider) < out.index("Baseline intro.")

    def test_demote_does_not_touch_code_blocks(self, tmp_path):
        f1 = _write(tmp_path / "a.md", "# A\nbody A\n")
        f2 = _write(tmp_path / "b.md", "# B\n```\n# Not a heading\n```\n")
        ch = Chapter(title="A", slug="a", source_files=[f1, f2])
        out = assembly.assemble_chapter_markdown(ch)
        assert "# Not a heading" in out  # unchanged inside code fence

    def test_full_page_sections_turns_heading_into_divider(self, tmp_path):
        f = _write(tmp_path / "a.md", "# A\n## Special Section\nbody\n")
        ch = Chapter(
            title="A",
            slug="a",
            source_files=[f],
            full_page_sections=["special-section"],
        )
        out = assembly.assemble_chapter_markdown(ch)
        assert 'data-chapter-name="A / Special Section"' in out
        assert "[A](#a)" in out
        assert "## Special Section {.section-divider-title #special-section}" in out
        assert "\n## Special Section\n" not in f"\n{out}\n"

    def test_source_reference_opening_size_line_becomes_heading(self, tmp_path):
        f = _write(
            tmp_path / "human.md",
            """
            (Medium)

            *Baseline stock.*
        """,
        )
        ch = Chapter(
            title="Original - Human",
            slug="original-human",
            style="source-reference",
            source_files=[f],
        )
        out = assembly.assemble_chapter_markdown(ch)
        assert "(Medium)" not in out
        assert "## Medium" in out

    def test_original_reference_feature_labels_get_linkable_anchors(self, tmp_path):
        levels = _write(
            tmp_path / "Berserker Levels.md",
            """
            # Levels
            **Rage**
            Original feature text.
        """,
        )
        arsenal = _write(
            tmp_path / "Savage Arsenal.md",
            """
            **Deathless Rage**
            Original option text.
        """,
        )
        invocations = _write(
            tmp_path / "Invocations.md",
            """
            # Lesser Invocations
            **Shadowmastery**
            Original utility text.
        """,
        )
        ch = Chapter(
            title="Original - Berserker",
            slug="original-berserker",
            source_files=[levels, arsenal, invocations],
        )

        out = assembly.assemble_chapter_markdown(ch)

        for anchor in (
            "original-berserker-levels",
            "original-rage",
            "original-savage-arsenal",
            "original-deathless-rage",
            "original-lesser-invocations",
            "original-shadowmastery",
            "original-invocations",
        ):
            assert out.count(f"{{.pdf-anchor #{anchor}}}") == 1

    def test_original_source_anchor_does_not_duplicate_chapter_slug(self, tmp_path):
        source = _write(
            tmp_path / "Conditions.md",
            """
            # Conditions
            Body.
        """,
        )
        ch = Chapter(
            title="Conditions",
            slug="original-conditions",
            source_files=[source],
        )

        out = assembly.assemble_combined_book_markdown([ch], include_toc=True)

        assert ".section-divider-title #original-conditions" in out
        assert "{.pdf-anchor #original-conditions}" not in out

    def test_generated_original_anchors_are_deduped_in_combined_book(self, tmp_path):
        first = _write(
            tmp_path / "First Levels.md",
            """
            # Levels
            **Level 1**
            First.
        """,
        )
        second = _write(
            tmp_path / "Second Levels.md",
            """
            # Levels
            **Level 1**
            Second.
        """,
        )
        chapters = [
            Chapter(
                title="First",
                slug="original-first",
                source_files=[first],
            ),
            Chapter(
                title="Second",
                slug="original-second",
                source_files=[second],
            ),
        ]

        out = assembly.assemble_combined_book_markdown(chapters, include_toc=True)

        assert "{.pdf-anchor #original-level-1}" in out
        assert "{.pdf-anchor #original-level-1-1}" in out
        assert out.count("{.pdf-anchor #original-level-1}") == 1

    def test_class_spot_replaces_opening_hand_authored_spot(self, tmp_path):
        spot = tmp_path / "class-spot.png"
        spot.write_text("fake", encoding="utf-8")
        f = _write(
            tmp_path / "a.md",
            """
            # A

            :::: {.art-right .art-spot}
            ![](old-spot.png)
            ::::

            intro
        """,
        )
        ch = Chapter(
            title="A",
            slug="a",
            source_files=[f],
            spot_art_path=spot,
            replace_opening_art=True,
        )
        out = assembly.assemble_chapter_markdown(ch)
        assert ".class-opening-spot .art-right .art-spot" in out
        assert f"![](<{spot.as_posix()}>)" in out
        assert "old-spot.png" not in out
        assert out.index(".class-opening-spot") < out.index("intro")

    def test_class_spot_replaces_opening_spot_after_source_marker(self, tmp_path):
        spot = tmp_path / "class-spot.png"
        spot.write_text("fake", encoding="utf-8")
        f = _write(
            tmp_path / "a.md",
            """
            # A

            :::: {.art-right .art-spot}
            ![](old-spot.png)
            ::::

            intro
        """,
        )
        ch = Chapter(
            title="A",
            slug="a",
            source_files=[f],
            spot_art_path=spot,
            replace_opening_art=True,
        )
        out = assembly.assemble_chapter_markdown(ch, include_source_markers=True)
        assert ".class-opening-spot .art-right .art-spot" in out
        assert "papercrown-source-file:" in out
        assert "old-spot.png" not in out
        assert out.index("papercrown-source-file:") < out.index("intro")
        assert out.index(".class-opening-spot") < out.index("intro")

    def test_tailpiece_emits_conditional_filler_slot(self, tmp_path):
        f = _write(tmp_path / "a.md", "# A\nbody\n")
        plain = assembly.assemble_chapter_markdown(
            Chapter(title="A", slug="a", source_files=[f])
        )
        slotted = assembly.assemble_chapter_markdown(
            Chapter(
                title="A",
                slug="a",
                source_files=[f],
                filler_slots=[
                    ChapterFillerSlot(
                        id="filler-chapter-end-a",
                        slot="chapter-end",
                        chapter_slug="a",
                        preferred_asset_id="tail",
                    )
                ],
            )
        )
        assert ".ornament-tailpiece" not in plain
        assert ".ornament-tailpiece" not in slotted
        assert ".filler-slot" in slotted
        assert 'data-slot="chapter-end"' in slotted
        assert 'data-chapter="a"' in slotted
        assert 'data-preferred-filler="tail"' in slotted

    def test_frame_section_art_moves_from_body_flow_to_divider(self, tmp_path):
        f = _write(
            tmp_path / "frames.md",
            """
            # Frames
            Intro text.

            # Baseline Human

            ::: {.art-wide .art-frame}
            ![](frame-baseline-human.png)
            :::

            Baseline intro.

            ### Baseline Human Stats
            Baseline stats.

            # Heavyworlder Native

            ::: {.art-wide .art-frame}
            ![](<frame-heavyworlder-native.png>)
            :::

            Heavy intro.
            Heavy stats.
        """,
        )
        ch = Chapter(
            title="Frames",
            slug="frames",
            style="ancestries",
            source_files=[f],
            filler_slots=[
                ChapterFillerSlot(
                    id="filler-chapter-end-frames",
                    slot="chapter-end",
                    chapter_slug="frames",
                )
            ],
        )

        out = assembly.assemble_chapter_markdown(ch)

        assert ".section-divider-frame-art" in out
        assert (
            "![](<frame-baseline-human.png>)"
            "{.section-divider-art .section-divider-frame-art}" in out
        )
        assert (
            "![](<frame-heavyworlder-native.png>)"
            "{.section-divider-art .section-divider-frame-art}" in out
        )
        assert ".art-frame" not in out
        assert out.index("frame-baseline-human.png") < out.index("Baseline intro.")
        assert out.index("Baseline intro.") < out.index("Baseline Human Stats")
        assert "filler-section-end" not in out

    def test_section_end_slots_are_limited_to_opted_layouts(self, tmp_path):
        f = _write(
            tmp_path / "a.md",
            """
            # A
            Intro.

            ## Section
            Body.
        """,
        )
        ch = Chapter(
            title="A",
            slug="a",
            source_files=[f],
            filler_slots=[
                ChapterFillerSlot(
                    id="filler-chapter-end-a",
                    slot="chapter-end",
                    chapter_slug="a",
                )
            ],
        )

        out = assembly.assemble_chapter_markdown(ch)

        assert "filler-section-end" not in out
        assert "filler-chapter-end-a" in out

    def test_subclass_end_slot_ids_include_source_context(self, tmp_path):
        first = _write(
            tmp_path / "Mage" / "Subclasses" / "Alpha" / "Level 3.md",
            "# Level 3\nAlpha subclass text.\n",
        )
        second = _write(
            tmp_path / "Mage" / "Subclasses" / "Beta" / "Level 3.md",
            "# Level 3\nBeta subclass text.\n",
        )
        ch = Chapter(
            title="Mage",
            slug="mage",
            style="class",
            source_files=[first, second],
        )

        out = assembly.assemble_chapter_markdown(ch)

        assert "#filler-subclass-end-mage-alpha-level-3" in out
        assert "#filler-subclass-end-mage-beta-level-3" in out
        assert out.count("#filler-subclass-end-mage-") == 2

    def test_original_class_chapters_do_not_emit_subclass_end_slots(self, tmp_path):
        source = _write(
            tmp_path / "Mage" / "Subclasses" / "Alpha" / "Level 3.md",
            "# Level 3\nOriginal subclass text.\n",
        )
        ch = Chapter(
            title="Original Mage",
            slug="original-mage",
            style="class",
            source_files=[source],
        )

        out = assembly.assemble_chapter_markdown(ch)

        assert "filler-subclass-end" not in out

    def test_sequence_source_boundaries_emit_contextual_section_end_slots(
        self,
        tmp_path,
    ):
        combat = _write(tmp_path / "System" / "Combat.md", "# Combat\nIntro.\n")
        weapons = _write(
            tmp_path / "Items" / "Weapons & Armor.md",
            "# Weapons & Armor\nGear.\n",
        )
        artifacts = _write(
            tmp_path / "Items" / "Prototype Artifacts.md",
            "# Prototype Artifacts\nRare gear.\n",
        )
        ch = Chapter(
            title="Combat",
            slug="combat",
            style="equipment",
            source_files=[combat, weapons, artifacts],
            source_titles=[None, "Weapons & Armor", "Prototype Artifacts"],
            source_boundary_filler_slot="section-end",
        )

        out = assembly.assemble_chapter_markdown(ch)

        assert "#filler-section-end-combat-system-combat" in out
        assert "#filler-section-end-combat-items-weapons-armor" in out
        assert out.count('data-slot="section-end"') == 2
        assert out.count('data-slot-kind="source-boundary"') == 2
        assert 'data-filler-context="combat"' in out
        assert 'data-filler-context="equipment"' in out
        assert "filler-section-end-combat-prototype-artifacts" not in out

    def test_sequence_source_boundary_filler_can_be_disabled_per_source(
        self,
        tmp_path,
    ):
        first = _write(tmp_path / "first.md", "# First\nIntro.\n")
        second = _write(tmp_path / "second.md", "# Second\nMore.\n")
        third = _write(tmp_path / "third.md", "# Third\nDone.\n")
        ch = Chapter(
            title="Combat",
            slug="combat",
            style="equipment",
            source_files=[first, second, third],
            source_filler_enabled=[False, True, True],
            source_boundary_filler_slot="section-end",
        )

        out = assembly.assemble_chapter_markdown(ch)

        assert "#filler-section-end-combat-first" not in out
        assert out.count('data-slot="section-end"') == 1
        assert 'data-section-title="Second"' in out

    def test_sequence_wrapper_heading_can_be_removed_to_avoid_orphan_page(
        self,
        tmp_path,
    ):
        intro = _write(tmp_path / "intro.md", "# Powers\nintro\n")
        powers = _write(
            tmp_path / "powers.md",
            """
            # Tiered Power List

            ## Thermal Powers

            ### Flame Dart
            body
        """,
        )
        ch = Chapter(
            title="Powers",
            slug="powers",
            source_files=[intro, powers],
            source_titles=[None, "Tiered Power List"],
        )

        out = assembly.assemble_chapter_markdown(ch)

        assert "## Tiered Power List" not in out
        assert "### Thermal Powers" in out
        assert "#### Flame Dart" in out

    def test_headpiece_is_inserted_after_leading_heading(self, tmp_path):
        f = _write(tmp_path / "a.md", "# A\nintro\n")
        headpiece = tmp_path / "head.png"
        headpiece.write_text("fake", encoding="utf-8")
        ch = Chapter(
            title="A",
            slug="a",
            source_files=[f],
            headpiece_path=headpiece,
        )
        out = assembly.assemble_chapter_markdown(ch)
        assert ".ornament-headpiece" in out
        assert out.index(".ornament-headpiece") < out.index("intro")

    def test_break_ornament_replaces_thematic_breaks_when_opted_in(self, tmp_path):
        f = _write(tmp_path / "a.md", "# A\nbefore\n\n---\n\nafter\n")
        ornament = tmp_path / "break.png"
        ornament.write_text("fake", encoding="utf-8")
        ch = Chapter(
            title="A",
            slug="a",
            source_files=[f],
            break_ornament_path=ornament,
        )
        out = assembly.assemble_chapter_markdown(ch)
        assert "\n---\n" not in out
        assert ".ornament-break" in out
        assert f"![](<{ornament.as_posix()}>)" in out

    def test_tailpiece_can_render_as_explicit_art(self, tmp_path):
        f = _write(tmp_path / "a.md", "# A\nbody\n")
        tailpiece = tmp_path / "tail.png"
        tailpiece.write_text("fake", encoding="utf-8")
        ch = Chapter(
            title="A",
            slug="a",
            source_files=[f],
            tailpiece_path=tailpiece,
        )

        default = assembly.assemble_chapter_markdown(ch)
        explicit = assembly.assemble_chapter_markdown(ch, include_tailpiece_art=True)

        assert ".ornament-tailpiece" not in default
        assert ".ornament-tailpiece" in explicit
        assert f"![](<{tailpiece.as_posix()}>)" in explicit
        assert explicit.index("body") < explicit.index(".ornament-tailpiece")

    def test_splash_blocks_insert_at_chapter_start_and_after_heading(self, tmp_path):
        f = _write(tmp_path / "a.md", "# A\nintro\n\n## Factions\nbody\n")
        start = tmp_path / "start.png"
        corner = tmp_path / "corner.png"
        start.write_text("fake", encoding="utf-8")
        corner.write_text("fake", encoding="utf-8")
        ch = Chapter(title="A", slug="a", source_files=[f])
        out = assembly.assemble_chapter_markdown(
            ch,
            splashes=[
                Splash(
                    id="start",
                    art_path=start,
                    target="chapter-start",
                    placement="bottom-half",
                    chapter_slug="a",
                ),
                Splash(
                    id="corner",
                    art_path=corner,
                    target="after-heading",
                    placement="corner-right",
                    chapter_slug="a",
                    heading_slug="factions",
                ),
            ],
        )
        assert "#splash-start" in out
        assert ".splash-bottom-half" in out
        assert "#splash-corner" in out
        assert ".splash-corner-right" in out
        assert out.index("#splash-start") < out.index("intro")
        assert out.index("## Factions") < out.index("#splash-corner")

    def test_splash_after_heading_matches_rendered_heading_suffix(self, tmp_path):
        f = _write(
            tmp_path / "a.md",
            "# A\nintro\n\n## Power Activation (Spellcasting)\nbody\n",
        )
        corner = tmp_path / "corner.png"
        corner.write_text("fake", encoding="utf-8")
        ch = Chapter(title="A", slug="a", source_files=[f])
        out = assembly.assemble_chapter_markdown(
            ch,
            splashes=[
                Splash(
                    id="corner",
                    art_path=corner,
                    target="after-heading",
                    placement="corner-left",
                    chapter_slug="a",
                    heading_slug="power-activation",
                ),
            ],
        )
        assert "## Power Activation (Spellcasting)" in out
        assert "#splash-corner" in out
        assert out.index("## Power Activation") < out.index("#splash-corner")

    def test_thematic_breaks_remain_plain_markdown_rules(self, tmp_path):
        f = _write(tmp_path / "a.md", "# A\nbefore\n\n---\n\nafter\n")
        ch = Chapter(title="A", slug="a", source_files=[f])
        out = assembly.assemble_chapter_markdown(ch)
        assert "\n---\n" in out
        assert "ornament-break" not in out


# ---------------------------------------------------------------------------
# assemble_combined_book_markdown
# ---------------------------------------------------------------------------


class TestAssembleCombinedBookMarkdown:
    def test_emits_section_divider_per_top_level(self, tmp_path):
        f = _write(tmp_path / "a.md", "# A\nbody A\n")
        chapters = [
            Chapter(title="One", slug="one", source_files=[f]),
            Chapter(title="Two", slug="two", source_files=[f]),
        ]
        out = assembly.assemble_combined_book_markdown(chapters)
        # One section-divider per top-level chapter
        assert out.count(".section-divider data-chapter-name") == 2
        # Both chapter slugs appear as div ids
        assert 'id="div-one"' in out
        assert 'id="div-two"' in out

    def test_combined_book_appends_back_cover_splash_when_art_enabled(self, tmp_path):
        f = _write(tmp_path / "a.md", "# A\nbody A\n")
        art = tmp_path / "back.png"
        art.write_text("fake", encoding="utf-8")
        ch = Chapter(title="A", slug="a", source_files=[f])
        splash = Splash(
            id="back",
            art_path=art,
            target="back-cover",
            placement="back-cover",
        )
        out = assembly.assemble_combined_book_markdown([ch], splashes=[splash])
        draft = assembly.assemble_combined_book_markdown(
            [ch],
            include_art=False,
            splashes=[splash],
        )
        assert ".splash-back-cover" in out
        assert ".cover-back-page" in out
        assert ".cover-back-art" in out
        assert "#splash-back" in out
        assert ".splash-back-cover" not in draft
        terminal = assembly.assemble_combined_book_markdown(
            [ch],
            splashes=[splash],
            include_back_cover_splashes=False,
        )
        assert ".splash-back-cover" not in terminal

    def test_top_level_non_wrapper_body_is_rendered(self, tmp_path):
        # Regression: a previous revision unconditionally skipped the top
        # chapter inside the descendant loop, which silently dropped every
        # non-wrapper top-level chapter (Setting Primer, Languages, Frames,
        # Backgrounds in the production recipe) -- they got their divider
        # but no body, no h1, no TOC entry, and no PDF outline bookmark.
        f = _write(tmp_path / "setting.md", "# Setting Primer\nintro paragraph\n")
        ch = Chapter(title="Setting Primer", slug="setting-primer", source_files=[f])
        out = assembly.assemble_combined_book_markdown([ch])
        # Body content survives.
        assert "intro paragraph" in out
        # The divider supplies the canonical h1, so the body's duplicate h1
        # is stripped.
        assert "# Setting Primer {.section-divider-title #setting-primer}" in out
        assert "\n# Setting Primer\n" not in out
        # And the body sits inside the chapter-wrap fenced div.
        assert "#ch-setting-primer" in out

    def test_top_level_non_wrapper_divider_is_canonical_heading(self, tmp_path):
        # The divider for a non-wrapper top-level chapter should be a real
        # heading and the body h1 should be stripped so the TOC/sidebar have
        # one canonical target.
        f = _write(tmp_path / "a.md", "# A\nbody A\n")
        ch = Chapter(title="A", slug="a", source_files=[f])
        out = assembly.assemble_combined_book_markdown([ch])
        # Sanity: only one ATX h1 line for "A" in the assembled markdown.
        h1_lines = [ln for ln in out.splitlines() if ln.strip().startswith("# A")]
        assert len(h1_lines) == 1

    def test_wrapper_top_level_emits_real_h1(self, tmp_path):
        # Wrapper = no own source_files but has children
        leaf = Chapter(
            title="Leaf",
            slug="leaf",
            source_files=[_write(tmp_path / "leaf.md", "# Leaf\nbody\n")],
        )
        wrap = Chapter(title="Wrap", slug="wrap", children=[leaf])
        out = assembly.assemble_combined_book_markdown([wrap])
        # The wrapper title appears as an actual ATX h1 with the divider class
        assert "# Wrap {.section-divider-title #wrap}" in out

    def test_nested_chapter_with_divider_demotes_headings(self, tmp_path):
        leaf = Chapter(
            title="Leaf",
            slug="leaf",
            divider=True,
            source_files=[_write(tmp_path / "leaf.md", "# Leaf\n## Sub\nbody\n")],
        )
        wrap = Chapter(title="Wrap", slug="wrap", children=[leaf])
        out = assembly.assemble_combined_book_markdown([wrap])
        # Leaf's `# Leaf` is stripped (the divider supplies the heading)
        # and `## Sub` is demoted by depth=1 to `### Sub`
        assert 'data-chapter-name="Wrap / Leaf"' in out
        assert "### Sub" in out
        # The only surviving `## Leaf` line is the divider's own styled title
        # heading (ATX attributes attached). There must NOT be a bare
        # un-styled `## Leaf` line left behind from the body -- that would
        # produce a duplicate TOC entry.
        leaf_h2_lines = [
            ln for ln in out.splitlines() if ln.strip().startswith("## Leaf")
        ]
        assert len(leaf_h2_lines) == 1, leaf_h2_lines
        assert ".section-divider-title" in leaf_h2_lines[0], leaf_h2_lines[0]
        assert "#leaf" in leaf_h2_lines[0], leaf_h2_lines[0]

    def test_nested_chapter_without_divider_just_demotes(self, tmp_path):
        leaf = Chapter(
            title="Leaf",
            slug="leaf",  # divider defaults to False
            source_files=[_write(tmp_path / "leaf.md", "# Leaf\n## Sub\nbody\n")],
        )
        wrap = Chapter(title="Wrap", slug="wrap", children=[leaf])
        out = assembly.assemble_combined_book_markdown([wrap])
        # Without divider: leaf h1 -> h2 (depth=1), sub h2 -> h3
        assert "## Leaf {#leaf}" in out
        assert "### Sub" in out

    def test_nested_chapter_without_divider_keeps_slug_anchor(self, tmp_path):
        leaf = Chapter(
            title="Original - Survivalist",
            slug="original-survivalist",
            source_files=[_write(tmp_path / "survivalist.md", "body\n")],
        )
        wrap = Chapter(
            title="Original Background Reference",
            slug="original-background-reference",
            children=[leaf],
        )
        out = assembly.assemble_combined_book_markdown([wrap])
        assert "## Original - Survivalist {#original-survivalist}" in out
        assert "#ch-original-survivalist" in out

    def test_include_toc_prepends_manual_toc_from_heading_tree(self, tmp_path):
        frames = Chapter(
            title="Frames",
            slug="frames",
            source_files=[
                _write(
                    tmp_path / "frames.md",
                    "# Frames\n# Baseline Human\n### Baseline Human (Human)\n",
                )
            ],
        )
        out = assembly.assemble_combined_book_markdown([frames], include_toc=True)
        assert out.startswith(':::: {.toc role="doc-toc"}')
        assert "- [Frames](#frames)" in out
        assert "  - [Baseline Human](#baseline-human)" in out
        assert "    - [Baseline Human (Human)](#baseline-human-human)" in out
        assert out.index("[Frames](#frames)") < out.index(
            "[Baseline Human](#baseline-human)"
        )

    def test_top_level_toc_depth_caps_deep_entries(self, tmp_path):
        chapters = [
            Chapter(
                title="Frames",
                slug="frames",
                toc_depth=2,
                source_files=[
                    _write(
                        tmp_path / "frames.md",
                        "# Frames\n# Engineered Light\n### Nanoscale Drifter (Pixie)\n",
                    )
                ],
            ),
            Chapter(
                title="Backgrounds",
                slug="backgrounds",
                toc_depth=2,
                source_files=[
                    _write(
                        tmp_path / "backgrounds.md",
                        "# Backgrounds\n## Spacer Trash\n### Perk\n",
                    )
                ],
            ),
            Chapter(
                title="Character Classes",
                slug="character-classes",
                toc_depth=2,
                children=[
                    Chapter(
                        title="Commander",
                        slug="commander",
                        divider=True,
                        source_files=[
                            _write(
                                tmp_path / "commander.md",
                                "# Commander\n## Orders\n",
                            )
                        ],
                    ),
                ],
            ),
        ]
        out = assembly.assemble_combined_book_markdown(chapters, include_toc=True)
        toc = out.split("\n\n:::::", 1)[0]
        assert "- [Frames](#frames)" in toc
        assert "  - [Engineered Light](#engineered-light)" in toc
        assert "Nanoscale Drifter" not in toc
        assert "- [Backgrounds](#backgrounds)" in toc
        assert "  - [Spacer Trash](#spacer-trash)" in toc
        assert "Perk" not in toc
        assert "- [Character Classes](#character-classes)" in toc
        assert "  - [Commander](#commander)" in toc
        assert "Orders" not in toc

    def test_manual_toc_max_depth_caps_entries_without_overriding_stricter_chapters(
        self,
    ):
        chapters = [
            Chapter(title="Open Chapter", slug="open-chapter", toc_depth=4),
            Chapter(title="Strict Chapter", slug="strict-chapter", toc_depth=1),
        ]
        markdown = (
            "# Open Chapter {#open-chapter}\n\n"
            "## Major Section\n\n"
            "### Deep Detail\n\n"
            "# Strict Chapter {#strict-chapter}\n\n"
            "## Hidden Section\n"
        )

        out = assembly.add_manual_toc(markdown, chapters, max_depth=2)
        toc = out.split("\n\n# Open Chapter", 1)[0]

        assert "- [Open Chapter](#open-chapter)" in toc
        assert "  - [Major Section](#major-section)" in toc
        assert "Deep Detail" not in toc
        assert "- [Strict Chapter](#strict-chapter)" in toc
        assert "Hidden Section" not in toc
        assert "### Deep Detail {#deep-detail}" in out
        assert "## Hidden Section {#hidden-section}" in out

    def test_manual_toc_targets_unique_generated_heading_ids(self, tmp_path):
        a = Chapter(
            title="A",
            slug="a",
            source_files=[_write(tmp_path / "a.md", "# A\n## Levels\n")],
        )
        b = Chapter(
            title="B",
            slug="b",
            source_files=[_write(tmp_path / "b.md", "# B\n## Levels\n")],
        )
        out = assembly.assemble_combined_book_markdown([a, b], include_toc=True)
        assert "- [Levels](#levels)" in out
        assert "- [Levels](#levels-1)" in out
        assert "## Levels {#levels}" in out
        assert "## Levels {#levels-1}" in out

    def test_manual_toc_uses_clean_original_heading_ids(self, tmp_path):
        ch = Chapter(
            title="Original - Spell Lists",
            slug="original-spell-lists",
            source_files=[
                _write(
                    tmp_path / "spells.md",
                    "# Original - Spell Lists\n## Original - Chaos Magic Table\n",
                )
            ],
        )
        out = assembly.assemble_combined_book_markdown([ch], include_toc=True)
        assert "## Original - Chaos Magic Table {#original-chaos-magic-table}" in out
        assert "original---chaos-magic-table" not in out

    def test_manual_toc_reserves_explicit_divider_ids(self, tmp_path):
        setting = Chapter(
            title="Setting Primer",
            slug="setting-primer",
            source_files=[
                _write(tmp_path / "setting.md", "# Setting Primer\n## Languages\n")
            ],
        )
        languages = Chapter(
            title="Languages",
            slug="languages",
            source_files=[_write(tmp_path / "languages.md", "# Languages\nbody\n")],
        )
        out = assembly.assemble_combined_book_markdown(
            [setting, languages],
            include_toc=True,
        )
        assert "## Languages {#languages-1}" in out
        assert "# Languages {.section-divider-title #languages}" in out
        assert "- [Languages](#languages-1)" in out
        assert "- [Languages](#languages)" in out
