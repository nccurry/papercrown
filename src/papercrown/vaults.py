"""Vault indexing and wikilink resolution.

A `VaultIndex` holds one or more vaults in priority order (later wins) and
resolves Obsidian wikilink targets through the stack.

Real Obsidian wikilink syntax we handle:

    [[Goblin]]                              -- bare stem
    [[Goblin|Display]]                      -- stem + alias
    [[Heroes/Ancestries/Goblin]]            -- path-qualified
    [[Heroes/Ancestries/Goblin|Goblin]]     -- path + alias
    [[Goblin#Heading]]                      -- heading anchor
    [[Goblin#^block-id]]                    -- block reference
    [[#Heading-in-self]]                    -- self-link (resolved to None target)

Resolution strategy:
  1. If `path_or_stem` looks like a path (contains a slash), try literal
     subpath match in each vault by overlay priority. Match if the relative
     path (with or without `.md`) exists in that vault.
  2. Otherwise, treat as a stem and find any `<stem>.md` in any vault by
     overlay priority. If multiple matches in one vault, the one closest to
     the vault root wins (Obsidian's tiebreaking).
  3. `prefer_vault` (when given) bypasses overlay and only searches that vault
     first; falls back to overlay if not found.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# WikilinkTarget
# ---------------------------------------------------------------------------


_WIKILINK_FULL_RE = re.compile(r"^\[\[(?P<inner>.+?)\]\]$")


@dataclass(frozen=True)
class WikilinkTarget:
    """Parsed Obsidian wikilink target.

    Examples:
        WikilinkTarget.parse("Goblin")
            -> path_or_stem="Goblin", alias=None, heading=None, block_id=None
        WikilinkTarget.parse("Heroes/Ancestries/Goblin|Goblin")
            -> path_or_stem="Heroes/Ancestries/Goblin", alias="Goblin"
        WikilinkTarget.parse("Spell List#Fire Spells")
            -> path_or_stem="Spell List", heading="Fire Spells"
        WikilinkTarget.parse("[[Goblin]]")  # also accepts the brackets
            -> path_or_stem="Goblin"
    """

    raw: str
    path_or_stem: str
    alias: str | None = None
    heading: str | None = None
    block_id: str | None = None

    @classmethod
    def parse(cls, raw: str) -> WikilinkTarget:
        """Parse an Obsidian wikilink target, with or without ``[[...]]``."""
        if raw is None:
            raise ValueError("WikilinkTarget.parse: raw is None")
        original = raw
        text = raw.strip()
        # Optionally strip surrounding [[ ]]
        m = _WIKILINK_FULL_RE.match(text)
        if m:
            text = m.group("inner").strip()

        # Split alias on first |
        alias: str | None = None
        if "|" in text:
            text, alias_part = text.split("|", 1)
            text = text.strip()
            alias = alias_part.strip() or None

        # Split heading / block on # / #^
        heading: str | None = None
        block_id: str | None = None
        if "#" in text:
            text, anchor = text.split("#", 1)
            text = text.strip()
            anchor = anchor.strip()
            if anchor.startswith("^"):
                block_id = anchor[1:].strip() or None
            else:
                heading = anchor or None

        path_or_stem = text.replace("\\", "/").strip("/")
        return cls(
            raw=original,
            path_or_stem=path_or_stem,
            alias=alias,
            heading=heading,
            block_id=block_id,
        )

    @property
    def is_path_qualified(self) -> bool:
        """Return whether the target names a vault-relative path."""
        return "/" in self.path_or_stem

    @property
    def display_text(self) -> str:
        """The string a renderer should show in place of [[X|Y]] -> "Y"."""
        if self.alias:
            return self.alias
        # For path-qualified bare links, Obsidian uses just the stem
        if self.is_path_qualified:
            return self.path_or_stem.rsplit("/", 1)[-1]
        return self.path_or_stem


# ---------------------------------------------------------------------------
# Vault & index
# ---------------------------------------------------------------------------


@dataclass
class Vault:
    """A single Obsidian vault indexed by stem and relative path."""

    name: str
    root: Path
    # stem -> sorted list of paths (closest-to-root first)
    _by_stem: dict[str, list[Path]] = field(default_factory=dict)
    # normalized rel-path-without-ext -> Path
    _by_relpath: dict[str, Path] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.root = self.root.resolve()
        self._build_indexes()

    def _build_indexes(self) -> None:
        if not self.root.is_dir():
            return
        for md in self.root.rglob("*.md"):
            try:
                rel = md.relative_to(self.root)
            except ValueError:
                continue
            stem = md.stem
            self._by_stem.setdefault(stem, []).append(md)
            # Index path-qualified key WITHOUT extension, normalized to forward slashes
            rel_no_ext = rel.with_suffix("").as_posix()
            self._by_relpath[rel_no_ext] = md

        # Sort each stem bucket: shallower (fewer path parts) wins
        for paths in self._by_stem.values():
            paths.sort(key=lambda p: (len(p.relative_to(self.root).parts), str(p)))

    def resolve_path_qualified(self, rel_no_ext: str) -> Path | None:
        """Look up a vault-relative subpath (without `.md`)."""
        norm = rel_no_ext.replace("\\", "/").strip("/")
        return self._by_relpath.get(norm)

    def resolve_stem(self, stem: str) -> Path | None:
        """Resolve a note stem to the closest matching markdown path."""
        bucket = self._by_stem.get(stem)
        if not bucket:
            return None
        return bucket[0]


class VaultIndex:
    """Cross-vault file index honoring overlay priority order.

    The vaults list is in PRIORITY order with the FIRST being LOWEST priority
    (later wins). This matches recipe.vault_overlay semantics.
    """

    def __init__(self, vaults_in_priority_order: list[Vault]) -> None:
        self._vaults = list(vaults_in_priority_order)
        self._by_name = {v.name: v for v in self._vaults}

    @property
    def vaults(self) -> list[Vault]:
        """Return indexed vaults in recipe overlay priority order."""
        return list(self._vaults)

    def vault_by_name(self, name: str) -> Vault | None:
        """Return a vault by alias, or ``None`` if it is not indexed."""
        return self._by_name.get(name)

    def resolve(
        self,
        target: WikilinkTarget | str,
        prefer_vault: str | None = None,
    ) -> Path | None:
        """Resolve a wikilink target to an absolute path, or None if not found.

        If `prefer_vault` is given, that vault is searched first; on miss, fall
        through to the overlay stack in reverse-priority order (highest wins).
        """
        if isinstance(target, str):
            target = WikilinkTarget.parse(target)

        # Self-link (just #anchor) is unresolvable
        if not target.path_or_stem:
            return None

        ordered: list[Vault] = []
        if prefer_vault and prefer_vault in self._by_name:
            ordered.append(self._by_name[prefer_vault])

        # Higher priority (later in vault_overlay) wins, so iterate in REVERSE
        for v in reversed(self._vaults):
            if v not in ordered:
                ordered.append(v)

        for v in ordered:
            hit = self._resolve_in_vault(v, target)
            if hit is not None:
                return hit
        return None

    def _resolve_in_vault(self, vault: Vault, target: WikilinkTarget) -> Path | None:
        if target.is_path_qualified:
            # Try the literal subpath first
            hit = vault.resolve_path_qualified(target.path_or_stem)
            if hit is not None:
                return hit
            # Fallback: try the bare stem (last segment) -- mirrors Obsidian leniency
            stem = target.path_or_stem.rsplit("/", 1)[-1]
            return vault.resolve_stem(stem)
        return vault.resolve_stem(target.path_or_stem)

    def all_md_files(self) -> Iterable[Path]:
        """Yield every indexed markdown file once."""
        seen: set[Path] = set()
        for v in self._vaults:
            for paths in v._by_stem.values():
                for p in paths:
                    if p not in seen:
                        seen.add(p)
                        yield p

    @classmethod
    def from_recipe_paths(
        cls,
        vault_specs_in_priority_order: list[tuple[str, Path]],
    ) -> VaultIndex:
        """Build from a list of (name, path) tuples in priority order."""
        return cls([Vault(name=n, root=p) for n, p in vault_specs_in_priority_order])
