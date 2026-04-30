"""Project scaffolding for ``papercrown init``."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class InitError(ValueError):
    """Raised when a project scaffold cannot be created safely."""


class StarterBookType(StrEnum):
    """Starter content shapes for new Paper Crown books."""

    CAMPAIGN = "campaign"
    RULES = "rules"
    REFERENCE = "reference"


@dataclass(frozen=True)
class InitResult:
    """Files and directories created by project initialization."""

    root: Path
    created: list[Path]
    next_steps: list[str]


@dataclass(frozen=True)
class _StarterFile:
    """One starter vault file."""

    path: str
    content: str


@dataclass(frozen=True)
class _StarterChapter:
    """One starter recipe chapter."""

    title: str
    slug: str
    sources: list[str]


# Fallback book title used when init is not given a title.
DEFAULT_TITLE = "My Paper Crown Book"
# Starter subtitle text keyed by scaffold type.
DEFAULT_SUBTITLES = {
    StarterBookType.CAMPAIGN: "A campaign book scaffold",
    StarterBookType.RULES: "A rules book scaffold",
    StarterBookType.REFERENCE: "A reference book scaffold",
}


def init_project(
    root: Path,
    *,
    title: str | None = None,
    subtitle: str | None = None,
    theme: str = "clean-srd",
    book_type: StarterBookType | str = StarterBookType.CAMPAIGN,
    vault: Path | None = None,
    with_cover: bool = True,
    empty: bool = False,
    force: bool = False,
) -> InitResult:
    """Create a Paper Crown project scaffold under ``root``."""
    target = root.resolve()
    if target.exists() and any(target.iterdir()) and not force:
        raise InitError(f"destination already exists and is not empty: {target}")

    files: dict[str | Path, str]
    if empty:
        files = _empty_files()
        next_steps = [
            "Create book.yaml or set default_book in papercrown.yaml.",
            "Run papercrown manifest after adding a book.",
        ]
    else:
        book_type_enum = _coerce_book_type(book_type)
        clean_title = _clean_title(title)
        files = _starter_files(
            target,
            title=clean_title,
            subtitle=subtitle or DEFAULT_SUBTITLES[book_type_enum],
            theme=theme,
            book_type=book_type_enum,
            vault=vault,
            with_cover=with_cover,
        )
        next_steps = [
            "Run papercrown manifest.",
            "Run papercrown build --scope book --profile draft.",
        ]

    created: list[Path] = []
    for destination, content in files.items():
        raw_path = Path(destination)
        path = raw_path if raw_path.is_absolute() else target / raw_path
        if path.exists() and not force:
            raise InitError(f"refusing to overwrite existing file: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        created.append(path)
    return InitResult(root=target, created=created, next_steps=next_steps)


def _empty_files() -> dict[str | Path, str]:
    return {
        "papercrown.yaml": """# Empty Paper Crown project.
# Create a book file, then uncomment and update default_book.
# default_book: book.yaml

build:
  target: pdf
  scope: book
  profile: print
""",
        "Art/.gitkeep": "",
        "themes/.gitkeep": "",
    }


def _starter_files(
    target: Path,
    *,
    title: str,
    subtitle: str,
    theme: str,
    book_type: StarterBookType,
    vault: Path | None,
    with_cover: bool,
) -> dict[str | Path, str]:
    if not theme.strip():
        raise InitError("--theme cannot be empty")

    recipe_rel = "book.yaml"
    recipe_path = target / recipe_rel
    uses_project_root_vault = vault is None
    vault_path = target if uses_project_root_vault else _resolve_scaffold_vault(
        target,
        vault,
    )
    vault_ref = None
    if not uses_project_root_vault:
        vault_ref = _recipe_path_ref(
            vault_path,
            recipe_path.parent,
            project_root=target,
        )
    files, chapters = _starter_content(book_type, title=title)

    scaffold: dict[str | Path, str] = {
        "papercrown.yaml": f"""default_book: {recipe_rel}

build:
  target: pdf
  scope: book
  profile: print
  jobs: auto
  pagination: report
""",
        recipe_rel: _render_recipe(
            title=title,
            subtitle=subtitle,
            theme=theme.strip(),
            vault_ref=vault_ref,
            contents=chapters,
            with_cover=with_cover,
        ),
        "Art/.gitkeep": "",
        "themes/.gitkeep": "",
    }
    for starter_file in files:
        scaffold[_scaffold_path_key(target, vault_path / starter_file.path)] = (
            starter_file.content
        )
    return scaffold


def _starter_content(
    book_type: StarterBookType,
    *,
    title: str,
) -> tuple[list[_StarterFile], list[_StarterChapter]]:
    if book_type is StarterBookType.RULES:
        return (
            [
                _StarterFile(
                    "Core Rules.md",
                    f"""# Core Rules

Start writing the core loop for {title}. Keep the first page focused on what
players do, what they roll, and what changes after each roll.
""",
                ),
                _StarterFile(
                    "Character Options.md",
                    """# Character Options

Sketch the choices players make before play starts.

| Option | Why It Matters |
| --- | --- |
| Background | Connects a character to the setting |
| Role | Tells the table how this character helps |
""",
                ),
                _StarterFile(
                    "Quick Reference.md",
                    """# Quick Reference

- Name the roll.
- Set the stakes.
- Resolve the result.
""",
                ),
            ],
            [
                _StarterChapter(
                    "Playing the Game",
                    "playing-the-game",
                    ["Core Rules.md", "Character Options.md"],
                ),
                _StarterChapter(
                    "Quick Reference",
                    "quick-reference",
                    ["Quick Reference.md"],
                ),
            ],
        )

    if book_type is StarterBookType.REFERENCE:
        return (
            [
                _StarterFile(
                    "Introduction.md",
                    f"""# Introduction

Use this opening page to explain what {title} catalogs and how readers should
use it at the table.
""",
                ),
                _StarterFile(
                    "Entries/Sample Entry.md",
                    """# Sample Entry

**Use:** Replace this with a real entry.

**Details:** Add procedures, facts, tables, or cross-references here.
""",
                ),
                _StarterFile(
                    "Quick Reference.md",
                    """# Quick Reference

| Need | Page |
| --- | --- |
| First answer | Sample Entry |
""",
                ),
            ],
            [
                _StarterChapter("Introduction", "introduction", ["Introduction.md"]),
                _StarterChapter(
                    "Reference Entries",
                    "reference-entries",
                    ["Entries/Sample Entry.md"],
                ),
                _StarterChapter(
                    "Quick Reference",
                    "quick-reference",
                    ["Quick Reference.md"],
                ),
            ],
        )

    return (
        [
            _StarterFile(
                "Overview.md",
                f"""# Overview

Write the table promise for {title}: what the characters want, what pressure
pushes back, and what makes this campaign worth opening.
""",
            ),
            _StarterFile(
                "Campaign/First Session.md",
                """# First Session

Frame the first scene, name the immediate trouble, and list three clues or
prompts the group can act on.
""",
            ),
            _StarterFile(
                "Campaign/Factions.md",
                """# Factions

| Faction | Wants | First Move |
| --- | --- | --- |
| Example Faction | A concrete advantage | Make an offer |
""",
            ),
        ],
        [
            _StarterChapter("Overview", "overview", ["Overview.md"]),
            _StarterChapter(
                "Running the Campaign",
                "running-the-campaign",
                ["Campaign/First Session.md", "Campaign/Factions.md"],
            ),
        ],
    )


def _render_recipe(
    *,
    title: str,
    subtitle: str,
    theme: str,
    vault_ref: str | None,
    contents: list[_StarterChapter],
    with_cover: bool,
) -> str:
    optional_blocks: list[str] = []
    if not with_cover:
        optional_blocks.append("cover:\n  enabled: false\n")
    if vault_ref is not None:
        optional_blocks.append(f"vaults:\n  content: {_yaml_string(vault_ref)}\n")
    optional_yaml = "\n".join(optional_blocks)
    if optional_yaml:
        optional_yaml += "\n"

    source_prefix = "content:" if vault_ref is not None else ""
    return f"""theme: {_yaml_string(theme)}

{optional_yaml}contents:
  - kind: inline
    style: title
    title: {_yaml_string(title)}
    subtitle: {_yaml_string(subtitle)}
  - kind: toc
{_render_chapters(contents, source_prefix=source_prefix)}"""


def _render_chapters(chapters: list[_StarterChapter], *, source_prefix: str) -> str:
    rendered: list[str] = []
    for chapter in chapters:
        if len(chapter.sources) == 1:
            rendered.append(
                "\n".join(
                    [
                        "  - kind: file",
                        f"    title: {_yaml_string(chapter.title)}",
                        f"    slug: {_yaml_string(chapter.slug)}",
                        "    source: "
                        f"{_yaml_string(source_prefix + chapter.sources[0])}",
                    ]
                )
            )
            continue
        rendered.append(
            "\n".join(
                [
                    "  - kind: sequence",
                    f"    title: {_yaml_string(chapter.title)}",
                    f"    slug: {_yaml_string(chapter.slug)}",
                    "    sources:",
                    *[
                        f"      - {_yaml_string(source_prefix + source)}"
                        for source in chapter.sources
                    ],
                ]
            )
        )
    return "\n".join(rendered) + "\n"


def _resolve_scaffold_vault(root: Path, vault: Path | None) -> Path:
    if vault is None:
        return root / "vault"
    return vault.resolve() if vault.is_absolute() else (root / vault).resolve()


def _recipe_path_ref(path: Path, recipe_dir: Path, *, project_root: Path) -> str:
    if not _path_is_under(path.resolve(), project_root.resolve()):
        return path.resolve().as_posix()
    try:
        relative = os.path.relpath(path.resolve(), recipe_dir.resolve())
    except ValueError:
        return path.resolve().as_posix()
    return Path(relative).as_posix()


def _scaffold_path_key(root: Path, path: Path) -> str | Path:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.resolve()


def _path_is_under(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _coerce_book_type(book_type: StarterBookType | str) -> StarterBookType:
    if isinstance(book_type, StarterBookType):
        return book_type
    try:
        return StarterBookType(str(book_type))
    except ValueError as error:
        choices = ", ".join(item.value for item in StarterBookType)
        raise InitError(f"--book-type must be one of: {choices}") from error


def _clean_title(title: str | None) -> str:
    clean = (title or DEFAULT_TITLE).strip()
    if not clean:
        raise InitError("--title cannot be empty")
    return clean


def _yaml_string(value: str) -> str:
    return json.dumps(value)
