"""Console output helpers for the Paper Crown app layer."""

from __future__ import annotations

from pathlib import Path

from papercrown.build.options import BuildTarget
from papercrown.build.requests import BuildResult
from papercrown.system.export import Tools


def print_manifest_warnings(warnings: list[str]) -> None:
    """Print manifest warnings in the CLI's compact format."""
    if not warnings:
        return
    print("Manifest warnings:")
    for warning in warnings:
        print(f"  {warning}")


def print_tool_paths(tools: Tools) -> None:
    """Print external tool paths discovered for a command."""
    print(f"pandoc         : {tools.pandoc}")
    print(f"obsidian-export: {tools.obsidian_export}")
    if tools.weasyprint:
        print(f"weasyprint     : {tools.weasyprint}")


def display_path(path: Path) -> str:
    """Return a path relative to the current project when possible."""
    try:
        return str(path.resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(path)


def print_build_outputs(result: BuildResult, *, target: BuildTarget) -> None:
    """Print artifacts produced or reused by a build command."""
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
            print(f"  {display_path(path)}  ({size_kb:.0f} KB)")
        except OSError:
            print(f"  {display_path(path)}")


def print_init_result(
    result_root: Path,
    created: list[Path],
    next_steps: list[str],
) -> None:
    """Print project initialization results."""
    print(f"Initialized Paper Crown project at {display_path(result_root)}")
    for path in created:
        print(f"  {display_path(path)}")
    if not next_steps:
        return
    print()
    print("Next steps:")
    for step in next_steps:
        print(f"  {step}")
