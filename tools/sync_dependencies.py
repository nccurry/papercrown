"""Audit dependency metadata derived from versions.env."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
VERSIONS_FILE = ROOT / "versions.env"
DEPENDENCIES_FILE = ROOT / "dependencies.yaml"
REQUIRED_VERSION_KEYS = {
    "PYTHON_VERSION",
    "UV_VERSION",
    "TASK_VERSION",
    "OBSIDIAN_EXPORT_VERSION",
    "PANDOC_MIN_VERSION",
    "UV_BASE_IMAGE",
    "PYTHON_RUNTIME_IMAGE",
    "CI_IMAGE",
}
AUDITED_FILES = [
    "dependencies.yaml",
    "Dockerfile",
    "Dockerfile.ci",
    "scripts/deps-install.sh",
    "scripts/deps-install.ps1",
    "scripts/bootstrap.sh",
    "scripts/bootstrap.ps1",
    "scripts/container-build.sh",
    ".github/workflows/ci.yml",
    ".github/workflows/ci-image.yml",
    ".github/workflows/container.yml",
    ".github/workflows/pages.yml",
    ".github/workflows/release.yml",
]
DOCKER_ARG_DEFAULTS = {
    "Dockerfile": {
        "UV_BASE_IMAGE": "UV_BASE_IMAGE",
        "PYTHON_RUNTIME_IMAGE": "PYTHON_RUNTIME_IMAGE",
        "OBSIDIAN_EXPORT_VERSION": "OBSIDIAN_EXPORT_VERSION",
    },
    "Dockerfile.ci": {
        "UV_BASE_IMAGE": "UV_BASE_IMAGE",
        "TASK_VERSION": "TASK_VERSION",
        "OBSIDIAN_EXPORT_VERSION": "OBSIDIAN_EXPORT_VERSION",
    },
}
SCRIPT_ENV_DEFAULTS = {
    "scripts/container-build.sh": {
        "UV_BASE_IMAGE": "UV_BASE_IMAGE",
        "PYTHON_RUNTIME_IMAGE": "PYTHON_RUNTIME_IMAGE",
        "OBSIDIAN_EXPORT_VERSION": "OBSIDIAN_EXPORT_VERSION",
    },
}
EXPECTED_TOOL_POLICIES = {
    "pandoc": ("minimum_env", "PANDOC_MIN_VERSION"),
    "obsidian-export": ("exact_env", "OBSIDIAN_EXPORT_VERSION"),
    "uv": ("exact_env", "UV_VERSION"),
    "task": ("exact_env", "TASK_VERSION"),
}
FORBIDDEN_SNIPPETS = (
    (
        "cargo install " + "obsidian-export",
        "installs obsidian-export through Rust/Cargo",
    ),
    ("rustup.rs", "installs Rust"),
    ("dtolnay/rust-toolchain", "installs Rust"),
    ("astral-sh/setup-uv", "installs uv outside the CI builder image"),
    ("actions/setup-python", "installs Python outside the CI builder image"),
)


def load_versions(path: Path = VERSIONS_FILE) -> dict[str, str]:
    """Read a simple KEY=VALUE env file without shell expansion."""
    versions: dict[str, str] = {}
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), 1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"{path}:{line_number}: expected KEY=VALUE")
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            raise ValueError(f"{path}:{line_number}: invalid key {key!r}")
        versions[key] = value
    return versions


def audit() -> list[str]:
    """Return dependency drift problems."""
    problems: list[str] = []
    try:
        versions = load_versions()
    except OSError as error:
        return [f"failed to read {VERSIONS_FILE}: {error}"]
    except ValueError as error:
        return [str(error)]

    missing = sorted(REQUIRED_VERSION_KEYS - set(versions))
    if missing:
        problems.append("versions.env is missing: " + ", ".join(missing))

    try:
        manifest = yaml.safe_load(DEPENDENCIES_FILE.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        return problems + [f"failed to read {DEPENDENCIES_FILE}: {error}"]
    if not isinstance(manifest, dict):
        return problems + ["dependencies.yaml must contain a mapping"]

    tools = manifest.get("external_tools")
    if not isinstance(tools, dict):
        problems.append("dependencies.yaml external_tools must contain a mapping")
        tools = {}

    for name, raw_spec in tools.items():
        if not isinstance(raw_spec, dict):
            continue
        version_policy = raw_spec.get("version_policy")
        if not isinstance(version_policy, dict):
            continue
        for field in ("exact_env", "minimum_env"):
            env_key = version_policy.get(field)
            if isinstance(env_key, str) and env_key not in versions:
                problems.append(
                    f"external_tools.{name}.version_policy.{field} "
                    f"references missing {env_key}"
                )
    for name, (field, env_key) in EXPECTED_TOOL_POLICIES.items():
        raw_spec = tools.get(name)
        if not isinstance(raw_spec, dict):
            problems.append(f"dependencies.yaml is missing external_tools.{name}")
            continue
        version_policy = raw_spec.get("version_policy")
        if not isinstance(version_policy, dict):
            problems.append(f"external_tools.{name} is missing version_policy")
            continue
        if version_policy.get(field) != env_key:
            problems.append(
                f"external_tools.{name}.version_policy.{field} must reference {env_key}"
            )

    for relative in AUDITED_FILES:
        path = ROOT / relative
        if not path.is_file():
            problems.append(f"audited dependency file is missing: {relative}")
            continue
        text = path.read_text(encoding="utf-8")
        for snippet, message in FORBIDDEN_SNIPPETS:
            if snippet in text:
                problems.append(f"{relative} still {message}")
        for arg_name, env_key in DOCKER_ARG_DEFAULTS.get(relative, {}).items():
            actual = _docker_arg_default(text, arg_name)
            expected = versions.get(env_key)
            if actual != expected:
                problems.append(
                    f"{relative} ARG {arg_name} must match {env_key} "
                    f"from versions.env ({expected}); found {actual or 'missing'}"
                )
        for name, env_key in SCRIPT_ENV_DEFAULTS.get(relative, {}).items():
            actual = _shell_env_default(text, name)
            expected = versions.get(env_key)
            if actual != expected:
                problems.append(
                    f"{relative} default {name} must match {env_key} "
                    f"from versions.env ({expected}); found {actual or 'missing'}"
                )

    return problems


def _docker_arg_default(text: str, name: str) -> str | None:
    match = re.search(rf"^ARG\s+{re.escape(name)}=(?P<value>\S+)\s*$", text, re.M)
    if match is None:
        return None
    return match.group("value")


def _shell_env_default(text: str, name: str) -> str | None:
    match = re.search(rf"\$\{{{re.escape(name)}:-(?P<value>[^}}]+)\}}", text)
    if match is None:
        return None
    return match.group("value")


def main(argv: list[str] | None = None) -> int:
    """Run the dependency drift audit CLI."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail when dependency metadata has drifted.",
    )
    parser.parse_args(argv)
    problems = audit()
    if problems:
        print("Dependency metadata drift detected:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print("Dependency metadata is in sync.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
