"""Unit tests for catalog format detection and parsing."""

from __future__ import annotations

import textwrap

from papercrown.catalog import detect_format, parse_catalog

# ---------------------------------------------------------------------------
# detect_format
# ---------------------------------------------------------------------------


class TestDetectFormat:
    def test_empty(self):
        assert detect_format("") == "empty"
        assert detect_format("   \n\n   ") == "empty"

    def test_bullet_links_only(self):
        text = textwrap.dedent("""
            # Group
            - [[A]]
            - [[B]]
            - [[C]]
        """)
        assert detect_format(text) == "bullet-links"

    def test_bullet_links_no_heading(self):
        text = "- [[A]]\n- [[B]]\n- [[C]]\n"
        assert detect_format(text) == "bullet-links"

    def test_embed_compendium(self):
        text = textwrap.dedent("""
            # Fire Spells

            ![[Flame Dart]]

            ---

            ![[Heart's Fire]]

            ---

            ![[Inferno]]
        """)
        assert detect_format(text) == "embed-compendium"

    def test_annotated_embeds(self):
        text = textwrap.dedent("""
            Some intro prose.

            ![[Sparkfetch]]

            > [!faq]- Why secret?
            > Story reasons.

            ![[Other Spell]]
        """)
        assert detect_format(text) == "annotated-embeds"

    def test_embed_compendium_with_some_prose_stays_embed(self):
        # A short intro paragraph should not flip to annotated
        text = textwrap.dedent("""
            Brief intro line only.

            ![[A]]

            ---

            ![[B]]
        """)
        # Single body-text line + 2 embeds + 0 callouts -> embed-compendium
        assert detect_format(text) == "embed-compendium"

    def test_mixed_balanced_returns_mixed(self):
        text = "- [[A]]\n- [[B]]\n![[C]]\n![[D]]\n"
        assert detect_format(text) == "mixed"

    def test_dominantly_bullet_with_one_embed(self):
        text = "- [[A]]\n- [[B]]\n- [[C]]\n- [[D]]\n![[X]]\n"
        # bullet=4, embed=1 -> 4 >= 2*1 -> bullet-links wins
        assert detect_format(text) == "bullet-links"

    def test_code_blocks_dont_count(self):
        text = textwrap.dedent("""
            ```
            - [[NotReal]]
            ![[NorThis]]
            ```

            - [[Real]]
        """)
        assert detect_format(text) == "bullet-links"

    def test_horizontal_rules_dont_count(self):
        text = "---\n![[A]]\n---\n![[B]]\n"
        assert detect_format(text) == "embed-compendium"


# ---------------------------------------------------------------------------
# parse_catalog
# ---------------------------------------------------------------------------


class TestParseCatalog:
    def test_grouped_bullet_links(self):
        text = textwrap.dedent("""
            # Artificer
            - [[Artificer Description]]
            - [[Artificer Levels]]
            # Berserker
            - [[Berserker Description]]
            - [[Berserker Levels]]
        """)
        parsed = parse_catalog(text)
        assert parsed.format == "bullet-links"
        assert len(parsed.groups) == 2
        assert parsed.groups[0].name == "Artificer"
        assert parsed.groups[1].name == "Berserker"
        assert len(parsed.groups[0].entries) == 2
        assert (
            parsed.groups[0].entries[0].target.path_or_stem == "Artificer Description"
        )
        assert parsed.groups[0].entries[0].is_embed is False

    def test_ungrouped_embeds(self):
        text = textwrap.dedent("""
            ![[A]]

            ---

            ![[B]]

            ---

            ![[C]]
        """)
        parsed = parse_catalog(text)
        assert parsed.format == "embed-compendium"
        assert len(parsed.groups) == 1
        assert parsed.groups[0].name == ""
        assert [e.target.path_or_stem for e in parsed.groups[0].entries] == [
            "A",
            "B",
            "C",
        ]
        assert all(e.is_embed for e in parsed.groups[0].entries)

    def test_path_qualified_link_preserved(self):
        text = "![[Heroes/Ancestries/Goblin|Goblin]]\n"
        parsed = parse_catalog(text)
        entry = parsed.entries[0]
        assert entry.target.path_or_stem == "Heroes/Ancestries/Goblin"
        assert entry.target.alias == "Goblin"
        assert entry.target.is_path_qualified is True

    def test_intro_text_captured(self):
        text = textwrap.dedent("""
            This is the intro paragraph.

            It has multiple lines.

            # Section
            - [[A]]
        """)
        parsed = parse_catalog(text)
        # First non-empty content lines, before any heading or entry
        assert "intro paragraph" in parsed.intro_text
        assert "multiple lines" in parsed.intro_text

    def test_grouped_embeds(self):
        text = textwrap.dedent("""
            # Fire Spells
            ![[Flame Dart]]
            ![[Heart's Fire]]
            # Ice Spells
            ![[Frost Bolt]]
        """)
        parsed = parse_catalog(text)
        assert parsed.format == "embed-compendium"
        assert [g.name for g in parsed.groups] == ["Fire Spells", "Ice Spells"]
        assert len(parsed.groups[0].entries) == 2
        assert len(parsed.groups[1].entries) == 1

    def test_entries_helper_flattens(self):
        text = "# G1\n- [[A]]\n# G2\n- [[B]]\n- [[C]]\n"
        parsed = parse_catalog(text)
        assert [e.target.path_or_stem for e in parsed.entries] == ["A", "B", "C"]

    def test_group_name_attached_to_entry(self):
        text = "# Group A\n- [[Item]]\n"
        parsed = parse_catalog(text)
        assert parsed.entries[0].group_name == "Group A"

    def test_real_world_classes_list_snippet(self):
        # Mirrors a hand-authored classes index format.
        text = textwrap.dedent("""
            # Berserker
            - [[Berserker Description]]
            - [[Berserker Levels]]
            - [[Savage Arsenal]]
            - [[Path of the Mountainheart]]
            - [[Path of the Red Mist]]
        """)
        parsed = parse_catalog(text)
        assert parsed.format == "bullet-links"
        assert parsed.groups[0].name == "Berserker"
        assert len(parsed.groups[0].entries) == 5

    def test_real_world_ancestries_list_with_embeds_and_paths(self):
        text = textwrap.dedent("""
            ---
            ![[Bunbun]]

            ---

            ![[Heroes/Ancestries/Goblin|Goblin]]
        """)
        parsed = parse_catalog(text)
        assert parsed.format == "embed-compendium"
        assert len(parsed.entries) == 2
        assert parsed.entries[1].target.is_path_qualified
        assert parsed.entries[1].target.alias == "Goblin"
