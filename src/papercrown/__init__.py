"""Recipe-driven PDF generation for TTRPG markdown vaults."""

from __future__ import annotations

import os

if os.name == "nt":
    os.environ.setdefault("GIO_USE_VFS", "local")
