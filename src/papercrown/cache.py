"""Small content-addressed caches for exports and rendered artifacts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypeAlias

JsonValue: TypeAlias = (
    str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
)
CACHE_SCHEMA_VERSION = 1


def fingerprint_files(
    paths: Iterable[Path],
    *,
    extra: Mapping[str, JsonValue] | None = None,
) -> str:
    """Return a stable SHA-256 fingerprint for paths and extra metadata.

    Missing files are included as explicit markers rather than ignored, so a
    cache key cannot accidentally match after an input disappears.
    """
    digest = hashlib.sha256()
    payload: dict[str, JsonValue] = {
        "schema": CACHE_SCHEMA_VERSION,
        "extra": dict(extra or {}),
    }
    digest.update(json.dumps(payload, sort_keys=True).encode("utf-8"))
    for path in sorted({item.resolve() for item in paths}, key=lambda item: str(item)):
        digest.update(str(path).encode("utf-8"))
        digest.update(b"\0")
        if not path.is_file():
            digest.update(b"MISSING")
            digest.update(b"\0")
            continue
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


@dataclass
class ArtifactCache:
    """JSON-backed cache mapping output artifacts to input fingerprints."""

    state_path: Path
    state: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, state_path: Path | None = None) -> ArtifactCache:
        """Load a cache state file, returning an empty cache when absent."""
        path = state_path or (Path.cwd() / ".papercrown-cache" / "render-state.json")
        if not path.is_file():
            return cls(state_path=path)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls(state_path=path)
        if not isinstance(raw, dict) or raw.get("schema") != CACHE_SCHEMA_VERSION:
            return cls(state_path=path)
        artifacts = raw.get("artifacts")
        if not isinstance(artifacts, dict):
            return cls(state_path=path)
        state = {
            str(key): str(value)
            for key, value in artifacts.items()
            if isinstance(key, str) and isinstance(value, str)
        }
        return cls(state_path=path, state=state)

    def hit(self, output: Path, fingerprint: str) -> bool:
        """Return true when ``output`` exists and its fingerprint matches."""
        return output.is_file() and self.state.get(str(output.resolve())) == fingerprint

    def record(self, output: Path, fingerprint: str) -> None:
        """Record a fresh fingerprint for ``output``."""
        self.state[str(output.resolve())] = fingerprint

    def save(self) -> None:
        """Write the cache state atomically enough for local CLI use."""
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, JsonValue] = {
            "schema": CACHE_SCHEMA_VERSION,
            "artifacts": dict(sorted(self.state.items())),
        }
        self.state_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
