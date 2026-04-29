"""Recipe YAML loading, includes, and path normalization."""

from __future__ import annotations

import re
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path

import yaml

from papercrown.project.recipe.models import (
    DEFAULT_THEME,
    BookMetadataSpec,
    ChapterSpec,
    CoverSpec,
    FillersSpec,
    OrnamentsSpec,
    PageDamageSpec,
    Recipe,
    RecipeError,
    SplashSpec,
    VaultSpec,
    _filename_slug,
    _image_treatments_mapping,
    _matter_list,
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


def load_recipe(path: str | Path) -> Recipe:
    """Load and validate a recipe YAML file.

    Raises RecipeError with a clear message on any structural or referential
    problem (missing required fields, unknown chapter kinds, vault paths that
    don't exist, vault_overlay names not in `vaults`, recipe include cycles,
    etc). Recipes may use ``extends``, ``include_chapters``, and
    ``include_vaults`` to share reusable book structure.
    """
    recipe_path = Path(path).resolve()
    if not recipe_path.is_file():
        raise RecipeError(f"recipe file not found: {recipe_path}")

    raw = _load_recipe_mapping(recipe_path, stack=())

    # Required: title
    title = raw.get("title")
    if not isinstance(title, str) or not title.strip():
        raise RecipeError("recipe missing required field: title (non-empty string)")

    # Required: vaults (at least one)
    vaults_raw = raw.get("vaults")
    if not isinstance(vaults_raw, Mapping) or not vaults_raw:
        raise RecipeError(
            "recipe missing required field: vaults (mapping of name -> path)"
        )

    recipe_dir = recipe_path.parent
    vaults: dict[str, VaultSpec] = {}
    for name, vp in vaults_raw.items():
        if not isinstance(name, str) or not re.match(r"^[A-Za-z0-9_-]+$", name):
            raise RecipeError(
                f"invalid vault alias {name!r}: must be alphanumeric/underscore/dash"
            )
        resolved = _resolve_vault_path(str(vp), recipe_dir)
        if not resolved.is_dir():
            raise RecipeError(f"vault {name!r} path does not exist: {resolved}")
        vaults[name] = VaultSpec(name=name, path=resolved)

    # Optional: vault_overlay (defaults to declared insertion order)
    overlay_raw = raw.get("vault_overlay")
    if overlay_raw is None:
        vault_overlay = list(vaults.keys())
    else:
        if not isinstance(overlay_raw, list) or not all(
            isinstance(x, str) for x in overlay_raw
        ):
            raise RecipeError("vault_overlay must be a list of vault alias strings")
        for name in overlay_raw:
            if name not in vaults:
                raise RecipeError(
                    f"vault_overlay references unknown vault {name!r}; "
                    f"declared vaults: {sorted(vaults)}"
                )
        # Allow partial overlay; missing vaults still work via explicit prefix.
        vault_overlay = [str(name) for name in overlay_raw]

    art_dir_override = None
    art_dir_raw = _str_or_none(raw.get("art_dir"))
    if art_dir_raw:
        art_dir_override = _resolve_vault_path(art_dir_raw, recipe_dir)
        if not art_dir_override.is_dir():
            raise RecipeError(f"art_dir path does not exist: {art_dir_override}")

    output_dir_override = None
    output_dir_raw = _str_or_none(raw.get("output_dir"))
    if output_dir_raw:
        output_dir_override = _resolve_vault_path(output_dir_raw, recipe_dir)

    output_name = _str_or_none(raw.get("output_name"))
    if output_name is not None:
        output_name = _filename_slug(output_name)

    cache_dir_override = None
    cache_dir_raw = _str_or_none(raw.get("cache_dir"))
    if cache_dir_raw:
        cache_dir_override = _resolve_vault_path(cache_dir_raw, recipe_dir)

    theme = _slug_or_none(raw.get("theme"), loc="theme") or DEFAULT_THEME
    theme_dir_override = None
    theme_dir_raw = _str_or_none(raw.get("theme_dir"))
    if theme_dir_raw:
        theme_dir_override = _resolve_vault_path(theme_dir_raw, recipe_dir)
        if not theme_dir_override.is_dir():
            raise RecipeError(f"theme_dir path does not exist: {theme_dir_override}")

    metadata_raw = raw.get("metadata")
    if metadata_raw is not None and not isinstance(metadata_raw, Mapping):
        raise RecipeError("metadata must be a mapping when provided")
    theme_options = _theme_options_mapping(raw.get("theme_options"))
    image_treatments = _image_treatments_mapping(raw.get("image_treatments"))
    front_matter = _matter_list(raw.get("front_matter"), field_name="front_matter")
    back_matter = _matter_list(raw.get("back_matter"), field_name="back_matter")

    # Required: chapters (non-empty)
    cover_raw = raw.get("cover")
    if cover_raw is not None and not isinstance(cover_raw, Mapping):
        raise RecipeError("cover must be a mapping when provided")
    ornaments_raw = raw.get("ornaments")
    if ornaments_raw is not None and not isinstance(ornaments_raw, Mapping):
        raise RecipeError("ornaments must be a mapping when provided")
    fillers_raw = raw.get("fillers")
    if fillers_raw is not None and not isinstance(fillers_raw, Mapping):
        raise RecipeError("fillers must be a mapping when provided")
    page_damage_raw = raw.get("page_damage")
    if page_damage_raw is not None and not isinstance(page_damage_raw, Mapping):
        raise RecipeError("page_damage must be a mapping when provided")

    splashes_raw = raw.get("splashes") or []
    if not isinstance(splashes_raw, list):
        raise RecipeError("splashes must be a list when provided")
    splashes: list[SplashSpec] = []
    for i, splash_raw in enumerate(splashes_raw):
        if not isinstance(splash_raw, Mapping):
            raise RecipeError(
                f"splashes[{i}] must be a mapping, got {type(splash_raw).__name__}"
            )
        splashes.append(SplashSpec.from_dict(splash_raw, index=i))

    chapters_raw = raw.get("chapters")
    if not isinstance(chapters_raw, list) or not chapters_raw:
        raise RecipeError("recipe missing required field: chapters (non-empty list)")
    chapters: list[ChapterSpec] = []
    for i, chapter_raw in enumerate(chapters_raw):
        if not isinstance(chapter_raw, Mapping):
            raise RecipeError(
                f"chapter[{i}] must be a mapping, got {type(chapter_raw).__name__}"
            )
        chapters.append(ChapterSpec.from_dict(chapter_raw, index=i))

    # Validate every chapter source's vault prefix (if explicit) refers to a
    # known vault. Walks recursively into group `children` too.
    def _validate_sources(chs: list[ChapterSpec], crumb: str) -> None:
        for i, ch in enumerate(chs):
            here = f"{crumb}[{i}]"
            if (
                ch.source is not None
                and ch.source.vault is not None
                and ch.source.vault not in vaults
            ):
                raise RecipeError(
                    f"{here} source {ch.source!s} references unknown vault "
                    f"{ch.source.vault!r}; declared vaults: {sorted(vaults)}"
                )
            for j, item in enumerate(ch.sources):
                if item.source.vault is not None and item.source.vault not in vaults:
                    raise RecipeError(
                        f"{here}.sources[{j}] source {item.source!s} "
                        "references unknown vault "
                        f"{item.source.vault!r}; declared vaults: {sorted(vaults)}"
                    )
            _validate_sources(ch.children, f"{here}.children")

    _validate_sources(chapters, "chapter")

    return Recipe(
        title=title.strip(),
        subtitle=_str_or_none(raw.get("subtitle")),
        cover_eyebrow=_str_or_none(raw.get("cover_eyebrow")),
        cover_footer=_str_or_none(raw.get("cover_footer")),
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
        front_matter=front_matter,
        back_matter=back_matter,
        art_dir_override=art_dir_override,
        ornaments=OrnamentsSpec.from_dict(ornaments_raw),
        cover=CoverSpec.from_dict(cover_raw),
        splashes=splashes,
        fillers=FillersSpec.from_dict(fillers_raw),
        page_damage=PageDamageSpec.from_dict(page_damage_raw),
        chapters=chapters,
        recipe_path=recipe_path,
    )


def _load_recipe_mapping(path: Path, *, stack: tuple[Path, ...]) -> dict[str, object]:
    """Load a recipe or inherited recipe layer into an expanded mapping."""
    recipe_path = path.resolve()
    if recipe_path in stack:
        cycle = " -> ".join(p.name for p in (*stack, recipe_path))
        raise RecipeError(f"recipe extends/include cycle detected: {cycle}")

    try:
        raw_obj = yaml.safe_load(recipe_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise RecipeError(f"invalid YAML in {recipe_path}: {e}") from e
    except OSError as e:
        raise RecipeError(f"could not read recipe {recipe_path}: {e}") from e

    if raw_obj is None:
        raise RecipeError(f"recipe is empty: {recipe_path}")
    if not isinstance(raw_obj, Mapping):
        raise RecipeError(
            f"recipe root must be a mapping, got {type(raw_obj).__name__}"
        )

    raw = {str(key): value for key, value in raw_obj.items()}
    recipe_dir = recipe_path.parent
    next_stack = (*stack, recipe_path)

    base: dict[str, object] = {}
    extends_raw = raw.get("extends")
    if extends_raw is not None:
        if not isinstance(extends_raw, str) or not extends_raw.strip():
            raise RecipeError("extends must be a non-empty path string")
        base = _load_recipe_mapping(
            _resolve_include_path(extends_raw, recipe_dir),
            stack=next_stack,
        )

    local = dict(raw)
    local.pop("extends", None)
    chapter_includes = local.pop("include_chapters", None)
    vault_includes = local.pop("include_vaults", None)
    _normalize_recipe_filesystem_paths(local, recipe_dir)

    if vault_includes is not None:
        _merge_vault_includes(local, vault_includes, recipe_dir, stack=next_stack)
    if chapter_includes is not None:
        _merge_chapter_includes(local, chapter_includes, recipe_dir, stack=next_stack)

    return _deep_merge(base, local)


def _resolve_include_path(raw: str, base_dir: Path) -> Path:
    """Resolve an include or extends path relative to the declaring file."""
    path = Path(raw)
    if not path.is_absolute():
        path = base_dir / path
    resolved = path.resolve()
    if not resolved.is_file():
        raise RecipeError(f"included recipe file not found: {resolved}")
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
            raise RecipeError(f"{include_path.name}: vault include must be a mapping")
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


def _merge_chapter_includes(
    raw: dict[str, object],
    includes: object,
    recipe_dir: Path,
    *,
    stack: tuple[Path, ...],
) -> None:
    """Prepend chapter fragments from include files to ``raw`` chapters."""
    include_paths = _include_path_list(includes, field_name="include_chapters")
    included_chapters: list[object] = []
    for include in include_paths:
        include_path = _resolve_include_path(include, recipe_dir)
        fragment = _read_yaml_mapping_or_list(include_path, stack=stack)
        if isinstance(fragment, list):
            included_chapters.extend(deepcopy(fragment))
            continue
        chapters_raw = fragment.get("chapters")
        if not isinstance(chapters_raw, list):
            raise RecipeError(
                f"{include_path.name}: chapter include must be a list or "
                "a mapping with chapters"
            )
        included_chapters.extend(deepcopy(chapters_raw))

    local_chapters_raw = raw.get("chapters")
    if local_chapters_raw is None:
        local_chapters: list[object] = []
    elif isinstance(local_chapters_raw, list):
        local_chapters = list(local_chapters_raw)
    else:
        raise RecipeError("chapters must be a list when include_chapters is used")
    raw["chapters"] = included_chapters + local_chapters


def _read_yaml_mapping(path: Path, *, stack: tuple[Path, ...]) -> dict[str, object]:
    """Read an include file that must contain a mapping."""
    obj = _read_yaml_mapping_or_list(path, stack=stack)
    if not isinstance(obj, Mapping):
        raise RecipeError(f"{path.name}: expected a mapping")
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
        raise RecipeError(f"recipe extends/include cycle detected: {cycle}")
    try:
        obj = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise RecipeError(f"invalid YAML in {resolved}: {e}") from e
    except OSError as e:
        raise RecipeError(f"could not read include {resolved}: {e}") from e
    if isinstance(obj, Mapping) or isinstance(obj, list):
        return obj
    raise RecipeError(f"{resolved.name}: expected a mapping or list include")


def _include_path_list(raw: object, *, field_name: str) -> list[str]:
    """Normalize one include path or a list of include paths."""
    if isinstance(raw, str) and raw.strip():
        return [raw]
    if isinstance(raw, list) and all(isinstance(item, str) for item in raw):
        return [str(item) for item in raw]
    raise RecipeError(f"{field_name} must be a path string or list of path strings")


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
