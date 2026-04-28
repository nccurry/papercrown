"""Snapshot HTML normalization for render tests."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

_TOKEN_PAPERCROWN = "<<papercrown>>"
_TOKEN_FIXTURE = "<<fixture>>"
_TOKEN_TMP = "<<tmp>>"


def normalize_for_snapshot(
    html: str,
    *,
    papercrown_root: Path | None = None,
    fixture_root: Path | None = None,
) -> str:
    """Strip absolute paths from HTML before snapshot comparison."""
    out = html

    def normalize_path(raw: str) -> str:
        decoded = unquote(raw)
        path = Path(decoded)
        if papercrown_root is not None:
            try:
                rel = path.resolve().relative_to(papercrown_root.resolve())
                return f"{_TOKEN_PAPERCROWN}/{rel.as_posix()}"
            except (ValueError, OSError):
                pass
        if fixture_root is not None:
            try:
                rel = path.resolve().relative_to(fixture_root.resolve())
                return f"{_TOKEN_FIXTURE}/{rel.as_posix()}"
            except (ValueError, OSError):
                pass
        return f"{_TOKEN_TMP}/{path.name}"

    def replace_uri(match: re.Match[str]) -> str:
        uri = match.group(0)
        parsed = urlsplit(uri)
        path_str = parsed.path
        if parsed.netloc and parsed.netloc != "localhost":
            path_str = f"//{parsed.netloc}{path_str}"
        if re.match(r"^/[A-Za-z]:[\\/]", path_str):
            path_str = path_str[1:]
        return normalize_path(path_str)

    out = re.sub(r"file:///?[^\s\"'<>]+", replace_uri, out)

    def root_replace(root: Path | None, token: str) -> None:
        nonlocal out
        if root is None:
            return
        root_abs = root.resolve()
        forms = [str(root_abs)]
        forms.append(forms[0].replace("\\", "/"))
        forms.append(forms[0].replace("/", "\\"))

        seen: set[str] = set()
        unique_forms: list[str] = []
        for form in forms:
            if form in seen:
                continue
            seen.add(form)
            unique_forms.append(form)

        def build_repl(form: str) -> re.Pattern[str]:
            return re.compile(re.escape(form) + r"[\\/]([^\s\"'<>]+)")

        for form in unique_forms:
            pattern = build_repl(form)
            out = pattern.sub(
                lambda match: f"{token}/{match.group(1).replace(chr(92), '/')}",
                out,
            )

    root_replace(papercrown_root, _TOKEN_PAPERCROWN)
    root_replace(fixture_root, _TOKEN_FIXTURE)
    return out
