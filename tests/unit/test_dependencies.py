"""Unit tests for dependency manifest checks."""

from __future__ import annotations

from pathlib import Path

from papercrown import dependencies
from tools import sync_dependencies


def test_manifest_tracks_python_sources_without_transitive_packages(papercrown_root):
    manifest = dependencies.load_dependency_manifest(
        papercrown_root / "dependencies.yaml"
    )

    assert manifest["python"]["source_files"] == ["pyproject.toml", "uv.lock"]
    assert manifest["python_groups"]["runtime"]["source_files"] == [
        "pyproject.toml",
        "uv.lock",
    ]
    assert "dependencies" not in manifest["python_groups"]["runtime"]
    assert "dependencies" not in manifest["python_groups"]["dev"]


def test_versions_env_tracks_repo_managed_tool_versions(papercrown_root):
    versions = dependencies.load_versions_file(papercrown_root / "versions.env")

    assert versions["OBSIDIAN_EXPORT_VERSION"] == "25.3.0"
    assert versions["PYTHON_VERSION"] == "3.12"


def test_dependency_report_format_includes_owner_and_commands(tmp_path):
    report = dependencies.DependencyReport(
        manifest_path=tmp_path / "dependencies.yaml",
        checks=[
            dependencies.DependencyCheck(
                category="external_tools",
                name="pandoc",
                status=dependencies.DependencyStatus.WARN,
                message="pandoc should be updated",
                path=Path("C:/Program Files/Pandoc/pandoc.exe"),
                version="pandoc 3.1",
                managed_by="system package manager",
                check_command="pandoc --version",
                install_command="winget install JohnMacFarlane.Pandoc",
                update_command="winget upgrade JohnMacFarlane.Pandoc",
            )
        ],
    )

    text = report.format_text()

    assert "WARN: external_tools.pandoc - pandoc should be updated" in text
    assert "managed by: system package manager" in text
    assert "check: pandoc --version" in text
    assert "install: winget install JohnMacFarlane.Pandoc" in text
    assert "update: winget upgrade JohnMacFarlane.Pandoc" in text


def test_external_tool_commands_use_current_platform(monkeypatch):
    monkeypatch.setattr(dependencies.platform, "system", lambda: "Linux")

    assert (
        dependencies._platform_string_or_none(
            {
                "windows": "winget install Task.Task",
                "linux": "sudo apt-get install -y task",
                "posix": "curl install task",
            }
        )
        == "sudo apt-get install -y task"
    )


def test_external_tool_commands_fall_back_to_posix(monkeypatch):
    monkeypatch.setattr(dependencies.platform, "system", lambda: "Darwin")

    assert (
        dependencies._platform_string_or_none(
            {
                "windows": "winget install Task.Task",
                "posix": "curl install task",
            }
        )
        == "curl install task"
    )


def test_external_tool_exact_version_policy_errors_on_drift(monkeypatch, tmp_path):
    tool = tmp_path / "obsidian-export"
    tool.write_text("", encoding="utf-8")
    monkeypatch.setattr(dependencies.shutil, "which", lambda _command: str(tool))
    monkeypatch.setattr(
        dependencies,
        "_run_version_command",
        lambda *_args: "obsidian-export 24.11.0",
    )
    manifest = {
        "external_tools": {
            "obsidian-export": {
                "command": "obsidian-export",
                "version_command": ["obsidian-export", "--version"],
                "version_policy": {"exact_env": "OBSIDIAN_EXPORT_VERSION"},
            }
        }
    }

    checks = dependencies._check_external_tools(
        manifest,
        versions={"OBSIDIAN_EXPORT_VERSION": "25.3.0"},
    )

    assert checks[0].status is dependencies.DependencyStatus.ERROR
    assert "must be 25.3.0" in checks[0].message


def test_external_tool_warns_for_cargo_installed_obsidian_export(monkeypatch):
    monkeypatch.setattr(
        dependencies.shutil,
        "which",
        lambda _command: r"C:\Users\dev\.cargo\bin\obsidian-export.exe",
    )
    monkeypatch.setattr(
        dependencies,
        "_run_version_command",
        lambda *_args: "obsidian-export 25.3.0",
    )
    manifest = {
        "external_tools": {
            "obsidian-export": {
                "command": "obsidian-export",
                "version_command": ["obsidian-export", "--version"],
                "version_policy": {
                    "exact_env": "OBSIDIAN_EXPORT_VERSION",
                    "warn_path_contains": [".cargo"],
                },
            }
        }
    }

    checks = dependencies._check_external_tools(
        manifest,
        versions={"OBSIDIAN_EXPORT_VERSION": "25.3.0"},
    )

    assert checks[0].status is dependencies.DependencyStatus.WARN
    assert "non-preferred source" in checks[0].message


def test_dependency_metadata_audit_is_clean():
    assert sync_dependencies.audit() == []


def test_ci_uses_published_or_candidate_builder_image(papercrown_root):
    ci = (papercrown_root / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )
    ci_image = (papercrown_root / ".github" / "workflows" / "ci-image.yml").read_text(
        encoding="utf-8"
    )

    assert "Run checks in published CI image" in ci
    assert "Build candidate CI image" in ci
    assert "Run checks in candidate CI image" in ci
    assert "source versions.env" in ci
    assert "workflow_dispatch" in ci_image


def test_python_group_checks_read_pyproject_and_uv_lock(papercrown_root):
    manifest = dependencies.load_dependency_manifest(
        papercrown_root / "dependencies.yaml"
    )

    checks = dependencies._check_python_groups(manifest)
    statuses = {check.name: check.status for check in checks}

    assert statuses["runtime"] is dependencies.DependencyStatus.OK
    assert statuses["dev"] is dependencies.DependencyStatus.OK
    assert all(check.path == papercrown_root / "pyproject.toml" for check in checks)


def test_windows_native_runtime_msys2_ucrt64_pango_passes():
    preferred = Path(r"C:\msys64\ucrt64\bin")

    check = dependencies._classify_windows_native_runtime(
        preferred_dir=preferred,
        preferred_dir_present=True,
        stale_dirs=(Path(r"C:\Program Files\GTK3-Runtime Win64\bin"),),
        stale_versions=("2.70.2",),
        env_dirs=(preferred,),
        path_entries=(),
        glib_path=preferred / "libglib-2.0-0.dll",
        pango_path=preferred / "libpango-1.0-0.dll",
        glib_version="2.80.0",
        managed_by="MSYS2",
        check_command="uv run papercrown deps check",
        install_command="install msys2",
        update_command="update msys2",
        configure_command='setx WEASYPRINT_DLL_DIRECTORIES "C:\\msys64\\ucrt64\\bin"',
    )

    assert check.status is dependencies.DependencyStatus.OK


def test_windows_native_runtime_prefers_env_over_stale_path_order():
    preferred = Path(r"C:\msys64\ucrt64\bin")
    stale = Path(r"C:\Program Files\GTK3-Runtime Win64\bin")

    check = dependencies._classify_windows_native_runtime(
        preferred_dir=preferred,
        preferred_dir_present=True,
        stale_dirs=(stale,),
        stale_versions=("2.70.2",),
        env_dirs=(preferred,),
        path_entries=(stale,),
        glib_path=preferred / "libglib-2.0-0.dll",
        pango_path=preferred / "libpango-1.0-0.dll",
        glib_version="2.70.2",
        managed_by="MSYS2",
        check_command="uv run papercrown deps check",
        install_command="install msys2",
        update_command="update msys2",
        configure_command='setx WEASYPRINT_DLL_DIRECTORIES "C:\\msys64\\ucrt64\\bin"',
    )

    assert check.status is dependencies.DependencyStatus.OK
    assert check.path == preferred / "libglib-2.0-0.dll"


def test_windows_native_runtime_gtk_glib_warns_with_uwp_explanation():
    preferred = Path(r"C:\msys64\ucrt64\bin")
    stale = Path(r"C:\Program Files\GTK3-Runtime Win64\bin")

    check = dependencies._classify_windows_native_runtime(
        preferred_dir=preferred,
        preferred_dir_present=False,
        stale_dirs=(stale,),
        stale_versions=("2.70.2",),
        env_dirs=(),
        path_entries=(stale, preferred),
        glib_path=stale / "libglib-2.0-0.dll",
        pango_path=stale / "libpango-1.0-0.dll",
        glib_version="2.70.2",
        managed_by="MSYS2",
        check_command="uv run papercrown deps check",
        install_command="install msys2",
        update_command="update msys2",
        configure_command='setx WEASYPRINT_DLL_DIRECTORIES "C:\\msys64\\ucrt64\\bin"',
    )

    assert check.status is dependencies.DependencyStatus.WARN
    assert "UWP app-info warnings" in check.message


def test_windows_native_runtime_missing_errors_for_pdf_builds():
    check = dependencies._classify_windows_native_runtime(
        preferred_dir=Path(r"C:\msys64\ucrt64\bin"),
        preferred_dir_present=False,
        stale_dirs=(),
        stale_versions=(),
        env_dirs=(),
        path_entries=(),
        glib_path=None,
        pango_path=None,
        glib_version=None,
        managed_by="MSYS2",
        check_command="uv run papercrown deps check",
        install_command="install msys2",
        update_command="update msys2",
        configure_command='setx WEASYPRINT_DLL_DIRECTORIES "C:\\msys64\\ucrt64\\bin"',
    )

    assert check.status is dependencies.DependencyStatus.ERROR
