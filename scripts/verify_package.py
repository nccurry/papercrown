"""Verify the built wheel contains Paper Crown runtime resources."""

from __future__ import annotations

import configparser
import sys
import zipfile
from email.parser import Parser
from pathlib import Path

# Repository root used to locate build artifacts from any working directory.
ROOT = Path(__file__).resolve().parents[1]
# Directory where the package build writes wheels and source distributions.
DIST = ROOT / "dist"
# Source package root used to detect stale files copied from old build output.
SOURCE_PACKAGE = ROOT / "src" / "papercrown"
# SPDX license expression expected in the built wheel metadata.
LICENSE_EXPRESSION = "AGPL-3.0-or-later"
# Wheel member suffixes that prove runtime resources were packaged.
REQUIRED_SUFFIXES = (
    "dist-info/licenses/LICENSE",
    "dist-info/licenses/THIRD_PARTY_LICENSES.md",
    "papercrown/resources/styles/core/00-tokens.css",
    "papercrown/resources/styles/core/50-ttrpg-components.css",
    "papercrown/resources/templates/book.html",
    "papercrown/resources/filters/internal-links.lua",
    "papercrown/resources/themes/clean-srd/theme.yaml",
    "papercrown/resources/themes/clean-srd/tokens.css",
    "papercrown/resources/themes/clean-srd/components.css",
    "papercrown/resources/assets/fonts/Rajdhani-Regular.ttf",
    "papercrown/resources/assets/textures/paper-grain.png",
)


def _latest_wheel() -> Path:
    wheels = sorted(
        DIST.glob("papercrown-*.whl"),
        key=lambda path: path.stat().st_mtime,
    )
    if not wheels:
        raise RuntimeError("no papercrown wheel found in dist/")
    return wheels[-1]


def _unexpected_package_files(names: set[str]) -> list[str]:
    """Return package files in the wheel that are absent from ``src/papercrown``."""
    unexpected: list[str] = []
    for name in names:
        if not name.startswith("papercrown/") or name.endswith("/"):
            continue
        relative = Path(*name.split("/")[1:])
        if not (SOURCE_PACKAGE / relative).is_file():
            unexpected.append(name)
    return sorted(unexpected)


def main() -> int:
    """Return non-zero when the built wheel is missing expected metadata."""
    wheel = _latest_wheel()
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        missing = [
            suffix
            for suffix in REQUIRED_SUFFIXES
            if not any(name.endswith(suffix) for name in names)
        ]
        unexpected = _unexpected_package_files(names)
        entry_points_name = next(
            name for name in names if name.endswith(".dist-info/entry_points.txt")
        )
        parser = configparser.ConfigParser()
        parser.read_string(archive.read(entry_points_name).decode("utf-8"))

        metadata_name = next(
            name for name in names if name.endswith(".dist-info/METADATA")
        )
        metadata = Parser().parsestr(archive.read(metadata_name).decode("utf-8"))
        if metadata.get("License-Expression") != LICENSE_EXPRESSION:
            missing.append(f"License-Expression: {LICENSE_EXPRESSION}")
    scripts = dict(parser.items("console_scripts"))
    if scripts.get("papercrown") != "papercrown.app.cli:main":
        missing.append("console_scripts.papercrown")
    if "papercrown-verify" in scripts:
        missing.append("removed console_scripts.papercrown-verify")
    if missing or unexpected:
        print("Package verification failed:")
        if missing:
            print("  Missing or invalid:")
            for item in missing:
                print(f"    {item}")
        if unexpected:
            print("  Unexpected package files:")
            for item in unexpected:
                print(f"    {item}")
        return 1
    print(f"Package verification passed: {wheel.name}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as error:
        print(f"Package verification failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
