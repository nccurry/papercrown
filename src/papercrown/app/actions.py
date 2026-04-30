"""Command actions used by the Paper Crown CLI adapters."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from papercrown.app import output
from papercrown.app.config import (
    BuildConfig,
    BuildConfigPatch,
    ConfigError,
    load_project_config,
    load_recipe_build_config,
    parse_jobs,
    resolve_build_config,
)
from papercrown.art.audit import (
    audit_recipe_art,
    format_art_audit_markdown,
    format_art_audit_text,
    write_art_contact_sheet,
)
from papercrown.build.options import (
    BuildScope,
    BuildTarget,
    DraftMode,
    OutputProfile,
    PageDamageMode,
    PaginationMode,
)
from papercrown.build.requests import BuildRequest
from papercrown.project import manifest as manifest_mod
from papercrown.project import themes as themes_mod
from papercrown.project.manifest import Manifest, build_manifest
from papercrown.project.recipe import Recipe, RecipeError, load_recipe
from papercrown.project.starter import InitError, StarterBookType, init_project
from papercrown.render.build import build_outputs
from papercrown.system import verify as verify_mod
from papercrown.system.dependencies import check_dependencies
from papercrown.system.doctor import run_doctor as run_doctor_checks
from papercrown.system.export import Tools, discover_tools

CLI_USAGE_ERROR = 2
TIMINGS_ENV_VAR = "PAPERCROWN_TIMINGS"
ART_OUTPUT_FORMATS = {"text", "markdown"}


class AppCommandError(Exception):
    """Raised when an app action should terminate with a CLI-style error."""

    def __init__(self, message: str, *, exit_code: int = CLI_USAGE_ERROR) -> None:
        super().__init__(message)
        self.exit_code = exit_code


@dataclass(frozen=True)
class _RecipeContext:
    """Recipe inputs resolved from config layers."""

    config: BuildConfig
    recipe: Recipe
    manifest: Manifest


def build_cli_patch(
    *,
    target: BuildTarget | None = None,
    scope: BuildScope | None = None,
    profile: OutputProfile | None = None,
    chapter: str | None = None,
    include_art: bool | None = None,
    force: bool | None = None,
    jobs: str | None = None,
    clean_pdf: bool | None = None,
    pagination: PaginationMode | None = None,
    draft_mode: DraftMode | None = None,
    page_damage: PageDamageMode | None = None,
    timings: bool | None = None,
) -> BuildConfigPatch:
    """Return a config patch from explicit command-line options."""
    if timings is None and os.environ.get(TIMINGS_ENV_VAR) == "1":
        timings = True
    if chapter is not None and scope is None:
        scope = BuildScope.SECTIONS
    parsed_jobs = parse_jobs(jobs) if jobs is not None else None
    return BuildConfigPatch(
        target=target,
        scope=scope,
        profile=profile,
        single_chapter=chapter,
        include_art=include_art,
        force=force,
        jobs=parsed_jobs,
        clean_pdf=clean_pdf,
        pagination_mode=pagination,
        draft_mode=draft_mode,
        page_damage_mode=page_damage,
        timings=timings,
    )


def run_build(
    recipe: Path | None,
    *,
    config: Path | None,
    no_config: bool,
    target: BuildTarget | None,
    scope: BuildScope | None,
    profile: OutputProfile | None,
    chapter: str | None,
    include_art: bool | None,
    force: bool | None,
    jobs: str | None,
    clean_pdf: bool | None,
    pagination: PaginationMode | None,
    draft_mode: DraftMode | None,
    page_damage: PageDamageMode | None,
    filler_debug_overlay: bool,
    timings: bool | None,
) -> None:
    """Build PDFs or the static web artifact."""
    context = _load_recipe_context(
        recipe,
        config=config,
        no_config=no_config,
        cli_patch=build_cli_patch(
            target=target,
            scope=scope,
            profile=profile,
            chapter=chapter,
            include_art=include_art,
            force=force,
            jobs=jobs,
            clean_pdf=clean_pdf,
            pagination=pagination,
            draft_mode=draft_mode,
            page_damage=page_damage,
            timings=timings,
        ),
    )
    _ensure_requested_chapter_exists(context.config, context.manifest)

    tools = _discover_tools_for(context.config.target)
    output.print_tool_paths(tools)

    request = _build_request(
        context,
        filler_debug_overlay=filler_debug_overlay,
    )
    result = build_outputs(tools, request, log=print)
    output.print_build_outputs(result, target=context.config.target)


def run_manifest(
    recipe: Path | None,
    *,
    config: Path | None,
    no_config: bool,
) -> None:
    """Print the resolved build manifest."""
    context = _load_recipe_context(
        recipe,
        config=config,
        no_config=no_config,
        cli_patch=BuildConfigPatch(),
    )
    print(manifest_mod.dump(context.manifest))


def run_art_audit(
    recipe: Path | None,
    *,
    output_format: str,
    strict: bool,
    config: Path | None,
    no_config: bool,
) -> int:
    """Audit the recipe art library against the Paper Crown art contract."""
    if output_format not in ART_OUTPUT_FORMATS:
        raise AppCommandError("--format must be 'text' or 'markdown'")
    context = _load_recipe_context(
        recipe,
        config=config,
        no_config=no_config,
        cli_patch=BuildConfigPatch(),
    )
    result = audit_recipe_art(context.recipe, context.manifest)
    if output_format == "markdown":
        print(format_art_audit_markdown(result))
    else:
        print(format_art_audit_text(result))
    return result.exit_code(strict=strict)


def run_art_contact_sheet(
    recipe: Path | None,
    *,
    output_path: Path | None,
    config: Path | None,
    no_config: bool,
) -> None:
    """Write an HTML visual inventory of the recipe art library."""
    context = _load_recipe_context(
        recipe,
        config=config,
        no_config=no_config,
        cli_patch=BuildConfigPatch(),
    )
    result = audit_recipe_art(context.recipe, context.manifest)
    out = output_path or (context.recipe.generated_root / "art-contact-sheet.html")
    write_art_contact_sheet(result, out)
    print(out)


def run_doctor(
    recipe: Path | None,
    *,
    target: BuildTarget | None,
    strict: bool,
    config: Path | None,
    no_config: bool,
) -> int:
    """Run preflight diagnostics and return the report exit code."""
    context = _load_recipe_context(
        recipe,
        config=config,
        no_config=no_config,
        cli_patch=build_cli_patch(target=target),
    )
    report = run_doctor_checks(
        context.recipe,
        context.manifest,
        target=context.config.target,
        strict=strict,
        log=print,
    )
    return report.exit_code(strict=strict)


def run_deps_check(
    manifest: Path | None,
    *,
    strict: bool,
    updates_only: bool,
) -> int:
    """Report runtime, dev, tool, native, and bundled-asset dependencies."""
    report = check_dependencies(manifest)
    print(report.format_text(updates_only=updates_only))
    return report.exit_code(strict=strict)


def run_verify(
    recipe: Path | None,
    *,
    profile: OutputProfile | None,
    scope: BuildScope | None,
    no_book: bool,
    strict: bool,
    size_report: bool,
    top_images: int,
    web_assets: bool | None,
    config: Path | None,
    no_config: bool,
) -> int:
    """Verify generated outputs against the recipe manifest."""
    context = _load_recipe_context(
        recipe,
        config=config,
        no_config=no_config,
        cli_patch=build_cli_patch(profile=profile, scope=scope),
    )
    return verify_mod.main(
        _verify_argv(
            context.config,
            no_book=no_book,
            strict=strict,
            size_report=size_report,
            top_images=top_images,
            web_assets=web_assets,
        )
    )


def run_init(
    path: Path,
    *,
    title: str | None,
    subtitle: str | None,
    theme: str,
    book_type: StarterBookType,
    vault: Path | None,
    with_cover: bool,
    empty: bool,
    force: bool,
) -> None:
    """Create a new Paper Crown project scaffold."""
    try:
        result = init_project(
            path,
            title=title,
            subtitle=subtitle,
            theme=theme,
            book_type=book_type,
            vault=vault,
            with_cover=with_cover,
            empty=empty,
            force=force,
        )
    except InitError as error:
        raise AppCommandError(f"Init error: {error}") from error
    output.print_init_result(result.root, result.created, result.next_steps)


def run_themes_list() -> None:
    """List bundled themes."""
    for summary in themes_mod.bundled_theme_summaries():
        label = f"{summary.name} - {summary.display_name}"
        details = " / ".join(
            item for item in (summary.category, summary.description) if item
        )
        print(f"{label}: {details}" if details else label)


def run_themes_copy(name: str, dest: Path, *, force: bool) -> None:
    """Copy a bundled theme so it can be customized."""
    try:
        copied = themes_mod.copy_bundled_theme(name, dest, overwrite=force)
    except RecipeError as error:
        raise AppCommandError(f"Theme error: {error}") from error
    print(f"Copied {name} to {output.display_path(copied)}")


def _resolve_config(
    recipe: Path | None,
    *,
    config: Path | None,
    no_config: bool,
    cli_patch: BuildConfigPatch,
) -> BuildConfig:
    """Resolve config layers for a command that needs a recipe."""
    try:
        project_patch = load_project_config(config, enabled=not no_config)
        recipe_arg = recipe.resolve() if recipe is not None else None
        recipe_path = recipe_arg or project_patch.default_book
        if recipe_path is None:
            raise ConfigError(
                "no book provided; pass a book path or set default_book "
                "in papercrown.yaml"
            )
        recipe_patch = load_recipe_build_config(recipe_path)
        return resolve_build_config(
            recipe_arg=recipe_arg,
            project=project_patch,
            recipe=recipe_patch,
            cli=cli_patch,
        )
    except ConfigError as error:
        raise AppCommandError(f"Config error: {error}") from error


def _load_recipe_context(
    recipe: Path | None,
    *,
    config: Path | None,
    no_config: bool,
    cli_patch: BuildConfigPatch,
) -> _RecipeContext:
    """Resolve config, recipe, and manifest for a command."""
    build_config = _resolve_config(
        recipe,
        config=config,
        no_config=no_config,
        cli_patch=cli_patch,
    )
    recipe_obj, manifest = _load_recipe_and_manifest(build_config)
    return _RecipeContext(config=build_config, recipe=recipe_obj, manifest=manifest)


def _load_recipe_and_manifest(config: BuildConfig) -> tuple[Recipe, Manifest]:
    """Load the recipe and manifest for a resolved build config."""
    try:
        recipe = load_recipe(
            config.recipe_path,
            defaults=config.project_defaults,
            defaults_base_dir=config.project_defaults_base_dir,
        )
    except RecipeError as error:
        raise AppCommandError(f"Recipe error: {error}") from error

    try:
        manifest = build_manifest(recipe)
    except Exception as error:
        raise AppCommandError(f"Manifest error: {error}") from error

    output.print_manifest_warnings(manifest.warnings)
    return recipe, manifest


def _discover_tools_for(target: BuildTarget) -> Tools:
    try:
        return discover_tools(require_weasyprint=target is BuildTarget.PDF)
    except RuntimeError as error:
        raise AppCommandError(f"Tool error: {error}") from error


def _ensure_requested_chapter_exists(config: BuildConfig, manifest: Manifest) -> None:
    if not config.single_chapter or manifest.find_chapter(config.single_chapter):
        return
    available = ", ".join(chapter.title for chapter in manifest.all_chapters())
    raise AppCommandError(
        f"Unknown chapter: {config.single_chapter}\nAvailable: {available}"
    )


def _build_request(
    context: _RecipeContext,
    *,
    filler_debug_overlay: bool,
) -> BuildRequest:
    config = context.config
    return BuildRequest(
        recipe=context.recipe,
        manifest=context.manifest,
        target=config.target,
        scope=config.scope,
        profile=config.profile,
        include_art=config.include_art,
        single_chapter=config.single_chapter,
        force=config.force,
        jobs=config.jobs,
        clean_pdf=config.clean_pdf,
        pagination_mode=config.pagination_mode,
        draft_mode=config.draft_mode,
        page_damage_mode=config.page_damage_mode,
        filler_debug_overlay=filler_debug_overlay,
        timings=config.timings,
    )


def _verify_argv(
    config: BuildConfig,
    *,
    no_book: bool,
    strict: bool,
    size_report: bool,
    top_images: int,
    web_assets: bool | None,
) -> list[str]:
    argv = [
        str(config.recipe_path),
        "--profile",
        config.profile.value,
        "--scope",
        config.scope.value,
    ]
    if no_book:
        argv.append("--no-book")
    if strict:
        argv.append("--strict")
    if size_report:
        argv.append("--size-report")
        argv.extend(["--top-images", str(top_images)])
    if web_assets is True:
        argv.append("--web-assets")
    elif web_assets is False:
        argv.append("--no-web-assets")
    return argv
