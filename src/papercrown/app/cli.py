"""Command-line interface for Paper Crown."""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from typing import Annotated

import click
import typer

from papercrown.app import actions
from papercrown.build.options import (
    BuildScope,
    BuildTarget,
    DraftMode,
    OutputProfile,
    PageDamageMode,
    PaginationMode,
)
from papercrown.project.starter import StarterBookType

APP_HELP = "Build polished TTRPG PDFs and web exports from Markdown vaults."
DEPS_HELP = "Dependency diagnostics."
THEMES_HELP = "Inspect and copy bundled themes."
ART_HELP = "Inspect and audit recipe art."

DEFAULT_INIT_THEME = "clean-srd"
DEFAULT_VERIFY_TOP_IMAGES = 5


RecipeArg = Annotated[
    Path | None,
    typer.Argument(
        help="Path to a book YAML file. Defaults to papercrown.yaml default_book.",
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

BuildTargetOpt = Annotated[
    BuildTarget | None,
    typer.Option("--target", help="Output target."),
]
BuildScopeOpt = Annotated[
    BuildScope | None,
    typer.Option("--scope", help="PDF output scope."),
]
OutputProfileOpt = Annotated[
    OutputProfile | None,
    typer.Option("--profile", help="PDF output profile."),
]
ChapterOpt = Annotated[
    str | None,
    typer.Option(
        "--chapter",
        help="Build one section by slug or title; implies --scope sections.",
    ),
]
IncludeArtOpt = Annotated[
    bool | None,
    typer.Option("--art/--no-art", help="Include recipe art assets."),
]
ForceOpt = Annotated[
    bool | None,
    typer.Option("--force/--no-force", help="Refresh export/cache state."),
]
JobsOpt = Annotated[
    str | None,
    typer.Option("--jobs", help="Parallel PDF jobs: integer or 'auto'."),
]
CleanPdfOpt = Annotated[
    bool | None,
    typer.Option("--clean-pdf/--no-clean-pdf", help="Run final PDF cleanup."),
]
PaginationOpt = Annotated[
    PaginationMode | None,
    typer.Option("--pagination", help="Pagination analysis/fix mode."),
]
DraftModeOpt = Annotated[
    DraftMode | None,
    typer.Option("--draft-mode", help="Draft build behavior."),
]
PageDamageOpt = Annotated[
    PageDamageMode | None,
    typer.Option("--page-damage", help="Page damage application mode."),
]
FillerDebugOverlayOpt = Annotated[
    bool,
    typer.Option(
        "--filler-debug-overlay",
        help="Write a sibling PDF annotated with filler decisions.",
    ),
]
TimingsOpt = Annotated[
    bool | None,
    typer.Option("--timings/--no-timings", help="Print stage timing logs."),
]

StrictOpt = Annotated[
    bool,
    typer.Option("--strict", help="Fail on warnings as well as errors."),
]
ArtFormatOpt = Annotated[
    str,
    typer.Option("--format", help="Output format: text or markdown."),
]
ManifestPathOpt = Annotated[
    Path | None,
    typer.Option("--manifest", help="Path to dependencies.yaml."),
]
UpdatesOnlyOpt = Annotated[
    bool,
    typer.Option("--updates-only", help="Only print dependency issues."),
]
NoBookOpt = Annotated[
    bool,
    typer.Option("--no-book", help="Skip checking the combined book PDF."),
]
VerifyStrictOpt = Annotated[
    bool,
    typer.Option(
        "--strict",
        help="Fail on content mismatches as well as missing files.",
    ),
]
SizeReportOpt = Annotated[
    bool,
    typer.Option("--size-report", help="Print PDF size and image diagnostics."),
]
TopImagesOpt = Annotated[
    int,
    typer.Option("--top-images", help="Largest embedded images to report."),
]

InitPathArg = Annotated[
    Path,
    typer.Argument(help="Directory to initialize."),
]
InitTitleOpt = Annotated[
    str | None,
    typer.Option("--title", help="Book title for the starter recipe."),
]
InitSubtitleOpt = Annotated[
    str | None,
    typer.Option("--subtitle", help="Optional subtitle for the starter recipe."),
]
InitThemeOpt = Annotated[
    str,
    typer.Option("--theme", help="Bundled or project theme name."),
]
InitBookTypeOpt = Annotated[
    StarterBookType,
    typer.Option("--book-type", help="Starter content shape."),
]
InitVaultOpt = Annotated[
    Path | None,
    typer.Option("--vault", help="Vault directory to create or reference."),
]
InitCoverOpt = Annotated[
    bool,
    typer.Option("--with-cover/--no-cover", help="Enable a generated cover page."),
]
InitEmptyOpt = Annotated[
    bool,
    typer.Option("--empty", help="Create only config and empty folders."),
]
InitForceOpt = Annotated[
    bool,
    typer.Option("--force", help="Overwrite scaffold files when present."),
]

ThemeNameArg = Annotated[str, typer.Argument(help="Bundled theme name.")]
ThemeDestArg = Annotated[Path, typer.Argument(help="Destination directory.")]
ThemeForceOpt = Annotated[
    bool,
    typer.Option("--force", help="Allow copying into an existing directory."),
]
ContactSheetOutputOpt = Annotated[
    Path | None,
    typer.Option("--output", help="HTML contact sheet path."),
]


def create_app() -> typer.Typer:
    """Create the Paper Crown command tree."""
    root = typer.Typer(help=APP_HELP, no_args_is_help=True)
    deps = typer.Typer(help=DEPS_HELP)
    themes = typer.Typer(help=THEMES_HELP)
    art = typer.Typer(help=ART_HELP)

    root.add_typer(deps, name="deps")
    root.add_typer(themes, name="themes")
    root.add_typer(art, name="art")

    root.command("build")(build_command)
    root.command("manifest")(manifest_command)
    root.command("doctor")(doctor_command)
    root.command("verify")(verify_command)
    root.command("init")(init_command)

    deps.command("check")(deps_check_command)
    themes.command("list")(themes_list_command)
    themes.command("copy")(themes_copy_command)
    art.command("audit")(art_audit_command)
    art.command("contact-sheet")(art_contact_sheet_command)
    return root


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


def _run(action: Callable[[], int | None]) -> None:
    try:
        exit_code = action()
    except actions.AppCommandError as error:
        print(error, file=sys.stderr)
        raise typer.Exit(error.exit_code) from error
    if exit_code:
        raise typer.Exit(exit_code)


def build_command(
    recipe: RecipeArg = None,
    target: BuildTargetOpt = None,
    scope: BuildScopeOpt = None,
    profile: OutputProfileOpt = None,
    chapter: ChapterOpt = None,
    include_art: IncludeArtOpt = None,
    force: ForceOpt = None,
    jobs: JobsOpt = None,
    clean_pdf: CleanPdfOpt = None,
    pagination: PaginationOpt = None,
    draft_mode: DraftModeOpt = None,
    page_damage: PageDamageOpt = None,
    filler_debug_overlay: FillerDebugOverlayOpt = False,
    timings: TimingsOpt = None,
    config: ConfigOpt = None,
    no_config: NoConfigOpt = False,
) -> None:
    """Build PDFs or the static web artifact."""
    _run(
        lambda: actions.run_build(
            recipe,
            config=config,
            no_config=no_config,
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
            filler_debug_overlay=filler_debug_overlay,
            timings=timings,
        )
    )


def manifest_command(
    recipe: RecipeArg = None,
    config: ConfigOpt = None,
    no_config: NoConfigOpt = False,
) -> None:
    """Print the resolved build manifest."""
    _run(
        lambda: actions.run_manifest(
            recipe,
            config=config,
            no_config=no_config,
        )
    )


def art_audit_command(
    recipe: RecipeArg = None,
    output_format: ArtFormatOpt = "text",
    strict: StrictOpt = False,
    config: ConfigOpt = None,
    no_config: NoConfigOpt = False,
) -> None:
    """Audit the recipe art library against the Paper Crown art contract."""
    _run(
        lambda: actions.run_art_audit(
            recipe,
            output_format=output_format,
            strict=strict,
            config=config,
            no_config=no_config,
        )
    )


def art_contact_sheet_command(
    recipe: RecipeArg = None,
    output: ContactSheetOutputOpt = None,
    config: ConfigOpt = None,
    no_config: NoConfigOpt = False,
) -> None:
    """Write an HTML visual inventory of the recipe art library."""
    _run(
        lambda: actions.run_art_contact_sheet(
            recipe,
            output_path=output,
            config=config,
            no_config=no_config,
        )
    )


def doctor_command(
    recipe: RecipeArg = None,
    target: BuildTargetOpt = None,
    strict: StrictOpt = False,
    config: ConfigOpt = None,
    no_config: NoConfigOpt = False,
) -> None:
    """Run preflight diagnostics and exit without rendering."""
    _run(
        lambda: actions.run_doctor(
            recipe,
            target=target,
            strict=strict,
            config=config,
            no_config=no_config,
        )
    )


def deps_check_command(
    manifest: ManifestPathOpt = None,
    strict: StrictOpt = False,
    updates_only: UpdatesOnlyOpt = False,
) -> None:
    """Report runtime, dev, tool, native, and bundled-asset dependencies."""
    _run(
        lambda: actions.run_deps_check(
            manifest,
            strict=strict,
            updates_only=updates_only,
        )
    )


def verify_command(
    recipe: RecipeArg = None,
    profile: OutputProfileOpt = None,
    scope: BuildScopeOpt = None,
    no_book: NoBookOpt = False,
    strict: VerifyStrictOpt = False,
    size_report: SizeReportOpt = False,
    top_images: TopImagesOpt = DEFAULT_VERIFY_TOP_IMAGES,
    config: ConfigOpt = None,
    no_config: NoConfigOpt = False,
) -> None:
    """Verify generated PDFs against the recipe manifest."""
    _run(
        lambda: actions.run_verify(
            recipe,
            profile=profile,
            scope=scope,
            no_book=no_book,
            strict=strict,
            size_report=size_report,
            top_images=top_images,
            config=config,
            no_config=no_config,
        )
    )


def init_command(
    path: InitPathArg = Path("."),
    title: InitTitleOpt = None,
    subtitle: InitSubtitleOpt = None,
    theme: InitThemeOpt = DEFAULT_INIT_THEME,
    book_type: InitBookTypeOpt = StarterBookType.CAMPAIGN,
    vault: InitVaultOpt = None,
    with_cover: InitCoverOpt = True,
    empty: InitEmptyOpt = False,
    force: InitForceOpt = False,
) -> None:
    """Create a new Paper Crown project scaffold."""
    _run(
        lambda: actions.run_init(
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
    )


def themes_list_command() -> None:
    """List bundled themes."""
    _run(actions.run_themes_list)


def themes_copy_command(
    name: ThemeNameArg,
    dest: ThemeDestArg,
    force: ThemeForceOpt = False,
) -> None:
    """Copy a bundled theme so it can be customized."""
    _run(lambda: actions.run_themes_copy(name, dest, force=force))


app = create_app()


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
