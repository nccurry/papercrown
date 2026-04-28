"""Command-line interface for Paper Crown."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Annotated

import click
import typer

from . import manifest as manifest_mod
from . import themes as themes_mod
from . import verify as verify_mod
from .art_audit import (
    audit_recipe_art,
    format_art_audit_markdown,
    format_art_audit_text,
)
from .build import BuildRequest, BuildResult, build_outputs
from .config import (
    BuildConfig,
    BuildConfigPatch,
    ConfigError,
    load_project_config,
    load_recipe_build_config,
    parse_jobs,
    resolve_build_config,
)
from .dependencies import check_dependencies
from .doctor import run_doctor
from .export import Tools, discover_tools
from .manifest import Manifest, build_manifest
from .options import (
    BuildScope,
    BuildTarget,
    DraftMode,
    OutputProfile,
    PageDamageMode,
    PaginationMode,
)
from .recipe import Recipe, RecipeError, load_recipe
from .starter import InitError, StarterBookType, init_project

app = typer.Typer(
    help="Build polished TTRPG PDFs and web exports from Markdown vaults.",
    no_args_is_help=True,
)
deps_app = typer.Typer(help="Dependency diagnostics.")
themes_app = typer.Typer(help="Inspect and copy bundled themes.")
art_app = typer.Typer(help="Inspect and audit recipe art.")
app.add_typer(deps_app, name="deps")
app.add_typer(themes_app, name="themes")
app.add_typer(art_app, name="art")


RecipeArg = Annotated[
    Path | None,
    typer.Argument(
        help="Path to a recipe YAML file. Defaults to papercrown.yaml default_recipe.",
    ),
]
ConfigOpt = Annotated[
    Path | None,
    typer.Option("--config", help="Path to a project papercrown.yaml file."),
]
NoConfigOpt = Annotated[
    bool,
    typer.Option("--no-config", help="Ignore project papercrown.yaml."),
]


def configure_stdio_for_unicode() -> None:
    """Configure stdout/stderr as UTF-8 when the host stream supports it."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8")
        except Exception:
            continue


def _print_manifest_warnings(warnings: list[str]) -> None:
    if not warnings:
        return
    print("Manifest warnings:")
    for warning in warnings:
        print(f"  {warning}")


def _print_tool_paths(tools: Tools) -> None:
    print(f"pandoc         : {tools.pandoc}")
    print(f"obsidian-export: {tools.obsidian_export}")
    if tools.weasyprint:
        print(f"weasyprint     : {tools.weasyprint}")


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(path)


def _print_outputs(result: BuildResult, *, target: BuildTarget) -> None:
    print()
    label = "PDF(s)" if target is BuildTarget.PDF else "web artifact(s)"
    total = len(result.produced) + len(result.skipped)
    if result.skipped:
        print(
            f"Done. {len(result.produced)} {label} written; "
            f"{len(result.skipped)} cached ({total} available):"
        )
    else:
        print(f"Done. {len(result.produced)} {label} written:")
    for path in result.produced + result.skipped:
        try:
            size_kb = path.stat().st_size / 1024
            print(f"  {_display_path(path)}  ({size_kb:.0f} KB)")
        except OSError:
            print(f"  {_display_path(path)}")


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
        recipe_path = recipe_arg or project_patch.default_recipe
        if recipe_path is None:
            raise ConfigError(
                "no recipe provided; pass a recipe path or set default_recipe "
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
        print(f"Config error: {error}", file=sys.stderr)
        raise typer.Exit(2) from error


def _load_recipe_and_manifest(config: BuildConfig) -> tuple[Recipe, Manifest]:
    """Load the recipe and manifest for a resolved build config."""
    try:
        recipe = load_recipe(config.recipe_path)
    except RecipeError as error:
        print(f"Recipe error: {error}", file=sys.stderr)
        raise typer.Exit(2) from error

    try:
        manifest = build_manifest(recipe)
    except Exception as error:
        print(f"Manifest error: {error}", file=sys.stderr)
        raise typer.Exit(2) from error

    _print_manifest_warnings(manifest.warnings)
    return recipe, manifest


def _build_cli_patch(
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
    if timings is None and os.environ.get("PAPERCROWN_TIMINGS") == "1":
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


@app.command("build")
def build_command(
    recipe: RecipeArg = None,
    target: Annotated[
        BuildTarget | None,
        typer.Option("--target", help="Output target."),
    ] = None,
    scope: Annotated[
        BuildScope | None,
        typer.Option("--scope", help="PDF output scope."),
    ] = None,
    profile: Annotated[
        OutputProfile | None,
        typer.Option("--profile", help="PDF output profile."),
    ] = None,
    chapter: Annotated[
        str | None,
        typer.Option(
            "--chapter",
            help="Build one section by slug or title; implies --scope sections.",
        ),
    ] = None,
    include_art: Annotated[
        bool | None,
        typer.Option("--art/--no-art", help="Include recipe art assets."),
    ] = None,
    force: Annotated[
        bool | None,
        typer.Option("--force/--no-force", help="Refresh export/cache state."),
    ] = None,
    jobs: Annotated[
        str | None,
        typer.Option("--jobs", help="Parallel PDF jobs: integer or 'auto'."),
    ] = None,
    clean_pdf: Annotated[
        bool | None,
        typer.Option("--clean-pdf/--no-clean-pdf", help="Run final PDF cleanup."),
    ] = None,
    pagination: Annotated[
        PaginationMode | None,
        typer.Option("--pagination", help="Pagination analysis/fix mode."),
    ] = None,
    draft_mode: Annotated[
        DraftMode | None,
        typer.Option("--draft-mode", help="Draft build behavior."),
    ] = None,
    page_damage: Annotated[
        PageDamageMode | None,
        typer.Option("--page-damage", help="Page damage application mode."),
    ] = None,
    timings: Annotated[
        bool | None,
        typer.Option("--timings/--no-timings", help="Print stage timing logs."),
    ] = None,
    config: ConfigOpt = None,
    no_config: NoConfigOpt = False,
) -> None:
    """Build PDFs or the static web artifact."""
    build_config = _resolve_config(
        recipe,
        config=config,
        no_config=no_config,
        cli_patch=_build_cli_patch(
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
    recipe_obj, manifest = _load_recipe_and_manifest(build_config)

    if (
        build_config.single_chapter
        and manifest.find_chapter(build_config.single_chapter) is None
    ):
        print(f"Unknown chapter: {build_config.single_chapter}", file=sys.stderr)
        print(
            "Available: "
            + ", ".join(chapter.title for chapter in manifest.all_chapters()),
            file=sys.stderr,
        )
        raise typer.Exit(2)

    try:
        tools = discover_tools(
            require_weasyprint=build_config.target is BuildTarget.PDF
        )
    except RuntimeError as error:
        print(f"Tool error: {error}", file=sys.stderr)
        raise typer.Exit(2) from error
    _print_tool_paths(tools)

    request = BuildRequest(
        recipe=recipe_obj,
        manifest=manifest,
        target=build_config.target,
        scope=build_config.scope,
        profile=build_config.profile,
        include_art=build_config.include_art,
        single_chapter=build_config.single_chapter,
        force=build_config.force,
        jobs=build_config.jobs,
        clean_pdf=build_config.clean_pdf,
        pagination_mode=build_config.pagination_mode,
        draft_mode=build_config.draft_mode,
        page_damage_mode=build_config.page_damage_mode,
        timings=build_config.timings,
    )
    result = build_outputs(tools, request, log=print)
    _print_outputs(result, target=build_config.target)


@app.command("manifest")
def manifest_command(
    recipe: RecipeArg = None,
    config: ConfigOpt = None,
    no_config: NoConfigOpt = False,
) -> None:
    """Print the resolved build manifest."""
    build_config = _resolve_config(
        recipe,
        config=config,
        no_config=no_config,
        cli_patch=BuildConfigPatch(),
    )
    _recipe, manifest = _load_recipe_and_manifest(build_config)
    print(manifest_mod.dump(manifest))


@art_app.command("audit")
def art_audit_command(
    recipe: RecipeArg = None,
    output_format: Annotated[
        str,
        typer.Option(
            "--format",
            help="Output format: text or markdown.",
        ),
    ] = "text",
    strict: Annotated[
        bool,
        typer.Option("--strict", help="Fail on warnings as well as errors."),
    ] = False,
    config: ConfigOpt = None,
    no_config: NoConfigOpt = False,
) -> None:
    """Audit the recipe art library against the Paper Crown art contract."""
    if output_format not in {"text", "markdown"}:
        print("--format must be 'text' or 'markdown'", file=sys.stderr)
        raise typer.Exit(2)
    build_config = _resolve_config(
        recipe,
        config=config,
        no_config=no_config,
        cli_patch=BuildConfigPatch(),
    )
    recipe_obj, manifest = _load_recipe_and_manifest(build_config)
    result = audit_recipe_art(recipe_obj, manifest)
    if output_format == "markdown":
        print(format_art_audit_markdown(result))
    else:
        print(format_art_audit_text(result))
    raise typer.Exit(result.exit_code(strict=strict))


@app.command("doctor")
def doctor_command(
    recipe: RecipeArg = None,
    target: Annotated[
        BuildTarget | None,
        typer.Option("--target", help="Diagnostics target."),
    ] = None,
    strict: Annotated[
        bool,
        typer.Option("--strict", help="Fail on warnings as well as errors."),
    ] = False,
    config: ConfigOpt = None,
    no_config: NoConfigOpt = False,
) -> None:
    """Run preflight diagnostics and exit without rendering."""
    build_config = _resolve_config(
        recipe,
        config=config,
        no_config=no_config,
        cli_patch=_build_cli_patch(target=target),
    )
    recipe_obj, manifest = _load_recipe_and_manifest(build_config)
    report = run_doctor(
        recipe_obj,
        manifest,
        target=build_config.target,
        strict=strict,
        log=print,
    )
    raise typer.Exit(report.exit_code(strict=strict))


@deps_app.command("check")
def deps_check_command(
    manifest: Annotated[
        Path | None,
        typer.Option("--manifest", help="Path to dependencies.yaml."),
    ] = None,
    strict: Annotated[
        bool,
        typer.Option("--strict", help="Fail on warnings as well as errors."),
    ] = False,
    updates_only: Annotated[
        bool,
        typer.Option("--updates-only", help="Only print dependency issues."),
    ] = False,
) -> None:
    """Report runtime, dev, tool, native, and bundled-asset dependencies."""
    report = check_dependencies(manifest)
    print(report.format_text(updates_only=updates_only))
    raise typer.Exit(report.exit_code(strict=strict))


@app.command("verify")
def verify_command(
    recipe: RecipeArg = None,
    profile: Annotated[
        OutputProfile | None,
        typer.Option("--profile", help="PDF output profile to verify."),
    ] = None,
    scope: Annotated[
        BuildScope | None,
        typer.Option("--scope", help="PDF output scope to verify."),
    ] = None,
    no_book: Annotated[
        bool,
        typer.Option("--no-book", help="Skip checking the combined book PDF."),
    ] = False,
    strict: Annotated[
        bool,
        typer.Option(
            "--strict",
            help="Fail on content mismatches as well as missing files.",
        ),
    ] = False,
    size_report: Annotated[
        bool,
        typer.Option("--size-report", help="Print PDF size and image diagnostics."),
    ] = False,
    top_images: Annotated[
        int,
        typer.Option("--top-images", help="Largest embedded images to report."),
    ] = 5,
    config: ConfigOpt = None,
    no_config: NoConfigOpt = False,
) -> None:
    """Verify generated PDFs against the recipe manifest."""
    build_config = _resolve_config(
        recipe,
        config=config,
        no_config=no_config,
        cli_patch=_build_cli_patch(profile=profile, scope=scope),
    )
    argv = [
        str(build_config.recipe_path),
        "--profile",
        build_config.profile.value,
        "--scope",
        build_config.scope.value,
    ]
    if no_book:
        argv.append("--no-book")
    if strict:
        argv.append("--strict")
    if size_report:
        argv.append("--size-report")
        argv.extend(["--top-images", str(top_images)])
    raise typer.Exit(verify_mod.main(argv))


@app.command("init")
def init_command(
    path: Annotated[
        Path,
        typer.Argument(help="Directory to initialize."),
    ] = Path("."),
    title: Annotated[
        str | None,
        typer.Option("--title", help="Book title for the starter recipe."),
    ] = None,
    subtitle: Annotated[
        str | None,
        typer.Option("--subtitle", help="Optional subtitle for the starter recipe."),
    ] = None,
    theme: Annotated[
        str,
        typer.Option("--theme", help="Bundled or project theme name."),
    ] = "clean-srd",
    book_type: Annotated[
        StarterBookType,
        typer.Option("--book-type", help="Starter content shape."),
    ] = StarterBookType.CAMPAIGN,
    vault: Annotated[
        Path | None,
        typer.Option("--vault", help="Vault directory to create or reference."),
    ] = None,
    with_cover: Annotated[
        bool,
        typer.Option("--with-cover/--no-cover", help="Enable a generated cover page."),
    ] = True,
    empty: Annotated[
        bool,
        typer.Option("--empty", help="Create only config and empty folders."),
    ] = False,
    force: Annotated[
        bool,
        typer.Option("--force", help="Overwrite scaffold files when present."),
    ] = False,
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
        print(f"Init error: {error}", file=sys.stderr)
        raise typer.Exit(2) from error
    print(f"Initialized Paper Crown project at {_display_path(result.root)}")
    for created in result.created:
        print(f"  {_display_path(created)}")
    if result.next_steps:
        print()
        print("Next steps:")
        for step in result.next_steps:
            print(f"  {step}")


@themes_app.command("list")
def themes_list_command() -> None:
    """List bundled themes."""
    for summary in themes_mod.bundled_theme_summaries():
        label = f"{summary.name} - {summary.display_name}"
        details = " / ".join(
            item for item in (summary.category, summary.description) if item
        )
        print(f"{label}: {details}" if details else label)


@themes_app.command("copy")
def themes_copy_command(
    name: Annotated[str, typer.Argument(help="Bundled theme name.")],
    dest: Annotated[Path, typer.Argument(help="Destination directory.")],
    force: Annotated[
        bool,
        typer.Option("--force", help="Allow copying into an existing directory."),
    ] = False,
) -> None:
    """Copy a bundled theme so it can be customized."""
    try:
        copied = themes_mod.copy_bundled_theme(name, dest, overwrite=force)
    except RecipeError as error:
        print(f"Theme error: {error}", file=sys.stderr)
        raise typer.Exit(2) from error
    print(f"Copied {name} to {_display_path(copied)}")


def main(argv: list[str] | None = None) -> int:
    """Run the Paper Crown CLI and return a process-style exit code."""
    configure_stdio_for_unicode()
    prog_name = Path(sys.argv[0]).name if argv is None else "papercrown"
    try:
        result = app(args=argv, prog_name=prog_name, standalone_mode=False)
    except typer.Exit as error:
        return int(error.exit_code or 0)
    except click.ClickException as error:
        error.show()
        return int(error.exit_code)
    if isinstance(result, int):
        return result
    return 0
