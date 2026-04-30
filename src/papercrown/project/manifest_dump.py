"""Human-readable manifest formatting."""

from __future__ import annotations

from papercrown.project.manifest_models import Chapter, Manifest


def dump(manifest: Manifest) -> str:
    """Human-readable dump of the resolved manifest."""
    out: list[str] = []
    out.append(f"=== Manifest for {manifest.recipe.title!r} ===")
    out.append(f"Recipe       : {manifest.recipe.recipe_path}")
    out.append(f"Vault overlay: {manifest.recipe.vault_overlay}")
    for name, vs in manifest.recipe.vaults.items():
        out.append(f"  vault[{name}]: {vs.path}")
    out.append(f"Output root : {manifest.recipe.generated_root}")
    out.append("")
    out.append(
        f"Chapters: {len(manifest.chapters)} top-level "
        f"({len(manifest.all_chapters())} total)"
    )
    _dump_chapter_tree(manifest.chapters, out, indent=0)
    if manifest.warnings:
        out.append("")
        out.append("=== Warnings ===")
        for warning in manifest.warnings:
            out.append(f"  {warning}")
    return "\n".join(out)


def _dump_chapter_tree(chapters: list[Chapter], out: list[str], *, indent: int) -> None:
    """Append a text representation of chapters and sources to ``out``."""
    pad = "  " * indent
    for chapter in chapters:
        flags = []
        if chapter.individual_pdf:
            flags.append("individual")
        if chapter.art_path:
            flags.append(f"art={chapter.art_path.name}")
        if chapter.spot_art_path:
            flags.append(f"spot={chapter.spot_art_path.name}")
        if chapter.tailpiece_path:
            flags.append(f"tailpiece={chapter.tailpiece_path.name}")
        if chapter.headpiece_path:
            flags.append(f"headpiece={chapter.headpiece_path.name}")
        if chapter.break_ornament_path:
            flags.append(f"break={chapter.break_ornament_path.name}")
        flag_str = f"  [{','.join(flags)}]" if flags else ""
        out.append(
            f"{pad}- {chapter.title}  (slug={chapter.slug}, "
            f"style={chapter.style}, files={len(chapter.source_files)}){flag_str}"
        )
        for source_file in chapter.source_files:
            out.append(f"{pad}    {source_file.name}")
        if chapter.children:
            _dump_chapter_tree(chapter.children, out, indent=indent + 1)
