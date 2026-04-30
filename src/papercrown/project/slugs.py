"""Shared slug helpers for project and assembly contracts."""

from __future__ import annotations

import re


def slugify(s: str) -> str:
    """Canonical chapter / anchor slug.

    Lowercase, runs of non-(letter/digit/underscore/hyphen) collapsed to a
    single hyphen, with leading/trailing hyphens stripped.

    Must stay in sync with `slugify` in `filters/internal-links.lua`. Any
    change to this rule needs the matching change in the Lua filter or
    cross-document anchor resolution will silently start missing.
    """
    slug = s.lower().strip()
    slug = re.sub(r"[^a-z0-9_-]+", "-", slug)
    return slug.strip("-") or "untitled"
