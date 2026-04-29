"""Remove generated package build artifacts before building distributions."""

from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _remove_tree(path: Path) -> None:
    """Remove ``path`` only when it resolves inside the repository root."""
    resolved = path.resolve()
    if resolved == ROOT or ROOT not in resolved.parents:
        raise RuntimeError(f"refusing to remove path outside repository: {resolved}")
    shutil.rmtree(resolved, ignore_errors=True)


def main() -> int:
    """Clean ignored build directories that can leak stale files into wheels."""
    for name in ("build", "dist"):
        _remove_tree(ROOT / name)
    for egg_info in (ROOT / "src").glob("*.egg-info"):
        _remove_tree(egg_info)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
