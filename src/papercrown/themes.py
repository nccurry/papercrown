"""Theme-pack discovery and render-resource resolution."""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .recipe import DEFAULT_THEME, Recipe, RecipeError
from .resources import TEMPLATE_FILE, THEMES_DIR


@dataclass(frozen=True)
class ThemePack:
    """Resolved CSS, template, and asset roots for one recipe theme."""

    name: str
    root: Path
    css_files: list[Path]
    template: Path
    resource_paths: list[Path] = field(default_factory=list)
    fingerprint_paths: list[Path] = field(default_factory=list)
    inline_css: str | None = None


def load_theme(recipe: Recipe) -> ThemePack:
    """Resolve the theme pack requested by ``recipe``."""
    root = _theme_root(recipe)
    name = getattr(recipe, "theme", DEFAULT_THEME)
    theme_yaml = root / "theme.yaml"
    if not theme_yaml.is_file():
        raise RecipeError(f"theme {name!r} is missing theme.yaml: {theme_yaml}")
    metadata = _read_theme_yaml(theme_yaml)
    css_files = _resolve_css_files(root, metadata)
    template = _resolve_template(root, metadata)
    asset_roots = _resolve_asset_roots(root, metadata)
    inline_css = _theme_options_css(getattr(recipe, "theme_options", {}))
    fingerprint_paths = [theme_yaml, *css_files]
    if template != TEMPLATE_FILE:
        fingerprint_paths.append(template)
    for asset_root in asset_roots:
        fingerprint_paths.extend(
            path
            for path in sorted(asset_root.rglob("*"), key=lambda item: item.as_posix())
            if path.is_file()
        )
    return ThemePack(
        name=name,
        root=root,
        css_files=css_files,
        template=template,
        resource_paths=[root, *asset_roots],
        fingerprint_paths=fingerprint_paths,
        inline_css=inline_css,
    )


def theme_option_css(options: dict[str, str]) -> str | None:
    """Return CSS custom-property overrides for recipe theme options."""
    return _theme_options_css(options)


def bundled_theme_names() -> list[str]:
    """Return bundled theme names available to recipes."""
    if not THEMES_DIR.is_dir():
        return []
    return sorted(
        path.name
        for path in THEMES_DIR.iterdir()
        if path.is_dir() and (path / "theme.yaml").is_file()
    )


def copy_bundled_theme(name: str, dest: Path, *, overwrite: bool = False) -> Path:
    """Copy a bundled theme directory to ``dest`` and return the copied root."""
    if name not in bundled_theme_names():
        raise RecipeError(
            f"unknown bundled theme {name!r}; choose one of: "
            + ", ".join(bundled_theme_names())
        )
    source = THEMES_DIR / name
    target = dest.resolve()
    if target.exists() and any(target.iterdir()) and not overwrite:
        raise RecipeError(f"destination already exists and is not empty: {target}")
    shutil.copytree(source, target, dirs_exist_ok=True)
    return target


def _theme_root(recipe: Recipe) -> Path:
    name = getattr(recipe, "theme", DEFAULT_THEME)
    theme_dir = getattr(recipe, "theme_dir_override", None) or THEMES_DIR
    root = (theme_dir / name).resolve()
    if not root.is_dir():
        raise RecipeError(
            f"theme {name!r} not found at {root}; "
            "set theme_dir or choose a bundled theme"
        )
    return root


def _read_theme_yaml(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as error:
        raise RecipeError(f"invalid theme YAML in {path}: {error}") from error
    except OSError as error:
        raise RecipeError(f"could not read theme {path}: {error}") from error
    if not isinstance(raw, dict):
        raise RecipeError(f"theme root must be a mapping: {path}")
    return {str(key): value for key, value in raw.items()}


def _resolve_css_files(root: Path, metadata: dict[str, Any]) -> list[Path]:
    css_raw = metadata.get("css", "book.css")
    css_names = _string_or_string_list(css_raw, field_name="css")
    css_files: list[Path] = []
    for css_name in css_names:
        css_path = (root / css_name).resolve()
        if not css_path.is_file():
            raise RecipeError(f"theme CSS file not found: {css_path}")
        css_files.append(css_path)
    return css_files


def _resolve_template(root: Path, metadata: dict[str, Any]) -> Path:
    template_raw = metadata.get("template")
    if template_raw is None:
        return TEMPLATE_FILE
    if not isinstance(template_raw, str) or not template_raw.strip():
        raise RecipeError("theme.template must be a non-empty path string")
    template = (root / template_raw).resolve()
    if not template.is_file():
        raise RecipeError(f"theme template not found: {template}")
    return template


def _resolve_asset_roots(root: Path, metadata: dict[str, Any]) -> list[Path]:
    asset_roots = [root]
    for asset_name in _string_or_string_list(
        metadata.get("assets", []),
        field_name="assets",
    ):
        asset_root = (root / asset_name).resolve()
        if not asset_root.is_dir():
            raise RecipeError(f"theme asset directory not found: {asset_root}")
        asset_roots.append(asset_root)
    return list(dict.fromkeys(asset_roots))


def _string_or_string_list(value: Any, *, field_name: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise RecipeError(f"theme.{field_name} must be a string or list of strings")
    return [item.strip() for item in value if item.strip()]


def _theme_options_css(options: dict[str, str]) -> str | None:
    declarations: list[str] = []
    for key, value in sorted(options.items()):
        property_name = key if key.startswith("--") else f"--{key}"
        if not re.fullmatch(r"--[A-Za-z0-9_-]+", property_name):
            raise RecipeError(
                f"theme option {key!r} must be a valid CSS custom property name"
            )
        sanitized = str(value).replace(";", "")
        declarations.append(f"  {property_name}: {sanitized};")
    if not declarations:
        return None
    return ":root {\n" + "\n".join(declarations) + "\n}\n"
