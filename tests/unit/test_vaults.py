"""Unit tests for VaultIndex and WikilinkTarget."""

from __future__ import annotations

import pytest

from papercrown.vaults import VaultIndex, WikilinkTarget

# ---------------------------------------------------------------------------
# WikilinkTarget.parse
# ---------------------------------------------------------------------------


class TestWikilinkTargetParse:
    def test_bare_stem(self):
        t = WikilinkTarget.parse("Goblin")
        assert t.path_or_stem == "Goblin"
        assert t.alias is None
        assert t.heading is None
        assert t.block_id is None
        assert t.is_path_qualified is False
        assert t.display_text == "Goblin"

    def test_alias(self):
        t = WikilinkTarget.parse("Goblin|Greenie")
        assert t.path_or_stem == "Goblin"
        assert t.alias == "Greenie"
        assert t.display_text == "Greenie"

    def test_path_qualified(self):
        t = WikilinkTarget.parse("Heroes/Ancestries/Goblin")
        assert t.path_or_stem == "Heroes/Ancestries/Goblin"
        assert t.alias is None
        assert t.is_path_qualified is True
        assert t.display_text == "Goblin"

    def test_path_qualified_with_alias(self):
        t = WikilinkTarget.parse("Heroes/Ancestries/Goblin|Goblin")
        assert t.path_or_stem == "Heroes/Ancestries/Goblin"
        assert t.alias == "Goblin"
        assert t.is_path_qualified is True

    def test_heading_anchor(self):
        t = WikilinkTarget.parse("Spell List#Fire Spells")
        assert t.path_or_stem == "Spell List"
        assert t.heading == "Fire Spells"
        assert t.block_id is None

    def test_block_anchor(self):
        t = WikilinkTarget.parse("Note#^abc123")
        assert t.path_or_stem == "Note"
        assert t.heading is None
        assert t.block_id == "abc123"

    def test_with_brackets(self):
        t = WikilinkTarget.parse("[[Goblin]]")
        assert t.path_or_stem == "Goblin"

    def test_with_brackets_and_alias(self):
        t = WikilinkTarget.parse("[[Heroes/Ancestries/Goblin|Goblin]]")
        assert t.path_or_stem == "Heroes/Ancestries/Goblin"
        assert t.alias == "Goblin"

    def test_normalizes_backslashes(self):
        t = WikilinkTarget.parse("Heroes\\Ancestries\\Goblin")
        assert t.path_or_stem == "Heroes/Ancestries/Goblin"

    def test_self_link(self):
        t = WikilinkTarget.parse("#Section")
        assert t.path_or_stem == ""
        assert t.heading == "Section"


# ---------------------------------------------------------------------------
# VaultIndex resolution
# ---------------------------------------------------------------------------


@pytest.fixture
def two_vault_setup(tmp_path):
    """Build a base vault and an overlay vault with overlapping content."""
    base = tmp_path / "base"
    over = tmp_path / "overlay"

    # base: classes + spells
    (base / "Heroes" / "Classes" / "Mage").mkdir(parents=True)
    (base / "Heroes" / "Classes" / "Mage" / "Mage Description.md").write_text(
        "# Mage (base)", encoding="utf-8"
    )
    (base / "Heroes" / "Classes" / "Mage" / "Mage Levels.md").write_text(
        "# Levels (base)", encoding="utf-8"
    )
    (base / "Heroes" / "Ancestries").mkdir(parents=True)
    (base / "Heroes" / "Ancestries" / "Goblin.md").write_text(
        "# Goblin (base)", encoding="utf-8"
    )
    (base / "Magic" / "Spells").mkdir(parents=True)
    (base / "Magic" / "Spells" / "Fireball.md").write_text(
        "# Fireball (base)", encoding="utf-8"
    )
    # Two notes with the same stem at different depths -- shallower should win
    (base / "Notes").mkdir()
    (base / "Notes" / "Common.md").write_text("shallow", encoding="utf-8")
    (base / "Notes" / "deep" / "subdir").mkdir(parents=True)
    (base / "Notes" / "deep" / "subdir" / "Common.md").write_text(
        "deep", encoding="utf-8"
    )

    # overlay: only overrides Mage Description and adds a new file
    (over / "Heroes" / "Classes" / "Mage").mkdir(parents=True)
    (over / "Heroes" / "Classes" / "Mage" / "Mage Description.md").write_text(
        "# Mage (overlay reskin)", encoding="utf-8"
    )
    (over / "OverlayOnly.md").write_text("only here", encoding="utf-8")

    return base, over


class TestVaultIndexResolve:
    def test_resolve_bare_stem(self, two_vault_setup):
        base, _ = two_vault_setup
        idx = VaultIndex.from_recipe_paths([("base", base)])
        hit = idx.resolve("Mage Levels")
        assert hit is not None
        assert hit.name == "Mage Levels.md"

    def test_resolve_path_qualified(self, two_vault_setup):
        base, _ = two_vault_setup
        idx = VaultIndex.from_recipe_paths([("base", base)])
        target = WikilinkTarget.parse("Heroes/Ancestries/Goblin")
        hit = idx.resolve(target)
        assert hit is not None
        assert hit == base / "Heroes" / "Ancestries" / "Goblin.md"

    def test_resolve_path_qualified_with_alias(self, two_vault_setup):
        base, _ = two_vault_setup
        idx = VaultIndex.from_recipe_paths([("base", base)])
        target = WikilinkTarget.parse("Heroes/Ancestries/Goblin|Goblin")
        hit = idx.resolve(target)
        assert hit is not None
        assert hit.name == "Goblin.md"

    def test_overlay_priority_later_wins(self, two_vault_setup):
        base, over = two_vault_setup
        # Priority order: base first (lowest), overlay second (wins)
        idx = VaultIndex.from_recipe_paths([("base", base), ("overlay", over)])
        hit = idx.resolve("Mage Description")
        assert hit is not None
        assert hit.parent.parent.parent.parent == over

    def test_overlay_falls_through_when_only_in_base(self, two_vault_setup):
        base, over = two_vault_setup
        idx = VaultIndex.from_recipe_paths([("base", base), ("overlay", over)])
        hit = idx.resolve("Mage Levels")
        assert hit is not None
        assert hit.parent.parent.parent.parent == base

    def test_prefer_vault_hint(self, two_vault_setup):
        base, over = two_vault_setup
        idx = VaultIndex.from_recipe_paths([("base", base), ("overlay", over)])
        # prefer_vault forces base even though overlay has it too
        hit = idx.resolve("Mage Description", prefer_vault="base")
        assert hit is not None
        assert hit.parent.parent.parent.parent == base

    def test_prefer_vault_falls_through_on_miss(self, two_vault_setup):
        base, over = two_vault_setup
        idx = VaultIndex.from_recipe_paths([("base", base), ("overlay", over)])
        # OverlayOnly doesn't exist in base; falls through to overlay
        hit = idx.resolve("OverlayOnly", prefer_vault="base")
        assert hit is not None
        assert hit.parent == over

    def test_missing_resolves_to_none(self, two_vault_setup):
        base, _ = two_vault_setup
        idx = VaultIndex.from_recipe_paths([("base", base)])
        assert idx.resolve("Nonexistent") is None

    def test_self_link_resolves_to_none(self, two_vault_setup):
        base, _ = two_vault_setup
        idx = VaultIndex.from_recipe_paths([("base", base)])
        assert idx.resolve("#OnlyHeading") is None

    def test_string_argument_is_parsed(self, two_vault_setup):
        base, _ = two_vault_setup
        idx = VaultIndex.from_recipe_paths([("base", base)])
        # Pass a string with alias and brackets
        hit = idx.resolve("[[Heroes/Ancestries/Goblin|Goblin]]")
        assert hit is not None

    def test_duplicate_stem_shallower_wins(self, two_vault_setup):
        base, _ = two_vault_setup
        idx = VaultIndex.from_recipe_paths([("base", base)])
        hit = idx.resolve("Common")
        assert hit is not None
        assert hit == base / "Notes" / "Common.md"
        assert hit.read_text(encoding="utf-8") == "shallow"

    def test_path_qualified_falls_back_to_stem_lookup(self, two_vault_setup):
        base, _ = two_vault_setup
        idx = VaultIndex.from_recipe_paths([("base", base)])
        # Path doesn't actually exist, but stem 'Goblin' does
        target = WikilinkTarget.parse("Wrong/Path/Goblin")
        hit = idx.resolve(target)
        assert hit is not None
        assert hit.name == "Goblin.md"


class TestVaultIndexAccessors:
    def test_vault_by_name(self, two_vault_setup):
        base, over = two_vault_setup
        idx = VaultIndex.from_recipe_paths([("base", base), ("overlay", over)])
        assert idx.vault_by_name("base").root == base.resolve()
        assert idx.vault_by_name("overlay").root == over.resolve()
        assert idx.vault_by_name("ghost") is None
