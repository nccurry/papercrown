"""Dependency manifest parsing and environment checks for Paper Crown."""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import sys
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, cast

import yaml

from .diagnostics import Diagnostic, DiagnosticSeverity
from .resources import FONTS_DIR, PACKAGE_DIR

PAPERCROWN_DIR = PACKAGE_DIR.parent.parent.resolve()
DEFAULT_DEPENDENCIES_FILE = PAPERCROWN_DIR / "dependencies.yaml"
DEFAULT_VERSIONS_FILE = PAPERCROWN_DIR / "versions.env"
_VERSION_TIMEOUT_SECONDS = 5
_WINDOWS_LIBRARY_NAMES = ("libglib-2.0-0.dll", "libpango-1.0-0.dll")
_GLIB_GIO_WARNING_EXPLANATION = (
    "Old GTK3-Runtime GLib can emit GLib-GIO UWP app-info warnings during "
    "WeasyPrint PDF builds."
)
_FALLBACK_NATIVE_RUNTIME_MANIFEST: dict[str, Any] = {
    "native_pdf_runtime": {
        "windows": {
            "managed_by": "MSYS2 pacman + WEASYPRINT_DLL_DIRECTORIES",
            "check": "uv run papercrown deps check",
            "preferred": {
                "dll_dir": r"C:\msys64\ucrt64\bin",
                "install_commands": [
                    "winget install --id MSYS2.MSYS2 -e",
                    r'C:\msys64\usr\bin\bash.exe -lc "pacman -Syu --noconfirm"',
                    (
                        r'C:\msys64\usr\bin\bash.exe -lc "pacman -S --needed '
                        r'--noconfirm mingw-w64-ucrt-x86_64-pango"'
                    ),
                    r'setx WEASYPRINT_DLL_DIRECTORIES "C:\msys64\ucrt64\bin"',
                    r"add C:\msys64\ucrt64\bin to User PATH",
                ],
                "update_commands": [
                    r'C:\msys64\usr\bin\bash.exe -lc "pacman -Syu --noconfirm"',
                    (
                        r'C:\msys64\usr\bin\bash.exe -lc "pacman -S --needed '
                        r'--noconfirm mingw-w64-ucrt-x86_64-pango"'
                    ),
                    r'setx WEASYPRINT_DLL_DIRECTORIES "C:\msys64\ucrt64\bin"',
                    r"add C:\msys64\ucrt64\bin to User PATH",
                ],
            },
            "stale_unsupported": [
                {
                    "dll_dir": r"C:\Program Files\GTK3-Runtime Win64\bin",
                    "known_glib_versions": ["2.70.2"],
                }
            ],
        }
    }
}


class DependencyManifestError(RuntimeError):
    """Raised when dependencies.yaml is missing or malformed."""


class DependencyStatus(Enum):
    """Status for one dependency check."""

    OK = "OK"
    WARN = "WARN"
    ERROR = "ERROR"
    INFO = "INFO"


@dataclass(frozen=True)
class DependencyCheck:
    """One dependency check result."""

    category: str
    name: str
    status: DependencyStatus
    message: str
    path: Path | None = None
    version: str | None = None
    managed_by: str | None = None
    check_command: str | None = None
    install_command: str | None = None
    update_command: str | None = None
    hint: str | None = None


@dataclass
class DependencyReport:
    """A dependency check report with CLI formatting helpers."""

    manifest_path: Path
    checks: list[DependencyCheck] = field(default_factory=list)

    @property
    def errors(self) -> list[DependencyCheck]:
        """Return dependency checks that should fail."""
        return [
            check for check in self.checks if check.status is DependencyStatus.ERROR
        ]

    @property
    def warnings(self) -> list[DependencyCheck]:
        """Return dependency checks that should warn."""
        return [check for check in self.checks if check.status is DependencyStatus.WARN]

    def exit_code(self, *, strict: bool = False) -> int:
        """Return a process-style exit code."""
        if self.errors or (strict and self.warnings):
            return 1
        return 0

    def format_text(self, *, updates_only: bool = False) -> str:
        """Render dependency checks as human-readable text."""
        lines = ["papercrown deps", f"  manifest: {self.manifest_path}"]
        checks = self.checks
        if updates_only:
            checks = [
                check
                for check in checks
                if check.status in {DependencyStatus.WARN, DependencyStatus.ERROR}
            ]
        if not checks:
            lines.append("  OK: no dependency issues found")
            return "\n".join(lines)

        for check in checks:
            lines.append(
                f"  {check.status.value}: {check.category}.{check.name} - "
                f"{check.message}"
            )
            if check.path is not None:
                lines.append(f"      path: {check.path}")
            if check.version:
                lines.append(f"      version: {check.version}")
            if check.managed_by:
                lines.append(f"      managed by: {check.managed_by}")
            if check.check_command:
                lines.append(f"      check: {check.check_command}")
            if check.install_command:
                lines.append(f"      install: {check.install_command}")
            if check.update_command:
                lines.append(f"      update: {check.update_command}")
            if check.hint:
                lines.append(f"      hint: {check.hint}")

        lines.append(
            "  result: " + ("failed" if self.exit_code(strict=False) else "passed")
        )
        return "\n".join(lines)


def load_dependency_manifest(path: Path | None = None) -> dict[str, Any]:
    """Load the repo-owned dependency manifest."""
    manifest_path = (path or DEFAULT_DEPENDENCIES_FILE).resolve()
    if not manifest_path.is_file():
        raise DependencyManifestError(f"dependency manifest not found: {manifest_path}")
    try:
        loaded = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        message = f"invalid dependency manifest: {error}"
        raise DependencyManifestError(message) from error
    if not isinstance(loaded, dict):
        raise DependencyManifestError("dependency manifest must be a mapping")
    return cast(dict[str, Any], loaded)


def load_versions_file(path: Path | None = None) -> dict[str, str]:
    """Load repo-managed tool versions from ``versions.env``."""
    versions_path = (path or DEFAULT_VERSIONS_FILE).resolve()
    if not versions_path.is_file():
        raise DependencyManifestError(f"tool version file not found: {versions_path}")
    versions: dict[str, str] = {}
    try:
        lines = versions_path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise DependencyManifestError(
            f"failed to read {versions_path}: {error}"
        ) from error
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise DependencyManifestError(
                f"{versions_path}:{line_number}: expected KEY=VALUE"
            )
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            raise DependencyManifestError(
                f"{versions_path}:{line_number}: invalid key {key!r}"
            )
        versions[key] = value
    return versions


def check_dependencies(path: Path | None = None) -> DependencyReport:
    """Run all dependency checks defined by dependencies.yaml."""
    manifest_path = (path or DEFAULT_DEPENDENCIES_FILE).resolve()
    try:
        manifest = load_dependency_manifest(manifest_path)
    except DependencyManifestError as error:
        return DependencyReport(
            manifest_path=manifest_path,
            checks=[
                DependencyCheck(
                    category="manifest",
                    name="dependencies.yaml",
                    status=DependencyStatus.ERROR,
                    message=str(error),
                )
            ],
        )
    try:
        versions = load_versions_file()
    except DependencyManifestError as error:
        return DependencyReport(
            manifest_path=manifest_path,
            checks=[
                DependencyCheck(
                    category="manifest",
                    name="versions.env",
                    status=DependencyStatus.ERROR,
                    message=str(error),
                    path=DEFAULT_VERSIONS_FILE,
                )
            ],
        )

    checks: list[DependencyCheck] = []
    checks.extend(_check_python(manifest))
    checks.extend(_check_python_groups(manifest))
    checks.extend(_check_external_tools(manifest, versions=versions))
    checks.extend(check_native_pdf_runtime(manifest))
    checks.extend(_check_bundled_assets(manifest))
    return DependencyReport(manifest_path=manifest_path, checks=checks)


def check_native_pdf_runtime(
    manifest: dict[str, Any] | None = None,
    *,
    path: Path | None = None,
) -> list[DependencyCheck]:
    """Run only native PDF runtime checks."""
    manifest_data = manifest if manifest is not None else load_dependency_manifest(path)
    native = _mapping(manifest_data.get("native_pdf_runtime"))
    windows = _mapping(native.get("windows"))
    if not windows:
        return []

    managed_by = _string_or_none(windows.get("managed_by"))
    if platform.system() != "Windows":
        return [
            DependencyCheck(
                category="native_pdf_runtime",
                name="windows",
                status=DependencyStatus.INFO,
                message="Windows WeasyPrint runtime policy is not active here",
                managed_by=managed_by,
                check_command=_string_or_none(windows.get("check")),
            )
        ]

    preferred = _mapping(windows.get("preferred"))
    preferred_dir = Path(
        _string_or_none(preferred.get("dll_dir")) or r"C:\msys64\mingw64\bin"
    )
    stale_entries = _sequence(windows.get("stale_unsupported"))
    stale_dirs = tuple(
        Path(stale_dir)
        for item in stale_entries
        if (stale_dir := _string_or_none(_mapping(item).get("dll_dir"))) is not None
    )
    stale_versions = tuple(
        version
        for item in stale_entries
        for version in _string_list(_mapping(item).get("known_glib_versions"))
    )
    install_command = _join_commands(_string_list(preferred.get("install_commands")))
    update_command = _join_commands(_string_list(preferred.get("update_commands")))
    configure_command = _last_command(install_command)
    env_dirs = tuple(_split_path_list(os.environ.get("WEASYPRINT_DLL_DIRECTORIES", "")))
    path_entries = tuple(_split_path_list(os.environ.get("PATH", "")))
    search_dirs = env_dirs + path_entries
    glib_path = _find_library("libglib-2.0-0.dll", search_dirs)
    pango_path = _find_library("libpango-1.0-0.dll", search_dirs)
    glib_version = _read_windows_file_version(glib_path) if glib_path else None
    preferred_dir_present = all(
        (preferred_dir / library_name).is_file()
        for library_name in _WINDOWS_LIBRARY_NAMES
    )

    return [
        _classify_windows_native_runtime(
            preferred_dir=preferred_dir,
            preferred_dir_present=preferred_dir_present,
            stale_dirs=stale_dirs,
            stale_versions=stale_versions,
            env_dirs=env_dirs,
            path_entries=path_entries,
            glib_path=glib_path,
            pango_path=pango_path,
            glib_version=glib_version,
            managed_by=managed_by,
            check_command=_string_or_none(windows.get("check")),
            install_command=install_command,
            update_command=update_command,
            configure_command=configure_command,
        )
    ]


def native_pdf_runtime_diagnostics(path: Path | None = None) -> list[Diagnostic]:
    """Return doctor diagnostics for PDF-critical native runtime issues."""
    try:
        checks = check_native_pdf_runtime(path=path)
    except DependencyManifestError as error:
        if path is not None:
            return [
                Diagnostic(
                    code="deps.manifest",
                    severity=DiagnosticSeverity.ERROR,
                    message=str(error),
                )
            ]
        checks = check_native_pdf_runtime(_FALLBACK_NATIVE_RUNTIME_MANIFEST)
    diagnostics: list[Diagnostic] = []
    for check in checks:
        if check.status not in {DependencyStatus.WARN, DependencyStatus.ERROR}:
            continue
        diagnostics.append(
            Diagnostic(
                code=f"deps.{check.category}.{check.name}",
                severity=_diagnostic_severity(check.status),
                message=check.message,
                path=check.path,
                hint=check.hint or check.install_command or check.update_command,
            )
        )
    return diagnostics


def _check_python(manifest: dict[str, Any]) -> list[DependencyCheck]:
    python_spec = _mapping(manifest.get("python"))
    required = _string_or_none(python_spec.get("requires")) or ">=3.11"
    source_files = _source_files(python_spec)
    missing = [path.name for path in source_files if not path.is_file()]
    managed_by = _string_or_none(python_spec.get("managed_by"))
    check_command = _string_or_none(python_spec.get("check"))
    update_command = _string_or_none(python_spec.get("update"))
    version = platform.python_version()

    if missing:
        return [
            DependencyCheck(
                category="python",
                name="environment",
                status=DependencyStatus.ERROR,
                message="missing dependency source file(s): " + ", ".join(missing),
                path=PAPERCROWN_DIR,
                version=version,
                managed_by=managed_by,
                check_command=check_command,
                update_command=update_command,
            )
        ]

    status = DependencyStatus.OK
    message = f"Python {required} is satisfied"
    if not _python_requires_satisfied(required):
        status = DependencyStatus.ERROR
        message = f"Python {required} is required"

    return [
        DependencyCheck(
            category="python",
            name="environment",
            status=status,
            message=message,
            path=Path(sys.executable),
            version=version,
            managed_by=managed_by,
            check_command=check_command,
            update_command=update_command,
            hint="source files: " + ", ".join(path.name for path in source_files),
        )
    ]


def _check_python_groups(manifest: dict[str, Any]) -> list[DependencyCheck]:
    groups = _mapping(manifest.get("python_groups"))
    if not groups:
        return []
    pyproject_path = PAPERCROWN_DIR / "pyproject.toml"
    lock_path = PAPERCROWN_DIR / "uv.lock"
    if not pyproject_path.is_file():
        return [
            DependencyCheck(
                category="python_groups",
                name="pyproject",
                status=DependencyStatus.ERROR,
                message="pyproject.toml is missing",
                managed_by="pyproject.toml + uv.lock",
            )
        ]
    pyproject = _read_pyproject(pyproject_path)
    project = _mapping(pyproject.get("project"))
    dependency_groups = _mapping(pyproject.get("dependency-groups"))
    checks: list[DependencyCheck] = []

    runtime = _mapping(groups.get("runtime"))
    if runtime:
        runtime_dependencies = _string_list(project.get("dependencies"))
        source_missing = _missing_sources(runtime)
        if source_missing:
            status = DependencyStatus.ERROR
            message = "missing source file(s): " + ", ".join(source_missing)
        elif not runtime_dependencies:
            status = DependencyStatus.WARN
            message = "no direct runtime dependencies are declared"
        else:
            status = DependencyStatus.OK
            message = (
                f"{len(runtime_dependencies)} direct runtime dependencies are "
                "declared in pyproject.toml"
            )
        checks.append(
            DependencyCheck(
                category="python_groups",
                name="runtime",
                status=status,
                message=message,
                path=pyproject_path,
                managed_by=_string_or_none(runtime.get("managed_by")),
                check_command=_join_commands(
                    _string_list(runtime.get("check_commands"))
                ),
                update_command="uv lock --upgrade",
                hint=f"lockfile: {lock_path.name}",
            )
        )

    dev = _mapping(groups.get("dev"))
    if dev:
        dev_dependencies = _string_list(dependency_groups.get("dev"))
        declared_names = {_dependency_name(value) for value in dev_dependencies}
        expected_names = {
            _dependency_name(name) for name in _mapping(dev.get("tools")).keys()
        }
        missing_expected = sorted(expected_names - declared_names)
        source_missing = _missing_sources(dev)
        if source_missing:
            status = DependencyStatus.ERROR
            message = "missing source file(s): " + ", ".join(source_missing)
        elif missing_expected:
            status = DependencyStatus.ERROR
            message = "missing direct dev package(s): " + ", ".join(missing_expected)
        else:
            status = DependencyStatus.OK
            message = (
                f"{len(dev_dependencies)} direct dev dependencies are declared "
                "in pyproject.toml"
            )
        checks.append(
            DependencyCheck(
                category="python_groups",
                name="dev",
                status=status,
                message=message,
                path=pyproject_path,
                managed_by=_string_or_none(dev.get("managed_by")),
                check_command=_join_commands(_dev_check_commands(dev)),
                update_command="uv lock --upgrade --group dev",
                hint=f"lockfile: {lock_path.name}",
            )
        )

    return checks


def _check_external_tools(
    manifest: dict[str, Any],
    *,
    versions: dict[str, str],
) -> list[DependencyCheck]:
    tools = _mapping(manifest.get("external_tools"))
    checks: list[DependencyCheck] = []
    for name, raw_spec in tools.items():
        spec = _mapping(raw_spec)
        command = _string_or_none(spec.get("command")) or name
        executable = shutil.which(command)
        version_command = _command_list(spec.get("version_command"))
        if executable is None:
            checks.append(
                DependencyCheck(
                    category="external_tools",
                    name=name,
                    status=DependencyStatus.ERROR,
                    message=f"{command!r} was not found on PATH",
                    managed_by=_string_or_none(spec.get("managed_by")),
                    check_command=(
                        _command_text(version_command) or f"{command} --version"
                    ),
                    install_command=_platform_string_or_none(spec.get("install")),
                    update_command=_platform_string_or_none(spec.get("update")),
                )
            )
            continue
        version = _run_version_command(version_command, executable, command)
        status, message = _classify_external_tool_version(
            command=command,
            executable=Path(executable),
            version=version,
            spec=spec,
            versions=versions,
        )
        checks.append(
            DependencyCheck(
                category="external_tools",
                name=name,
                status=status,
                message=message,
                path=Path(executable),
                version=version,
                managed_by=_string_or_none(spec.get("managed_by")),
                check_command=_command_text(version_command) or f"{command} --version",
                install_command=_platform_string_or_none(spec.get("install")),
                update_command=_platform_string_or_none(spec.get("update")),
            )
        )
    return checks


def _classify_external_tool_version(
    *,
    command: str,
    executable: Path,
    version: str | None,
    spec: dict[str, Any],
    versions: dict[str, str],
) -> tuple[DependencyStatus, str]:
    """Return status/message for an installed external command."""
    policy = _mapping(spec.get("version_policy"))
    detected = _extract_version(version)
    exact = _policy_version(policy, "exact_env", versions)
    minimum = _policy_version(policy, "minimum_env", versions)
    if exact is not None:
        if detected is None or _compare_versions(detected, exact) != 0:
            found = version or "unknown"
            return (
                DependencyStatus.ERROR,
                f"{command!r} version must be {exact}; found {found}",
            )
    if minimum is not None:
        if detected is None or _compare_versions(detected, minimum) < 0:
            found = version or "unknown"
            return (
                DependencyStatus.ERROR,
                f"{command!r} must be at least {minimum}; found {found}",
            )

    path_text = str(executable).replace("\\", "/").lower()
    warn_parts = [
        part.lower().replace("\\", "/")
        for part in _string_list(policy.get("warn_path_contains"))
    ]
    if any(part in path_text for part in warn_parts):
        return (
            DependencyStatus.WARN,
            f"{command!r} is available but was installed from a non-preferred source",
        )
    return DependencyStatus.OK, f"{command!r} is available"


def _policy_version(
    policy: dict[str, Any],
    field: str,
    versions: dict[str, str],
) -> str | None:
    env_key = _string_or_none(policy.get(field))
    if env_key is None:
        return None
    return versions.get(env_key)


def _extract_version(value: str | None) -> str | None:
    if not value:
        return None
    match = re.search(r"(\d+(?:\.\d+)+)", value)
    return match.group(1) if match else None


def _compare_versions(left: str, right: str) -> int:
    left_parts = [int(part) for part in left.split(".") if part.isdigit()]
    right_parts = [int(part) for part in right.split(".") if part.isdigit()]
    max_len = max(len(left_parts), len(right_parts))
    left_parts.extend([0] * (max_len - len(left_parts)))
    right_parts.extend([0] * (max_len - len(right_parts)))
    if left_parts < right_parts:
        return -1
    if left_parts > right_parts:
        return 1
    return 0


def _check_bundled_assets(manifest: dict[str, Any]) -> list[DependencyCheck]:
    assets = _mapping(manifest.get("bundled_assets"))
    fonts = _mapping(assets.get("fonts"))
    if not fonts:
        return []
    required_fonts = _string_list(fonts.get("required"))
    missing = [font for font in required_fonts if not (FONTS_DIR / font).is_file()]
    if missing:
        status = DependencyStatus.ERROR
        message = "missing bundled font file(s): " + ", ".join(missing)
    else:
        status = DependencyStatus.OK
        message = f"{len(required_fonts)} bundled font file(s) are present"
    return [
        DependencyCheck(
            category="bundled_assets",
            name="fonts",
            status=status,
            message=message,
            path=FONTS_DIR,
            managed_by=_string_or_none(fonts.get("managed_by")),
            check_command=_string_or_none(fonts.get("check")),
            update_command=_string_or_none(fonts.get("update")),
            hint=_string_or_none(fonts.get("source")),
        )
    ]


def _classify_windows_native_runtime(
    *,
    preferred_dir: Path,
    preferred_dir_present: bool,
    stale_dirs: Sequence[Path],
    stale_versions: Sequence[str],
    env_dirs: Sequence[Path],
    path_entries: Sequence[Path],
    glib_path: Path | None,
    pango_path: Path | None,
    glib_version: str | None,
    managed_by: str | None,
    check_command: str | None,
    install_command: str | None,
    update_command: str | None,
    configure_command: str | None,
) -> DependencyCheck:
    preferred_env_active = _path_in_dirs(preferred_dir, env_dirs)
    preferred_path_active = _path_in_dirs(preferred_dir, path_entries)
    preferred_runtime_resolved = _path_under_any(
        glib_path,
        (preferred_dir,),
    ) or _path_under_any(pango_path, (preferred_dir,))
    stale_version_active = (
        glib_version is not None
        and glib_version in set(stale_versions)
        and not preferred_runtime_resolved
    )
    stale_path_order_active = not preferred_env_active and _stale_before_preferred(
        path_entries, stale_dirs, preferred_dir
    )
    stale_active = (
        _path_under_any(glib_path, stale_dirs)
        or _path_under_any(pango_path, stale_dirs)
        or stale_path_order_active
        or stale_version_active
    )
    active_path = (
        glib_path or pango_path or (preferred_dir if preferred_dir_present else None)
    )

    if preferred_env_active and not stale_active:
        return DependencyCheck(
            category="native_pdf_runtime",
            name="windows",
            status=DependencyStatus.OK,
            message="MSYS2 UCRT64 Pango/GLib is configured for WeasyPrint",
            path=active_path,
            version=glib_version,
            managed_by=managed_by,
            check_command=check_command,
            install_command=install_command,
            update_command=update_command,
        )

    if preferred_dir_present and not (preferred_env_active or preferred_path_active):
        return DependencyCheck(
            category="native_pdf_runtime",
            name="windows",
            status=DependencyStatus.WARN,
            message=(
                "MSYS2 UCRT64 Pango/GLib is installed but not configured "
                "for WeasyPrint"
            ),
            path=preferred_dir,
            version=glib_version,
            managed_by=managed_by,
            check_command=check_command,
            install_command=install_command,
            update_command=update_command,
            hint=configure_command,
        )

    if stale_active:
        return DependencyCheck(
            category="native_pdf_runtime",
            name="windows",
            status=DependencyStatus.WARN,
            message=_GLIB_GIO_WARNING_EXPLANATION,
            path=active_path,
            version=glib_version,
            managed_by=managed_by,
            check_command=check_command,
            install_command=install_command,
            update_command=update_command,
            hint=configure_command,
        )

    if preferred_env_active or (preferred_path_active and preferred_dir_present):
        return DependencyCheck(
            category="native_pdf_runtime",
            name="windows",
            status=DependencyStatus.OK,
            message="MSYS2 UCRT64 Pango/GLib is configured for WeasyPrint",
            path=active_path,
            version=glib_version,
            managed_by=managed_by,
            check_command=check_command,
            install_command=install_command,
            update_command=update_command,
        )

    if glib_path is not None or pango_path is not None:
        return DependencyCheck(
            category="native_pdf_runtime",
            name="windows",
            status=DependencyStatus.WARN,
            message="a non-preferred Pango/GLib runtime is active for WeasyPrint",
            path=active_path,
            version=glib_version,
            managed_by=managed_by,
            check_command=check_command,
            install_command=install_command,
            update_command=update_command,
            hint=configure_command,
        )

    return DependencyCheck(
        category="native_pdf_runtime",
        name="windows",
        status=DependencyStatus.ERROR,
        message="missing Windows Pango/GLib runtime required by WeasyPrint PDF builds",
        managed_by=managed_by,
        check_command=check_command,
        install_command=install_command,
        update_command=update_command,
    )


def _diagnostic_severity(status: DependencyStatus) -> DiagnosticSeverity:
    if status is DependencyStatus.ERROR:
        return DiagnosticSeverity.ERROR
    if status is DependencyStatus.WARN:
        return DiagnosticSeverity.WARNING
    return DiagnosticSeverity.INFO


def _mapping(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return cast(dict[str, Any], value)
    return {}


def _sequence(value: object) -> list[object]:
    if isinstance(value, list):
        return list(value)
    return []


def _string_or_none(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _platform_string_or_none(value: object) -> str | None:
    direct = _string_or_none(value)
    if direct is not None:
        return direct
    mapping = _mapping(value)
    if not mapping:
        return None
    platform_key = _current_platform_key()
    keys = [platform_key]
    if platform_key in {"linux", "macos"}:
        keys.append("posix")
    keys.append("default")
    for key in keys:
        command = _string_or_none(mapping.get(key))
        if command is not None:
            return command
    return None


def _current_platform_key() -> str:
    system = platform.system()
    if system == "Windows":
        return "windows"
    if system == "Darwin":
        return "macos"
    if system == "Linux":
        return "linux"
    return system.lower()


def _string_list(value: object) -> list[str]:
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    if isinstance(value, list):
        return [
            item.strip() for item in value if isinstance(item, str) and item.strip()
        ]
    return []


def _source_files(spec: dict[str, Any]) -> list[Path]:
    paths = _string_list(spec.get("source_files"))
    return [(PAPERCROWN_DIR / path).resolve() for path in paths]


def _missing_sources(spec: dict[str, Any]) -> list[str]:
    return [path.name for path in _source_files(spec) if not path.is_file()]


def _read_pyproject(path: Path) -> dict[str, Any]:
    with path.open("rb") as file:
        return tomllib.load(file)


def _python_requires_satisfied(requirement: str) -> bool:
    match = re.fullmatch(r">=\s*(\d+)\.(\d+)", requirement.strip())
    if match is None:
        return True
    major = int(match.group(1))
    minor = int(match.group(2))
    return sys.version_info >= (major, minor)


def _dependency_name(value: str) -> str:
    match = re.match(r"\s*([A-Za-z0-9_.-]+)", value)
    if match is None:
        return value.strip().lower()
    return match.group(1).lower()


def _dev_check_commands(dev: dict[str, Any]) -> list[str]:
    tools = _mapping(dev.get("tools"))
    commands: list[str] = []
    for raw_tool in tools.values():
        command = _string_or_none(_mapping(raw_tool).get("check"))
        if command is not None:
            commands.append(command)
    return commands


def _command_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str):
        return value.split()
    return []


def _command_text(command: Sequence[str]) -> str | None:
    if not command:
        return None
    return " ".join(command)


def _run_version_command(
    command: Sequence[str],
    executable: str,
    executable_name: str,
) -> str | None:
    if not command:
        return None
    argv = list(command)
    if argv and argv[0] == executable_name:
        argv[0] = executable
    try:
        completed = subprocess.run(
            argv,
            check=False,
            capture_output=True,
            text=True,
            timeout=_VERSION_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    output = completed.stdout or completed.stderr
    for line in output.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return None


def _split_path_list(value: str) -> list[Path]:
    if not value:
        return []
    parts = re.split(r";|" + re.escape(os.pathsep), value)
    return [Path(part.strip().strip('"')) for part in parts if part.strip()]


def _normalize_path(path: Path) -> str:
    return str(path).replace("/", "\\").rstrip("\\").lower()


def _same_path(left: Path, right: Path) -> bool:
    return _normalize_path(left) == _normalize_path(right)


def _path_in_dirs(path: Path, directories: Sequence[Path]) -> bool:
    return any(_same_path(path, directory) for directory in directories)


def _path_under(parent: Path, child: Path) -> bool:
    parent_norm = _normalize_path(parent)
    child_norm = _normalize_path(child)
    return child_norm == parent_norm or child_norm.startswith(parent_norm + "\\")


def _path_under_any(path: Path | None, directories: Sequence[Path]) -> bool:
    if path is None:
        return False
    return any(_path_under(directory, path) for directory in directories)


def _stale_before_preferred(
    path_entries: Sequence[Path],
    stale_dirs: Sequence[Path],
    preferred_dir: Path,
) -> bool:
    saw_stale = False
    for entry in path_entries:
        if any(_same_path(entry, stale_dir) for stale_dir in stale_dirs):
            saw_stale = True
        if _same_path(entry, preferred_dir):
            return saw_stale
    return False


def _find_library(name: str, directories: Sequence[Path]) -> Path | None:
    for directory in directories:
        candidate = directory / name
        if candidate.is_file():
            return candidate
    resolved = shutil.which(name)
    return Path(resolved) if resolved else None


def _read_windows_file_version(path: Path) -> str | None:
    if platform.system() != "Windows":
        return None
    script = (
        "param([string]$Path) "
        "$info = (Get-Item -LiteralPath $Path).VersionInfo; "
        "$info.ProductVersion"
    )
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script, str(path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=_VERSION_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    version = completed.stdout.strip()
    return version or None


def _join_commands(commands: Sequence[str]) -> str | None:
    if not commands:
        return None
    return " ; ".join(commands)


def _last_command(commands: str | None) -> str | None:
    if not commands:
        return None
    return commands.split(" ; ")[-1]
