"""Unit tests for recipe loading."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from papercrown.project.manifest import build_manifest
from papercrown.project.recipe import (
    CONTENT_ITEM_KINDS,
    BookConfigError,
    ContentItemSpec,
    SourceRef,
    load_book_config,
)

FIXTURES_DIR = Path(__file__).parents[2] / "fixtures"

# ---------------------------------------------------------------------------
# SourceRef
# ---------------------------------------------------------------------------


class TestSourceRef:
    def test_with_vault_prefix(self):
        s = SourceRef.parse("custom:Heroes/Foo.md")
        assert s.vault == "custom"
        assert s.path == "Heroes/Foo.md"

    def test_without_vault_prefix(self):
        s = SourceRef.parse("Heroes/Foo.md")
        assert s.vault is None
        assert s.path == "Heroes/Foo.md"

    def test_normalizes_backslashes(self):
        s = SourceRef.parse("custom:Heroes\\Foo.md")
        assert s.path == "Heroes/Foo.md"

    def test_strips_leading_slash(self):
        s = SourceRef.parse("custom:/Heroes/Foo.md")
        assert s.path == "Heroes/Foo.md"

    def test_empty_raises(self):
        with pytest.raises(BookConfigError, match="empty"):
            SourceRef.parse("")
        with pytest.raises(BookConfigError, match="empty"):
            SourceRef.parse("   ")

    def test_str_roundtrip(self):
        assert str(SourceRef.parse("custom:Foo.md")) == "custom:Foo.md"
        assert str(SourceRef.parse("Foo.md")) == "Foo.md"


# ---------------------------------------------------------------------------
# ContentItemSpec
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected_kind"),
    [
        ({"source": "v:Intro.md"}, "file"),
        ({"sources": ["v:Intro.md"]}, "sequence"),
        ({"children": [{"source": "v:Intro.md"}]}, "group"),
        ({"type": "appendix-index"}, "generated"),
    ],
)
def test_chapter_spec_infers_kind_by_shape(raw, expected_kind):
    chapter = ContentItemSpec.from_dict(raw, index=0)

    assert chapter.kind == expected_kind


def test_chapter_spec_splits_divider_art_from_insert_art():
    chapter = ContentItemSpec.from_dict(
        {
            "source": "v:Intro.md",
            "art": [
                {
                    "role": "splash",
                    "art": "splashes/intro.png",
                    "after_heading": "Opening",
                }
            ],
        },
        index=0,
    )
    divider = ContentItemSpec.from_dict(
        {
            "source": "v:Divider.md",
            "art": "dividers/intro.png",
        },
        index=1,
    )

    assert chapter.art is None
    assert chapter.art_inserts[0].target == "after-heading"
    assert chapter.art_inserts[0].heading == "Opening"
    assert divider.art == "dividers/intro.png"
    assert divider.art_inserts == []


# ---------------------------------------------------------------------------
# Helpers for building recipes on the fly
# ---------------------------------------------------------------------------


def _write_recipe(
    tmp_path: Path, body: str, *, vault_dirs: list[str] = ("vault",)
) -> Path:
    """Write a recipe yaml into tmp_path along with the required vault dirs."""
    for v in vault_dirs:
        (tmp_path / v).mkdir(exist_ok=True)
    p = tmp_path / "recipe.yaml"
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# load_book_config: happy path
# ---------------------------------------------------------------------------


class TestLoadBookConfigHappy:
    def test_convention_first_book_uses_top_level_identity(self, tmp_path):
        p = _write_recipe(
            tmp_path,
            """
            title: Nimble Space Opera
            subtitle: Rules Book
            cover_eyebrow: Player's Handbook
            theme: clean-srd
            cover:
              enabled: true
            contents:
              - Intro.md
        """,
            vault_dirs=(),
        )
        r = load_book_config(p)
        assert r.title == "Nimble Space Opera"
        assert r.subtitle == "Rules Book"
        assert r.cover_eyebrow == "Player's Handbook"
        assert r.output_dir == tmp_path.resolve()
        assert r.generated_name == "nimble-space-opera"
        assert r.art_dir == (tmp_path / "Art").resolve()
        assert r.vault_overlay == ["content"]
        assert r.vaults["content"].path == tmp_path.resolve()
        assert r.cover.enabled is True
        assert [item.kind for item in r.contents] == ["file"]

    def test_minimal_convention_fixture_is_verifiable(self):
        r = load_book_config(FIXTURES_DIR / "convention_minimal" / "book.yml")
        m = build_manifest(r)

        assert r.title == "Minimal Convention Book"
        assert r.generated_name == "minimal-convention-book"
        assert r.vault_overlay == ["content"]
        assert [chapter.title for chapter in m.chapters] == ["Intro", "Rules"]

    def test_minimal_recipe(self, tmp_path):
        p = _write_recipe(
            tmp_path,
            """
            title: My Book
            vaults:
              custom: vault
            contents:
              - kind: file
                source: custom:Foo.md
        """,
        )
        r = load_book_config(p)
        assert r.title == "My Book"
        assert r.subtitle is None
        assert "custom" in r.vaults
        assert r.vaults["custom"].path == (tmp_path / "vault").resolve()
        assert r.vault_overlay == ["custom"]
        assert len(r.contents) == 1
        assert r.contents[0].kind == "file"
        assert r.contents[0].source.path == "Foo.md"

    def test_full_recipe(self, tmp_path):
        p = _write_recipe(
            tmp_path,
            """
            title: My Book
            subtitle: Sub
            cover_eyebrow: Eyebrow
            cover_footer: Footer
            vaults:
              base: vault_a
              over: vault_b
            vault_overlay: [base, over]
            output_dir: build
            output_name: my-book
            art_dir: art
            ornaments:
              folio_frame: ornaments/folio.png
              corner_bracket: ornaments/corner.png
            splashes:
              - id: opening
                art: splashes/opening.png
                target: front-cover
                placement: cover
              - id: setting-corner
                art: splashes/setting.png
                chapter: Setting
                target: after-heading
                heading: Factions
                placement: corner-right
            fillers:
              enabled: true
              art_dir: fillers
              slots:
                chapter-end:
                  min_space: 0.65in
                  max_space: 3.5in
                  shapes: [tailpiece, spot, small-wide]
                section-end:
                  min_space: 0.65in
                  max_space: 2.25in
                  shapes: [tailpiece]
              assets:
                - id: tailpiece-airlock
                  art: ornaments/tail.png
                  shape: tailpiece
                  height: 0.65in
            page_damage:
              enabled: true
              art_dir: page-wear
              seed: wear-test-v1
              density: 0.4
              max_assets_per_page: 3
              opacity: 0.22
              glaze_opacity: 0.45
              glaze_texture: surface-dust-speckle.png
              skip: [cover, divider]
            image_treatments:
              ornament: ink-blend
              filler: raw
              cover: print-punch
            cover:
              enabled: true
              art: cover.png
            contents:
              - kind: file
                style: setting
                title: Setting
                slug: custom-setting
                eyebrow: Setting Primer
                art: setting.png
                headpiece: ornaments/head.png
                break_ornament: ornaments/break.png
                tailpiece: ornaments/tail.png
                source: base:Setting.md
                full_page_sections:
                  - Character Creation
                toc_depth: 2
              - kind: classes-catalog
                source: over:Heroes/Classes List.md
                wrapper: false
                child_style: class
                individual_pdfs: true
                individual_pdf_subdir: classes
                art_per_class: true
                class_art_pattern: classes/dividers/class-{slug}.png
                class_spot_art_pattern: class-spots/spot-class-{slug}.png
                replace_existing_opening_art: true
            """,
            vault_dirs=["vault_a", "vault_b", "art"],
        )
        r = load_book_config(p)
        assert r.subtitle == "Sub"
        assert r.cover_eyebrow == "Eyebrow"
        assert r.cover_footer == "Footer"
        assert r.output_dir == (tmp_path / "build").resolve()
        assert r.output_name == "my-book"
        assert r.cover.enabled is True
        assert r.cover.art == "cover.png"
        assert r.art_dir == (tmp_path / "art").resolve()
        assert r.ornaments.folio_frame == "ornaments/folio.png"
        assert r.ornaments.corner_bracket == "ornaments/corner.png"
        assert len(r.splashes) == 2
        assert r.splashes[0].id == "opening"
        assert r.splashes[0].target == "front-cover"
        assert r.splashes[1].chapter == "Setting"
        assert r.splashes[1].heading == "Factions"
        assert r.fillers.enabled is True
        assert r.fillers.art_dir == "fillers"
        assert r.fillers.slots["chapter-end"].min_space_in == 0.65
        assert r.fillers.slots["chapter-end"].shapes == [
            "tailpiece",
            "spot",
            "small-wide",
        ]
        assert r.fillers.slots["section-end"].max_space_in == 2.25
        assert r.fillers.slots["section-end"].shapes == ["tailpiece"]
        assert r.fillers.assets[0].id == "tailpiece-airlock"
        assert r.fillers.assets[0].height_in == 0.65
        assert r.page_damage.enabled is True
        assert r.page_damage.art_dir == "page-wear"
        assert r.page_damage.seed == "wear-test-v1"
        assert r.page_damage.density == 0.4
        assert r.page_damage.max_assets_per_page == 3
        assert r.page_damage.opacity == 0.22
        assert r.page_damage.glaze_opacity == 0.45
        assert r.page_damage.glaze_texture == "surface-dust-speckle.png"
        assert r.page_damage.skip == ["cover", "divider"]
        assert r.image_treatments == {
            "ornament": "ink-blend",
            "filler": "raw",
            "cover": "print-punch",
        }
        assert r.vault_overlay == ["base", "over"]
        assert r.contents[0].slug == "custom-setting"
        assert r.contents[0].headpiece == "ornaments/head.png"
        assert r.contents[0].break_ornament == "ornaments/break.png"
        assert r.contents[0].tailpiece == "ornaments/tail.png"
        assert r.contents[0].full_page_sections == ["Character Creation"]
        assert r.contents[0].toc_depth == 2
        ch = r.contents[1]
        assert ch.kind == "classes-catalog"
        assert ch.individual_pdfs is True
        assert ch.individual_pdf_subdir == "classes"
        assert ch.art_per_class is True
        assert ch.class_art_pattern == "classes/dividers/class-{slug}.png"
        assert ch.class_spot_art_pattern == "class-spots/spot-class-{slug}.png"
        assert ch.replace_existing_opening_art is True
        assert ch.child_style == "class"

    def test_sequence_recipe_parses_ordered_sources(self, tmp_path):
        p = _write_recipe(
            tmp_path,
            """
            title: My Book
            vaults:
              custom: vault
            contents:
              - kind: sequence
                title: Combat
                source: custom:Combat.md
        """,
        )
        with pytest.raises(BookConfigError, match="source"):
            load_book_config(p)

        p = _write_recipe(
            tmp_path,
            """
            title: My Book
            vaults:
              custom: vault
            contents:
              - kind: sequence
                title: Combat
                sources:
                  - custom:Combat Intro.md
                  - title: Combat Structure
                    source: custom:Combat Structure.md
                    strip_related: true
        """,
        )
        r = load_book_config(p)
        ch = r.contents[0]
        assert ch.kind == "sequence"
        assert [str(item.source) for item in ch.sources] == [
            "custom:Combat Intro.md",
            "custom:Combat Structure.md",
        ]
        assert ch.sources[0].title is None
        assert ch.sources[1].title == "Combat Structure"
        assert ch.sources[1].strip_related is True

    def test_extends_deep_merges_recipe_layers(self, tmp_path):
        base_dir = tmp_path / "base"
        child_dir = tmp_path / "child"
        (base_dir / "vault").mkdir(parents=True)
        (child_dir / "vault").mkdir(parents=True)
        base = base_dir / "base.yaml"
        base.write_text(
            textwrap.dedent(
                """
                title: Base Book
                subtitle: Base Subtitle
                vaults:
                  base: vault
                output_name: base-book
                cover:
                  enabled: true
                contents:
                  - kind: file
                    title: Base
                    source: base:Base.md
                """
            ).lstrip(),
            encoding="utf-8",
        )
        child = child_dir / "child.yaml"
        child.write_text(
            textwrap.dedent(
                """
                extends: ../base/base.yaml
                title: Child Book
                vaults:
                  child: vault
                contents:
                  - kind: file
                    title: Child
                    source: child:Child.md
                """
            ).lstrip(),
            encoding="utf-8",
        )

        recipe = load_book_config(child)

        assert recipe.title == "Child Book"
        assert recipe.subtitle == "Base Subtitle"
        assert recipe.output_name == "base-book"
        assert recipe.cover.enabled is True
        assert recipe.vaults["base"].path == (base_dir / "vault").resolve()
        assert recipe.vaults["child"].path == (child_dir / "vault").resolve()
        assert [chapter.title for chapter in recipe.contents] == ["Child"]

    def test_include_contents_prepends_reusable_fragments(self, tmp_path):
        (tmp_path / "vault").mkdir()
        include = tmp_path / "chapters.yaml"
        include.write_text(
            textwrap.dedent(
                """
                - kind: file
                  title: Included
                  source: v:Included.md
                """
            ).lstrip(),
            encoding="utf-8",
        )
        recipe_path = _write_recipe(
            tmp_path,
            """
            title: My Book
            include_contents: chapters.yaml
            vaults:
              v: vault
            contents:
              - kind: file
                title: Local
                source: v:Local.md
            """,
        )

        recipe = load_book_config(recipe_path)

        assert [chapter.title for chapter in recipe.contents] == [
            "Included",
            "Local",
        ]

    def test_include_vaults_imports_paths_relative_to_fragment(self, tmp_path):
        shared = tmp_path / "shared"
        recipe_dir = tmp_path / "recipe"
        (shared / "vaults" / "base").mkdir(parents=True)
        (recipe_dir / "custom").mkdir(parents=True)
        vaults = shared / "vaults.yaml"
        vaults.write_text(
            textwrap.dedent(
                """
                vaults:
                  base: vaults/base
                vault_overlay: [base]
                """
            ).lstrip(),
            encoding="utf-8",
        )
        recipe_path = recipe_dir / "recipe.yaml"
        recipe_path.write_text(
            textwrap.dedent(
                """
                title: My Book
                include_vaults: ../shared/vaults.yaml
                vaults:
                  custom: custom
                contents:
                  - kind: file
                    source: custom:Foo.md
                """
            ).lstrip(),
            encoding="utf-8",
        )

        recipe = load_book_config(recipe_path)

        assert recipe.vaults["base"].path == (shared / "vaults" / "base").resolve()
        assert recipe.vaults["custom"].path == (recipe_dir / "custom").resolve()
        assert recipe.vault_overlay == ["base", "custom"]


# ---------------------------------------------------------------------------
# load_book_config: error cases
# ---------------------------------------------------------------------------


class TestLoadBookConfigErrors:
    def test_missing_file(self, tmp_path):
        with pytest.raises(BookConfigError, match="not found"):
            load_book_config(tmp_path / "nope.yaml")

    def test_invalid_yaml(self, tmp_path):
        p = tmp_path / "bad.yaml"
        p.write_text("title: [unterminated\n", encoding="utf-8")
        with pytest.raises(BookConfigError, match="invalid YAML"):
            load_book_config(p)

    def test_empty_recipe(self, tmp_path):
        p = tmp_path / "empty.yaml"
        p.write_text("", encoding="utf-8")
        with pytest.raises(BookConfigError, match="empty"):
            load_book_config(p)

    def test_root_not_mapping(self, tmp_path):
        p = tmp_path / "x.yaml"
        p.write_text("- a\n- b\n", encoding="utf-8")
        with pytest.raises(BookConfigError, match="must be a mapping"):
            load_book_config(p)

    def test_missing_title(self, tmp_path):
        p = _write_recipe(
            tmp_path,
            """
            vaults:
              custom: vault
            contents:
              - kind: file
                source: custom:Foo.md
        """,
        )
        with pytest.raises(BookConfigError, match="title"):
            load_book_config(p)

    def test_missing_vaults(self, tmp_path):
        p = _write_recipe(
            tmp_path,
            """
            title: X
            contents:
              - kind: file
                source: custom:Foo.md
        """,
        )
        with pytest.raises(BookConfigError, match="vaults"):
            load_book_config(p)

    def test_vault_path_does_not_exist(self, tmp_path):
        p = _write_recipe(
            tmp_path,
            """
            title: X
            vaults:
              custom: nonexistent_dir
            contents:
              - kind: file
                source: custom:Foo.md
            """,
            vault_dirs=[],
        )
        with pytest.raises(BookConfigError, match="does not exist"):
            load_book_config(p)

    def test_invalid_vault_name(self, tmp_path):
        p = _write_recipe(
            tmp_path,
            """
            title: X
            vaults:
              "bad name!": vault
            contents:
              - kind: file
                source: vault:Foo.md
            """,
        )
        with pytest.raises(BookConfigError, match="invalid vault alias"):
            load_book_config(p)

    def test_ornaments_must_be_mapping(self, tmp_path):
        p = _write_recipe(
            tmp_path,
            """
            title: X
            vaults:
              custom: vault
            ornaments: ornaments/folio.png
            contents:
              - kind: file
                source: custom:Foo.md
        """,
        )
        with pytest.raises(BookConfigError, match="ornaments"):
            load_book_config(p)

    def test_splashes_must_be_list(self, tmp_path):
        p = _write_recipe(
            tmp_path,
            """
            title: X
            vaults:
              custom: vault
            splashes: splashes/opening.png
            contents:
              - kind: file
                source: custom:Foo.md
        """,
        )
        with pytest.raises(BookConfigError, match="splashes"):
            load_book_config(p)

    def test_image_treatments_validate_roles_and_presets(self, tmp_path):
        p = _write_recipe(
            tmp_path,
            """
            title: X
            vaults:
              custom: vault
            image_treatments:
              filler: none
              ornament: ink-blend
            contents:
              - kind: file
                source: custom:Foo.md
        """,
        )
        recipe = load_book_config(p)
        assert recipe.image_treatments == {
            "filler": "raw",
            "ornament": "ink-blend",
        }

        p = _write_recipe(
            tmp_path,
            """
            title: X
            vaults:
              custom: vault
            image_treatments:
              portraits: raw
            contents:
              - kind: file
                source: custom:Foo.md
        """,
        )
        with pytest.raises(BookConfigError, match="role"):
            load_book_config(p)

        p = _write_recipe(
            tmp_path,
            """
            title: X
            vaults:
              custom: vault
            image_treatments:
              filler: sharpen
            contents:
              - kind: file
                source: custom:Foo.md
        """,
        )
        with pytest.raises(BookConfigError, match="preset"):
            load_book_config(p)

    def test_splash_target_and_placement_are_validated(self, tmp_path):
        p = _write_recipe(
            tmp_path,
            """
            title: X
            vaults:
              custom: vault
            splashes:
              - id: bad
                art: splashes/bad.png
                target: chapter-start
                placement: cover
            contents:
              - kind: file
                source: custom:Foo.md
        """,
        )
        with pytest.raises(BookConfigError, match="chapter"):
            load_book_config(p)

        p = _write_recipe(
            tmp_path,
            """
            title: X
            vaults:
              custom: vault
            splashes:
              - id: bad
                art: splashes/bad.png
                target: front-cover
                placement: sideways
            contents:
              - kind: file
                source: custom:Foo.md
        """,
        )
        with pytest.raises(BookConfigError, match="placement"):
            load_book_config(p)

    def test_fillers_validate_shapes_and_lengths(self, tmp_path):
        p = _write_recipe(
            tmp_path,
            """
            title: X
            vaults:
              custom: vault
            fillers:
              enabled: true
              slots:
                chapter-end:
                  min_space: 0.65in
                  max_space: 3.5in
                  shapes: [sideways]
            contents:
              - kind: file
                source: custom:Foo.md
        """,
        )
        with pytest.raises(BookConfigError, match="shape"):
            load_book_config(p)

        p = _write_recipe(
            tmp_path,
            """
            title: X
            vaults:
              custom: vault
            fillers:
              enabled: true
              slots:
                chapter-end:
                  min_space: 0
                  max_space: 3.5in
                  shapes: [tailpiece]
              assets:
                - id: bad
                  art: ornaments/bad.png
                  shape: tailpiece
                  height: lots
            contents:
              - kind: file
                source: custom:Foo.md
        """,
        )
        with pytest.raises(BookConfigError, match="inch"):
            load_book_config(p)

    def test_page_damage_validates_mapping_ranges_and_skip_targets(self, tmp_path):
        p = _write_recipe(
            tmp_path,
            """
            title: X
            vaults:
              custom: vault
            page_damage: yes
            contents:
              - kind: file
                source: custom:Foo.md
        """,
        )
        with pytest.raises(BookConfigError, match="page_damage"):
            load_book_config(p)

        p = _write_recipe(
            tmp_path,
            """
            title: X
            vaults:
              custom: vault
            page_damage:
              enabled: true
              density: 1.4
            contents:
              - kind: file
                source: custom:Foo.md
        """,
        )
        with pytest.raises(BookConfigError, match="density"):
            load_book_config(p)

        p = _write_recipe(
            tmp_path,
            """
            title: X
            vaults:
              custom: vault
            page_damage:
              enabled: true
              glaze_opacity: 1.4
            contents:
              - kind: file
                source: custom:Foo.md
        """,
        )
        with pytest.raises(BookConfigError, match="glaze_opacity"):
            load_book_config(p)

        p = _write_recipe(
            tmp_path,
            """
            title: X
            vaults:
              custom: vault
            page_damage:
              enabled: true
              skip: [cover, glossary]
            contents:
              - kind: file
                source: custom:Foo.md
        """,
        )
        with pytest.raises(BookConfigError, match="skip"):
            load_book_config(p)

    def test_fillers_parse_marker_policy_and_opt_outs(self, tmp_path):
        p = _write_recipe(
            tmp_path,
            """
            title: X
            vaults:
              custom: vault
            fillers:
              enabled: true
              slots:
                chapter-end:
                  min_space: 0.65in
                  max_space: 5.5in
                  shapes: [tailpiece, plate, page-finish]
              markers:
                terminal:
                  chapter_slots: chapter-end
                  class_slots: false
                source_boundary: false
                subclass: false
                headings:
                  - chapter: Reference
                    slot: chapter-end
                    heading_level: 2
                    slot_kind: reference-section
                    context: reference
            contents:
              - kind: sequence
                title: Reference
                fillers: false
                sources:
                  - source: custom:Foo.md
                    filler: false
        """,
        )

        recipe = load_book_config(p)

        assert recipe.fillers.slots["chapter-end"].shapes == [
            "tailpiece",
            "plate",
            "page-finish",
        ]
        assert recipe.fillers.markers.terminal.class_slots == ()
        assert recipe.fillers.markers.source_boundary.sequence_slots == ()
        assert recipe.fillers.markers.subclass.slots == ()
        assert recipe.fillers.markers.headings[0].slot_kind == "reference-section"
        assert recipe.contents[0].fillers_enabled is False
        assert recipe.contents[0].sources[0].filler_enabled is False

    def test_fillers_parse_multi_slot_marker_policy(self, tmp_path):
        p = _write_recipe(
            tmp_path,
            """
            title: X
            vaults:
              custom: vault
            fillers:
              enabled: true
              slots:
                chapter-end:
                  min_space: 0.65in
                  max_space: 5.5in
                  shapes: [tailpiece]
              markers:
                terminal:
                  chapter_slots: [chapter-end, chapter-bottom-band]
                  class_slots: [class-end, class-bottom-band]
                source_boundary:
                  sequence_slots: [section-end, section-bottom-band]
                subclass:
                  slots: [subclass-end, subclass-bottom-band]
            contents:
              - kind: file
                source: custom:Foo.md
        """,
        )

        recipe = load_book_config(p)

        assert recipe.fillers.markers.terminal.chapter_slots == (
            "chapter-end",
            "chapter-bottom-band",
        )
        assert recipe.fillers.markers.terminal.class_slots == (
            "class-end",
            "class-bottom-band",
        )
        assert recipe.fillers.markers.source_boundary.sequence_slots == (
            "section-end",
            "section-bottom-band",
        )
        assert recipe.fillers.markers.subclass.slots == (
            "subclass-end",
            "subclass-bottom-band",
        )

    def test_missing_contents(self, tmp_path):
        p = _write_recipe(
            tmp_path,
            """
            title: X
            vaults:
              custom: vault
        """,
        )
        with pytest.raises(BookConfigError, match="contents"):
            load_book_config(p)

    @pytest.mark.parametrize(
        ("field", "hint"),
        [
            ("chapters", "use contents instead"),
            ("front_matter", "ordinary contents items"),
            ("back_matter", "ordinary contents items"),
            ("build", "papercrown.yaml"),
            ("include_chapters", "use include_contents instead"),
        ],
    )
    def test_legacy_recipe_fields_fail_clearly(self, tmp_path, field, hint):
        legacy_value = "[]"
        if field == "include_chapters":
            legacy_value = "old-chapters.yaml"
        if field == "build":
            legacy_value = "{scope: book}"
        p = _write_recipe(
            tmp_path,
            f"""
            title: X
            vaults:
              custom: vault
            contents:
              - kind: file
                source: custom:Foo.md
            {field}: {legacy_value}
        """,
        )
        with pytest.raises(BookConfigError, match=hint):
            load_book_config(p)

    def test_empty_contents(self, tmp_path):
        p = _write_recipe(
            tmp_path,
            """
            title: X
            vaults:
              custom: vault
            contents: []
        """,
        )
        with pytest.raises(BookConfigError, match="contents"):
            load_book_config(p)

    def test_unknown_chapter_kind(self, tmp_path):
        p = _write_recipe(
            tmp_path,
            """
            title: X
            vaults:
              custom: vault
            contents:
              - kind: bogus
                source: custom:Foo.md
        """,
        )
        with pytest.raises(BookConfigError, match="kind"):
            load_book_config(p)

    def test_inline_title_content_fails_clearly(self, tmp_path):
        p = _write_recipe(
            tmp_path,
            """
            title: X
            contents:
              - kind: inline
                style: title
                title: Old Title
              - Intro.md
        """,
            vault_dirs=(),
        )

        with pytest.raises(BookConfigError, match="top-level title"):
            load_book_config(p)

    def test_chapter_missing_source(self, tmp_path):
        p = _write_recipe(
            tmp_path,
            """
            title: X
            vaults:
              custom: vault
            contents:
              - kind: file
        """,
        )
        with pytest.raises(BookConfigError, match="source"):
            load_book_config(p)

    def test_chapter_source_unknown_vault(self, tmp_path):
        p = _write_recipe(
            tmp_path,
            """
            title: X
            vaults:
              custom: vault
            contents:
              - kind: file
                source: nimble:Foo.md
        """,
        )
        with pytest.raises(BookConfigError, match="unknown vault"):
            load_book_config(p)

    def test_overlay_unknown_vault(self, tmp_path):
        p = _write_recipe(
            tmp_path,
            """
            title: X
            vaults:
              custom: vault
            vault_overlay: [custom, ghost]
            contents:
              - kind: file
                source: custom:Foo.md
        """,
        )
        with pytest.raises(BookConfigError, match="unknown vault"):
            load_book_config(p)

    def test_sort_field_rejected(self, tmp_path):
        # `sort:` was an unimplemented option that lived in the API surface
        # for a while; it's now an explicit BookConfigError so old recipes
        # can't silently rely on a no-op setting.
        p = _write_recipe(
            tmp_path,
            """
            title: X
            vaults:
              custom: vault
            contents:
              - kind: folder
                source: custom:Foo
                sort: alphabetical
        """,
        )
        with pytest.raises(BookConfigError, match="sort"):
            load_book_config(p)

    def test_full_page_sections_must_be_list(self, tmp_path):
        p = _write_recipe(
            tmp_path,
            """
            title: X
            vaults:
              custom: vault
            contents:
              - kind: file
                source: custom:Foo.md
                full_page_sections: Character Creation
        """,
        )
        with pytest.raises(BookConfigError, match="full_page_sections"):
            load_book_config(p)

    def test_toc_depth_must_be_integer_between_one_and_four(self, tmp_path):
        p = _write_recipe(
            tmp_path,
            """
            title: Test
            vaults:
              base: vault
            contents:
              - kind: file
                source: base:Setting.md
                toc_depth: 0
        """,
        )
        with pytest.raises(BookConfigError, match="toc_depth"):
            load_book_config(p)

        p = _write_recipe(
            tmp_path,
            """
            title: Test
            vaults:
              base: vault
            contents:
              - kind: file
                source: base:Setting.md
                toc_depth: deep
        """,
        )
        with pytest.raises(BookConfigError, match="toc_depth"):
            load_book_config(p)

    def test_sources_only_valid_for_sequence(self, tmp_path):
        p = _write_recipe(
            tmp_path,
            """
            title: X
            vaults:
              custom: vault
            contents:
              - kind: file
                source: custom:Foo.md
                sources:
                  - custom:Bar.md
        """,
        )
        with pytest.raises(BookConfigError, match="sources"):
            load_book_config(p)

    def test_chapter_slug_must_be_anchor_safe(self, tmp_path):
        p = _write_recipe(
            tmp_path,
            """
            title: X
            vaults:
              custom: vault
            contents:
              - kind: file
                source: custom:Foo.md
                slug: "not a safe slug"
        """,
        )
        with pytest.raises(BookConfigError, match="slug"):
            load_book_config(p)

    def test_extends_cycle_is_rejected(self, tmp_path):
        (tmp_path / "vault").mkdir()
        a = tmp_path / "a.yaml"
        b = tmp_path / "b.yaml"
        a.write_text(
            textwrap.dedent(
                """
                extends: b.yaml
                title: A
                vaults:
                  v: vault
                contents:
                  - kind: file
                    source: v:A.md
                """
            ).lstrip(),
            encoding="utf-8",
        )
        b.write_text(
            textwrap.dedent(
                """
                extends: a.yaml
                title: B
                vaults:
                  v: vault
                contents:
                  - kind: file
                    source: v:B.md
                """
            ).lstrip(),
            encoding="utf-8",
        )

        with pytest.raises(BookConfigError, match="cycle"):
            load_book_config(a)


# ---------------------------------------------------------------------------
# Sanity: chapter kinds set is what the rest of the system expects
# ---------------------------------------------------------------------------


def test_chapter_kinds_set_is_canonical():
    assert CONTENT_ITEM_KINDS == {
        "file",
        "catalog",
        "composite",
        "classes-catalog",
        "folder",
        "generated",
        "group",
        "sequence",
        "toc",
    }
