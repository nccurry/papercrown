"""Layered configuration for the Paper Crown CLI."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import yaml

from papercrown.build.options import (
    BuildScope,
    BuildTarget,
    DraftMode,
    OutputProfile,
    PageDamageMode,
    PaginationMode,
)
from papercrown.project.recipe import RecipeError, _load_recipe_mapping


class ConfigError(ValueError):
    """Raised when a project or recipe build config is malformed."""


# Supported keys inside the nested build configuration block.
_BUILD_KEYS = {
    "target",
    "scope",
    "profile",
    "chapter",
    "include_art",
    "force",
    "jobs",
    "clean_pdf",
    "pagination",
    "draft_mode",
    "page_damage",
    "timings",
}
# Supported keys at the project configuration root.
_PROJECT_KEYS = {"default_book", "build", "defaults"}
# Upper bound for jobs:auto so one command does not overfill the machine.
AUTO_JOBS_CAP = 4


@dataclass(frozen=True)
class BuildConfig:
    """Resolved build options after config layers and CLI overrides."""

    recipe_path: Path
    project_defaults: dict[str, object] = field(default_factory=dict)
    project_defaults_base_dir: Path | None = None
    target: BuildTarget = BuildTarget.PDF
    scope: BuildScope = BuildScope.ALL
    profile: OutputProfile = OutputProfile.PRINT
    include_art: bool = True
    single_chapter: str | None = None
    force: bool = False
    jobs: int = 1
    clean_pdf: bool = True
    pagination_mode: PaginationMode = PaginationMode.REPORT
    draft_mode: DraftMode = DraftMode.FAST
    page_damage_mode: PageDamageMode = PageDamageMode.AUTO
    timings: bool = False


@dataclass(frozen=True)
class BuildConfigPatch:
    """Partial build config used for one precedence layer."""

    default_book: Path | None = None
    project_defaults: dict[str, object] | None = None
    project_defaults_base_dir: Path | None = None
    target: BuildTarget | None = None
    scope: BuildScope | None = None
    profile: OutputProfile | None = None
    include_art: bool | None = None
    single_chapter: str | None = None
    force: bool | None = None
    jobs: int | None = None
    clean_pdf: bool | None = None
    pagination_mode: PaginationMode | None = None
    draft_mode: DraftMode | None = None
    page_damage_mode: PageDamageMode | None = None
    timings: bool | None = None

    def apply(self, config: BuildConfig) -> BuildConfig:
        """Return ``config`` with non-empty values from this patch applied."""
        updates: dict[str, Any] = {}
        for patch_name, config_name in (
            ("target", "target"),
            ("scope", "scope"),
            ("profile", "profile"),
            ("include_art", "include_art"),
            ("single_chapter", "single_chapter"),
            ("force", "force"),
            ("jobs", "jobs"),
            ("clean_pdf", "clean_pdf"),
            ("pagination_mode", "pagination_mode"),
            ("draft_mode", "draft_mode"),
            ("page_damage_mode", "page_damage_mode"),
            ("timings", "timings"),
            ("project_defaults", "project_defaults"),
            ("project_defaults_base_dir", "project_defaults_base_dir"),
        ):
            value = getattr(self, patch_name)
            if value is not None:
                updates[config_name] = value
        return replace(config, **updates)


def default_project_config_path() -> Path:
    """Return the conventional project config path."""
    return Path.cwd() / "papercrown.yaml"


def load_project_config(
    path: Path | None = None,
    *,
    enabled: bool = True,
) -> BuildConfigPatch:
    """Load ``papercrown.yaml`` when enabled and present."""
    if not enabled:
        return BuildConfigPatch()
    config_path = (path or default_project_config_path()).resolve()
    if not config_path.exists():
        if path is None:
            return BuildConfigPatch()
        raise ConfigError(f"config file not found: {config_path}")
    raw = _read_yaml_mapping(config_path, label="config")
    unknown = set(raw) - _PROJECT_KEYS
    if unknown:
        raise ConfigError(
            f"{config_path}: unknown config key(s): {', '.join(sorted(unknown))}"
        )
    patch = BuildConfigPatch()
    if raw.get("default_book") is not None:
        patch = replace(
            patch,
            default_book=_resolve_config_path(raw["default_book"], config_path),
        )
    if raw.get("defaults") is not None:
        defaults_raw = raw["defaults"]
        if not isinstance(defaults_raw, Mapping):
            raise ConfigError(f"{config_path}: defaults must be a mapping")
        patch = replace(
            patch,
            project_defaults={str(key): value for key, value in defaults_raw.items()},
            project_defaults_base_dir=config_path.parent,
        )
    build_raw = raw.get("build") or {}
    if not isinstance(build_raw, Mapping):
        raise ConfigError(f"{config_path}: build must be a mapping")
    return _merge_patches(
        patch,
        _build_patch_from_mapping(
            build_raw,
            source=f"{config_path}: build",
        ),
    )


def load_recipe_build_config(recipe_path: Path) -> BuildConfigPatch:
    """Load the optional top-level ``build:`` block from a recipe."""
    try:
        raw = _load_recipe_mapping(recipe_path.resolve(), stack=())
    except RecipeError as error:
        raise ConfigError(str(error)) from error
    build_raw = raw.get("build") or {}
    if not isinstance(build_raw, Mapping):
        raise ConfigError(f"{recipe_path}: build must be a mapping")
    return _build_patch_from_mapping(
        build_raw,
        source=f"{recipe_path}: build",
    )


def resolve_build_config(
    *,
    recipe_arg: Path | None,
    project: BuildConfigPatch,
    recipe: BuildConfigPatch,
    cli: BuildConfigPatch,
) -> BuildConfig:
    """Resolve the effective build config with documented precedence."""
    recipe_path = recipe_arg or project.default_book
    if recipe_path is None:
        raise ConfigError(
            "no book provided; pass a book path or set default_book "
            "in papercrown.yaml"
        )
    if not recipe_path.is_absolute():
        recipe_path = recipe_path.resolve()
    config = BuildConfig(recipe_path=recipe_path.resolve())
    for patch in (project, recipe, cli):
        config = patch.apply(config)
    _validate_config(config)
    return config


def _build_patch_from_mapping(
    raw: Mapping[object, object],
    *,
    source: str,
) -> BuildConfigPatch:
    unknown = {str(key) for key in raw} - _BUILD_KEYS
    if unknown:
        unknown_keys = ", ".join(sorted(unknown))
        raise ConfigError(f"{source}: unknown build key(s): {unknown_keys}")
    patch = BuildConfigPatch()
    if "target" in raw:
        patch = replace(
            patch,
            target=_enum_value(BuildTarget, raw["target"], key="target", source=source),
        )
    if "scope" in raw:
        patch = replace(
            patch,
            scope=_enum_value(BuildScope, raw["scope"], key="scope", source=source),
        )
    if "profile" in raw:
        patch = replace(
            patch,
            profile=_enum_value(
                OutputProfile,
                raw["profile"],
                key="profile",
                source=source,
            ),
        )
    if "chapter" in raw:
        patch = replace(
            patch,
            single_chapter=_optional_str(raw["chapter"], key="chapter", source=source),
        )
    if "include_art" in raw:
        patch = replace(
            patch,
            include_art=_bool_value(
                raw["include_art"],
                key="include_art",
                source=source,
            ),
        )
    if "force" in raw:
        patch = replace(
            patch,
            force=_bool_value(raw["force"], key="force", source=source),
        )
    if "jobs" in raw:
        patch = replace(patch, jobs=parse_jobs(raw["jobs"]))
    if "clean_pdf" in raw:
        patch = replace(
            patch,
            clean_pdf=_bool_value(
                raw["clean_pdf"],
                key="clean_pdf",
                source=source,
            ),
        )
    if "pagination" in raw:
        patch = replace(
            patch,
            pagination_mode=_enum_value(
                PaginationMode,
                raw["pagination"],
                key="pagination",
                source=source,
            ),
        )
    if "draft_mode" in raw:
        patch = replace(
            patch,
            draft_mode=_enum_value(
                DraftMode,
                raw["draft_mode"],
                key="draft_mode",
                source=source,
            ),
        )
    if "page_damage" in raw:
        patch = replace(
            patch,
            page_damage_mode=_enum_value(
                PageDamageMode,
                raw["page_damage"],
                key="page_damage",
                source=source,
            ),
        )
    if "timings" in raw:
        patch = replace(
            patch,
            timings=_bool_value(raw["timings"], key="timings", source=source),
        )
    return patch


def parse_jobs(value: object) -> int:
    """Parse a concrete job count or ``auto``."""
    if isinstance(value, str):
        stripped = value.strip().lower()
        if stripped == "auto":
            return max(1, min(AUTO_JOBS_CAP, os.cpu_count() or 1))
        if stripped.isdigit():
            return parse_jobs(int(stripped))
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError("jobs must be a positive integer or 'auto'")
    if value < 1:
        raise ConfigError("jobs must be a positive integer or 'auto'")
    return value


def _validate_config(config: BuildConfig) -> None:
    if config.single_chapter and config.scope is not BuildScope.SECTIONS:
        raise ConfigError("--chapter may only be used with --scope sections")
    if config.target is BuildTarget.WEB:
        if config.profile is not OutputProfile.PRINT:
            raise ConfigError("--target web does not accept a PDF --profile")
        if config.scope is not BuildScope.ALL:
            raise ConfigError("--target web only supports --scope all")
    if (
        config.draft_mode is DraftMode.VISUAL
        and config.profile is not OutputProfile.DRAFT
    ):
        raise ConfigError("--draft-mode visual is only valid with --profile draft")


def _read_yaml_mapping(path: Path, *, label: str) -> dict[str, object]:
    try:
        raw_obj = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise ConfigError(f"invalid YAML in {path}: {error}") from error
    except OSError as error:
        raise ConfigError(f"could not read {label} {path}: {error}") from error
    if raw_obj is None:
        return {}
    if not isinstance(raw_obj, Mapping):
        raise ConfigError(f"{path}: root must be a mapping")
    return {str(key): value for key, value in raw_obj.items()}


def _enum_value(
    enum_type: type[Any],
    value: object,
    *,
    key: str,
    source: str,
) -> Any:
    if value is False and any(item.value == "off" for item in enum_type):
        value = "off"
    raw = _optional_str(value, key=key, source=source)
    if raw is None:
        raise ConfigError(f"{source}: {key} cannot be empty")
    try:
        return enum_type(raw)
    except ValueError as error:
        choices = ", ".join(item.value for item in enum_type)
        raise ConfigError(f"{source}: {key} must be one of: {choices}") from error


def _bool_value(value: object, *, key: str, source: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"{source}: {key} must be true or false")
    return value


def _optional_str(value: object, *, key: str, source: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ConfigError(f"{source}: {key} must be a string")
    stripped = value.strip()
    return stripped or None


def _resolve_config_path(value: object, config_path: Path) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{config_path}: default_book must be a path string")
    path = Path(value)
    if not path.is_absolute():
        path = config_path.parent / path
    return path.resolve()


def _merge_patches(
    base: BuildConfigPatch,
    override: BuildConfigPatch,
) -> BuildConfigPatch:
    return BuildConfigPatch(
        default_book=override.default_book or base.default_book,
        project_defaults=override.project_defaults or base.project_defaults,
        project_defaults_base_dir=(
            override.project_defaults_base_dir or base.project_defaults_base_dir
        ),
        target=override.target or base.target,
        scope=override.scope or base.scope,
        profile=override.profile or base.profile,
        include_art=(
            base.include_art if override.include_art is None else override.include_art
        ),
        single_chapter=override.single_chapter or base.single_chapter,
        force=base.force if override.force is None else override.force,
        jobs=override.jobs or base.jobs,
        clean_pdf=base.clean_pdf if override.clean_pdf is None else override.clean_pdf,
        pagination_mode=override.pagination_mode or base.pagination_mode,
        draft_mode=override.draft_mode or base.draft_mode,
        page_damage_mode=override.page_damage_mode or base.page_damage_mode,
        timings=base.timings if override.timings is None else override.timings,
    )
