"""Recipe-driven PDF generation for TTRPG markdown vaults."""

from __future__ import annotations

import os
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

try:
    __version__ = version("papercrown")
except PackageNotFoundError:
    __version__ = "0+unknown"

if os.name == "nt":
    os.environ.setdefault("GIO_USE_VFS", "local")

    dll_dirs = [
        Path(value.strip().strip('"'))
        for value in os.environ.get("WEASYPRINT_DLL_DIRECTORIES", "").split(os.pathsep)
        if value.strip()
    ]
    default_msys_ucrt = Path(r"C:\msys64\ucrt64\bin")
    if default_msys_ucrt.is_dir() and default_msys_ucrt not in dll_dirs:
        dll_dirs.append(default_msys_ucrt)

    if dll_dirs:
        preferred = [str(path) for path in dll_dirs if path.is_dir()]
        current = [
            value
            for value in os.environ.get("PATH", "").split(os.pathsep)
            if value.strip()
        ]
        seen: set[str] = set()
        path_entries: list[str] = []
        for value in preferred + current:
            normalized = os.path.normcase(os.path.normpath(value))
            if normalized in seen:
                continue
            seen.add(normalized)
            path_entries.append(value)
        os.environ["PATH"] = os.pathsep.join(path_entries)
