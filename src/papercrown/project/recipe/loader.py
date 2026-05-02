"""Book YAML loading, includes, and path normalization."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from copy import deepcopy
from pathlib import Path

import yaml

from papercrown.project.recipe.models import (
    DEFAULT_THEME,
    ArtPlacementSpec,
    BookConfig,
    BookConfigError,
    BookMetadataSpec,
    ContentItemSpec,
    CoverSpec,
    FillersSpec,
    OrnamentsSpec,
    PageDamageSpec,
    VaultSpec,
    _filename_slug,
    _image_treatments_mapping,
    _slug_or_none,
    _str_or_none,
    _theme_options_mapping,
)

# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def _resolve_vault_path(raw: str, recipe_dir: Path) -> Path:
    """Resolve a recipe-relative or absolute filesystem path."""
    p = Path(raw)
    if not p.is_absolute():
        p = (recipe_dir / p).resolve()
    else:
        p = p.resolve()
    return p


def load_book_config(
    path: str | Path,
    *,
    defaults: Mapping[str, object] | None = None,
    defaults_base_dir: Path | None = None,
) -> BookConfig:
    """Load and validate a book YAML file.

    Raises BookConfigError with a clear message on any structural or referential
    problem (missing required fields, unknown content kinds, vault paths that
    don't exist, vault_overlay names not in `vaults`, book include cycles,
    etc). Books may use ``extends``, ``include_contents``, and
    ``include_vaults`` to share reusable book structure.
    """
    recipe_path = Path(path).resolve()
    if not recipe_path.is_file():
        raise BookConfigError(f"book config file not found: {recipe_path}")

    raw = _load_book_config_mapping(recipe_path, stack=())
    if defaults:
        defaults_raw = {str(key): value for key, value in deepcopy(defaults).items()}
        _normalize_recipe_filesystem_paths(
            defaults_raw,
            (defaults_base_dir or recipe_path.parent).resolve(),
        )
        raw = _deep_merge(defaults_raw, raw)
    _reject_legacy_recipe_shape(raw)

    contents_raw = _normalize_contents(raw.get("contents"))
    _reject_inline_title_content(contents_raw)
    title, subtitle, cover_eyebrow, cover_footer = _title_fields(raw)

    recipe_dir = recipe_path.parent
    project_dir = _project_dir_for_recipe(recipe_path)

    vaults = _load_vaults(raw, recipe_dir=recipe_dir, project_dir=project_dir)
    vault_overlay = _vault_overlay(raw, vaults)

    art_dir_override = _optional_resolved_path(
        raw,
        "art_dir",
        recipe_dir,
        must_exist=True,
    )
    output_dir_override = _optional_resolved_path(raw, "output_dir", recipe_dir)
    cache_dir_override = _optional_resolved_path(raw, "cache_dir", recipe_dir)
    theme_dir_override = _optional_resolved_path(
        raw,
        "theme_dir",
        recipe_dir,
        must_exist=True,
    )

    output_name = _str_or_none(raw.get("output_name"))
    if output_name is not None:
        output_name = _filename_slug(output_name)

    theme = _slug_or_none(raw.get("theme"), loc="theme") or DEFAULT_THEME

    metadata_raw = raw.get("metadata")
    if metadata_raw is not None and not isinstance(metadata_raw, Mapping):
        raise BookConfigError("metadata must be a mapping when provided")
    theme_options = _theme_options_mapping(raw.get("theme_options"))
    image_treatments = _image_treatments_mapping(raw.get("image_treatments"))
    art_raw = raw.get("art")
    if art_raw is not None and not isinstance(art_raw, Mapping):
        raise BookConfigError("art must be a mapping when provided")

    cover_raw = raw.get("cover")
    if cover_raw is not None and not isinstance(cover_raw, Mapping):
        raise BookConfigError("cover must be a mapping when provided")
    ornaments_raw = raw.get("ornaments")
    if ornaments_raw is not None and not isinstance(ornaments_raw, Mapping):
        raise BookConfigError("ornaments must be a mapping when provided")
    fillers_raw = raw.get("fillers")
    if fillers_raw is not None and not isinstance(fillers_raw, Mapping):
        raise BookConfigError("fillers must be a mapping when provided")
    page_damage_raw = raw.get("page_damage")
    if page_damage_raw is not None and not isinstance(page_damage_raw, Mapping):
        raise BookConfigError("page_damage must be a mapping when provided")
    art_placements = _parse_art_placements(art_raw)
    contents = _parse_contents(contents_raw)
    _validate_chapter_sources(contents, "contents", declared_vaults=set(vaults))

    cover = _cover_spec(cover_raw)

    return BookConfig(
        title=title.strip(),
        subtitle=subtitle,
        cover_eyebrow=cover_eyebrow,
        cover_footer=cover_footer,
        vaults=vaults,
        vault_overlay=vault_overlay,
        output_dir_override=output_dir_override,
        output_name=output_name,
        cache_dir_override=cache_dir_override,
        theme=theme,
        theme_dir_override=theme_dir_override,
        theme_options=theme_options,
        image_treatments=image_treatments,
        metadata=BookMetadataSpec.from_dict(metadata_raw),
        art_dir_override=art_dir_override,
        ornaments=OrnamentsSpec.from_dict(ornaments_raw),
        cover=cover,
        art_placements=art_placements,
        fillers=FillersSpec.from_dict(fillers_raw),
        page_damage=PageDamageSpec.from_dict(page_damage_raw),
        contents=contents,
        recipe_path=recipe_path,
    )


def _title_fields(
    raw: Mapping[str, object],
) -> tuple[str, str | None, str | None, str | None]:
    """Resolve required top-level book title metadata."""
    title = _str_or_none(raw.get("title"))
    if title is None:
        raise BookConfigError("book config missing required top-level title")

    subtitle = _str_or_none(raw.get("subtitle"))
    cover_eyebrow = _str_or_none(raw.get("cover_eyebrow"))
    cover_footer = _str_or_none(raw.get("cover_footer"))
    return title, subtitle, cover_eyebrow, cover_footer


def _load_vaults(
    raw: Mapping[str, object],
    *,
    recipe_dir: Path,
    project_dir: Path,
) -> dict[str, VaultSpec]:
    """Resolve and validate recipe vault declarations."""
    vaults_raw = raw.get("vaults")
    if vaults_raw is None:
        vaults_raw = {"content": str(project_dir)}
    if not isinstance(vaults_raw, Mapping) or not vaults_raw:
        raise BookConfigError("vaults must be a mapping of name -> path when provided")

    vaults: dict[str, VaultSpec] = {}
    for name, vp in vaults_raw.items():
        if not isinstance(name, str) or not re.match(r"^[A-Za-z0-9_-]+$", name):
            raise BookConfigError(
                f"invalid vault alias {name!r}: must be alphanumeric/underscore/dash"
            )
        resolved = _resolve_vault_path(str(vp), recipe_dir)
        if not resolved.is_dir():
            raise BookConfigError(f"vault {name!r} path does not exist: {resolved}")
        vaults[name] = VaultSpec(name=name, path=resolved)
    return vaults


def _vault_overlay(
    raw: Mapping[str, object],
    vaults: Mapping[str, VaultSpec],
) -> list[str]:
    """Return the declared vault overlay order."""
    overlay_raw = raw.get("vault_overlay")
    if overlay_raw is None:
        return list(vaults.keys())
    if not isinstance(overlay_raw, list) or not all(
        isinstance(x, str) for x in overlay_raw
    ):
        raise BookConfigError("vault_overlay must be a list of vault alias strings")
    for name in overlay_raw:
        if name not in vaults:
            raise BookConfigError(
                f"vault_overlay references unknown vault {name!r}; "
                f"declared vaults: {sorted(vaults)}"
            )
    return [str(name) for name in overlay_raw]


def _optional_resolved_path(
    raw: Mapping[str, object],
    field_name: str,
    recipe_dir: Path,
    *,
    must_exist: bool = False,
) -> Path | None:
    """Resolve an optional recipe-relative path field."""
    field_raw = _str_or_none(raw.get(field_name))
    if not field_raw:
        return None
    resolved = _resolve_vault_path(field_raw, recipe_dir)
    if must_exist and not resolved.is_dir():
        raise BookConfigError(f"{field_name} path does not exist: {resolved}")
    return resolved


def _parse_art_placements(raw: object) -> list[ArtPlacementSpec]:
    """Parse optional dynamic art placements."""
    if raw is None:
        return []
    if not isinstance(raw, Mapping):
        raise BookConfigError("art must be a mapping when provided")
    placements_raw = raw.get("placements") or []
    if not isinstance(placements_raw, list):
        raise BookConfigError("art.placements must be a list when provided")
    placements: list[ArtPlacementSpec] = []
    for i, placement_raw in enumerate(placements_raw):
        if not isinstance(placement_raw, Mapping):
            raise BookConfigError(
                "art.placements"
                f"[{i}] must be a mapping, got {type(placement_raw).__name__}"
            )
        placements.append(ArtPlacementSpec.from_dict(placement_raw, index=i))
    return placements


def _parse_contents(
    contents_raw: Sequence[Mapping[str, object]],
) -> list[ContentItemSpec]:
    """Parse normalized chapter mappings into typed chapter specs."""
    return [
        ContentItemSpec.from_dict(chapter_raw, index=i)
        for i, chapter_raw in enumerate(contents_raw)
    ]


def _validate_chapter_sources(
    chapters: Sequence[ContentItemSpec],
    crumb: str,
    *,
    declared_vaults: set[str],
) -> None:
    """Ensure explicit source vault prefixes refer to declared vaults."""
    for i, chapter in enumerate(chapters):
        here = f"{crumb}[{i}]"
        if (
            chapter.source is not None
            and chapter.source.vault is not None
            and chapter.source.vault not in declared_vaults
        ):
            raise BookConfigError(
                f"{here} source {chapter.source!s} references unknown vault "
                f"{chapter.source.vault!r}; declared vaults: {sorted(declared_vaults)}"
            )
        for j, item in enumerate(chapter.sources):
            if (
                item.source.vault is not None
                and item.source.vault not in declared_vaults
            ):
                raise BookConfigError(
                    f"{here}.sources[{j}] source {item.source!s} "
                    "references unknown vault "
                    f"{item.source.vault!r}; declared vaults: {sorted(declared_vaults)}"
                )
        _validate_chapter_sources(
            chapter.children,
            f"{here}.children",
            declared_vaults=declared_vaults,
        )


def _cover_spec(
    cover_raw: Mapping[str, object] | None,
) -> CoverSpec:
    """Build cover settings from explicit top-level cover config."""
    return CoverSpec.from_dict(cover_raw)


def _reject_legacy_recipe_shape(raw: Mapping[str, object]) -> None:
    """Fail fast for the pre-contents recipe fields."""
    legacy = {
        "build": "move build defaults to papercrown.yaml",
        "chapters": "use contents instead",
        "front_matter": "make these ordinary contents items before kind: toc",
        "back_matter": "make these ordinary contents items after kind: toc",
        "include_chapters": "use include_contents instead",
    }
    for key, hint in legacy.items():
        if key in raw:
            raise BookConfigError(f"{key} is no longer supported; {hint}")


def _reject_inline_title_content(contents: Sequence[Mapping[str, object]]) -> None:
    """Reject the V1 inline title convention in ordered contents."""
    for i, item in enumerate(contents):
        if item.get("kind") == "inline" and item.get("style") == "title":
            raise BookConfigError(
                "inline title items are no longer supported; use top-level "
                f"title/subtitle/cover_eyebrow fields instead (contents[{i}])"
            )


def _project_dir_for_recipe(recipe_path: Path) -> Path:
    """Return the book project root for a book config path."""
    return recipe_path.parent.resolve()


def _normalize_contents(raw: object) -> list[dict[str, object]]:
    """Normalize contents strings/mappings into mutable mapping items."""
    if not isinstance(raw, list) or not raw:
        raise BookConfigError("book missing required field: contents (non-empty list)")
    contents: list[dict[str, object]] = []
    for i, item in enumerate(raw):
        if isinstance(item, str):
            contents.append({"source": item})
            continue
        if not isinstance(item, Mapping):
            raise BookConfigError(
                f"contents[{i}] must be a mapping or source string, "
                f"got {type(item).__name__}"
            )
        contents.append({str(key): value for key, value in item.items()})
    return contents


def _load_book_config_mapping(
    path: Path,
    *,
    stack: tuple[Path, ...],
) -> dict[str, object]:
    """Load a recipe or inherited recipe layer into an expanded mapping."""
    recipe_path = path.resolve()
    if recipe_path in stack:
        cycle = " -> ".join(p.name for p in (*stack, recipe_path))
        raise BookConfigError(f"book config extends/include cycle detected: {cycle}")

    try:
        raw_obj = yaml.safe_load(recipe_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise BookConfigError(f"invalid YAML in {recipe_path}: {e}") from e
    except OSError as e:
        raise BookConfigError(f"could not read book config {recipe_path}: {e}") from e

    if raw_obj is None:
        raise BookConfigError(f"book config is empty: {recipe_path}")
    if not isinstance(raw_obj, Mapping):
        raise BookConfigError(
            f"book config root must be a mapping, got {type(raw_obj).__name__}"
        )

    raw = {str(key): value for key, value in raw_obj.items()}
    recipe_dir = recipe_path.parent
    next_stack = (*stack, recipe_path)

    base: dict[str, object] = {}
    extends_raw = raw.get("extends")
    if extends_raw is not None:
        if not isinstance(extends_raw, str) or not extends_raw.strip():
            raise BookConfigError("extends must be a non-empty path string")
        base = _load_book_config_mapping(
            _resolve_include_path(extends_raw, recipe_dir),
            stack=next_stack,
        )

    local = dict(raw)
    local.pop("extends", None)
    content_includes = local.pop("include_contents", None)
    vault_includes = local.pop("include_vaults", None)
    _normalize_recipe_filesystem_paths(local, recipe_dir)

    if vault_includes is not None:
        _merge_vault_includes(local, vault_includes, recipe_dir, stack=next_stack)
    if content_includes is not None:
        _merge_content_includes(local, content_includes, recipe_dir, stack=next_stack)

    return _deep_merge(base, local)


def _resolve_include_path(raw: str, base_dir: Path) -> Path:
    """Resolve an include or extends path relative to the declaring file."""
    path = Path(raw)
    if not path.is_absolute():
        path = base_dir / path
    resolved = path.resolve()
    if not resolved.is_file():
        raise BookConfigError(f"included book config file not found: {resolved}")
    return resolved


def _normalize_recipe_filesystem_paths(
    raw: dict[str, object], recipe_dir: Path
) -> None:
    """Rewrite recipe-relative filesystem paths as absolute strings in place."""
    vaults_raw = raw.get("vaults")
    if isinstance(vaults_raw, Mapping):
        raw["vaults"] = {
            str(name): str(_resolve_vault_path(str(path), recipe_dir))
            for name, path in vaults_raw.items()
        }
    art_dir_raw = raw.get("art_dir")
    if isinstance(art_dir_raw, str) and art_dir_raw.strip():
        raw["art_dir"] = str(_resolve_vault_path(art_dir_raw, recipe_dir))
    art_dirs_raw = raw.get("art_dirs")
    if isinstance(art_dirs_raw, list):
        resolved = [
            str(_resolve_vault_path(item, recipe_dir))
            for item in art_dirs_raw
            if isinstance(item, str) and item.strip()
        ]
        if resolved and "art_dir" not in raw:
            # The renderer currently consumes one primary art library; project
            # defaults accept the new list shape and use the first library.
            raw["art_dir"] = resolved[0]
    output_dir_raw = raw.get("output_dir")
    if isinstance(output_dir_raw, str) and output_dir_raw.strip():
        raw["output_dir"] = str(_resolve_vault_path(output_dir_raw, recipe_dir))
    cache_dir_raw = raw.get("cache_dir")
    if isinstance(cache_dir_raw, str) and cache_dir_raw.strip():
        raw["cache_dir"] = str(_resolve_vault_path(cache_dir_raw, recipe_dir))
    theme_dir_raw = raw.get("theme_dir")
    if isinstance(theme_dir_raw, str) and theme_dir_raw.strip():
        raw["theme_dir"] = str(_resolve_vault_path(theme_dir_raw, recipe_dir))


def _merge_vault_includes(
    raw: dict[str, object],
    includes: object,
    recipe_dir: Path,
    *,
    stack: tuple[Path, ...],
) -> None:
    """Merge vault declarations from include files into ``raw``."""
    include_paths = _include_path_list(includes, field_name="include_vaults")
    included_vaults: dict[str, object] = {}
    included_overlay: list[str] = []
    for include in include_paths:
        include_path = _resolve_include_path(include, recipe_dir)
        fragment = _read_yaml_mapping(include_path, stack=stack)
        vaults_raw = fragment.get("vaults", fragment)
        if not isinstance(vaults_raw, Mapping):
            raise BookConfigError(
                f"{include_path.name}: vault include must be a mapping"
            )
        for name, value in vaults_raw.items():
            included_vaults[str(name)] = str(
                _resolve_vault_path(str(value), include_path.parent)
            )
        overlay_raw = fragment.get("vault_overlay")
        if isinstance(overlay_raw, list) and all(
            isinstance(item, str) for item in overlay_raw
        ):
            included_overlay.extend(str(item) for item in overlay_raw)

    local_vaults = raw.get("vaults")
    merged_vaults = dict(included_vaults)
    if isinstance(local_vaults, Mapping):
        merged_vaults.update({str(key): value for key, value in local_vaults.items()})
    raw["vaults"] = merged_vaults
    if "vault_overlay" not in raw and included_overlay:
        raw["vault_overlay"] = _dedupe(included_overlay + list(merged_vaults))


def _merge_content_includes(
    raw: dict[str, object],
    includes: object,
    recipe_dir: Path,
    *,
    stack: tuple[Path, ...],
) -> None:
    """Prepend content fragments from include files to ``raw`` contents."""
    include_paths = _include_path_list(includes, field_name="include_contents")
    included_contents: list[object] = []
    for include in include_paths:
        include_path = _resolve_include_path(include, recipe_dir)
        fragment = _read_yaml_mapping_or_list(include_path, stack=stack)
        if isinstance(fragment, list):
            included_contents.extend(deepcopy(fragment))
            continue
        contents_raw = fragment.get("contents")
        if not isinstance(contents_raw, list):
            raise BookConfigError(
                f"{include_path.name}: content include must be a list or "
                "a mapping with contents"
            )
        included_contents.extend(deepcopy(contents_raw))

    local_contents_raw = raw.get("contents")
    if local_contents_raw is None:
        local_contents: list[object] = []
    elif isinstance(local_contents_raw, list):
        local_contents = list(local_contents_raw)
    else:
        raise BookConfigError("contents must be a list when include_contents is used")
    raw["contents"] = included_contents + local_contents


def _read_yaml_mapping(path: Path, *, stack: tuple[Path, ...]) -> dict[str, object]:
    """Read an include file that must contain a mapping."""
    obj = _read_yaml_mapping_or_list(path, stack=stack)
    if not isinstance(obj, Mapping):
        raise BookConfigError(f"{path.name}: expected a mapping")
    return {str(key): value for key, value in obj.items()}


def _read_yaml_mapping_or_list(
    path: Path,
    *,
    stack: tuple[Path, ...],
) -> Mapping[object, object] | list[object]:
    """Read an include file that may contain a mapping or list."""
    resolved = path.resolve()
    if resolved in stack:
        cycle = " -> ".join(p.name for p in (*stack, resolved))
        raise BookConfigError(f"book config extends/include cycle detected: {cycle}")
    try:
        obj = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise BookConfigError(f"invalid YAML in {resolved}: {e}") from e
    except OSError as e:
        raise BookConfigError(f"could not read include {resolved}: {e}") from e
    if isinstance(obj, Mapping) or isinstance(obj, list):
        return obj
    raise BookConfigError(f"{resolved.name}: expected a mapping or list include")


def _include_path_list(raw: object, *, field_name: str) -> list[str]:
    """Normalize one include path or a list of include paths."""
    if isinstance(raw, str) and raw.strip():
        return [raw]
    if isinstance(raw, list) and all(isinstance(item, str) for item in raw):
        return [str(item) for item in raw]
    raise BookConfigError(f"{field_name} must be a path string or list of path strings")


def _deep_merge(
    base: dict[str, object], override: dict[str, object]
) -> dict[str, object]:
    """Deep-merge two recipe mappings with list/scalar replacement semantics."""
    merged = deepcopy(base)
    for key, value in override.items():
        existing = merged.get(key)
        if isinstance(existing, Mapping) and isinstance(value, Mapping):
            merged[key] = _deep_merge(
                {str(k): v for k, v in existing.items()},
                {str(k): v for k, v in value.items()},
            )
        else:
            merged[key] = deepcopy(value)
    return merged


def _dedupe(values: list[str]) -> list[str]:
    """Return values with duplicates removed while preserving order."""
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out
