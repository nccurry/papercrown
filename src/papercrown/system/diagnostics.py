"""Diagnostic data structures for doctor and content-quality checks."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class DiagnosticSeverity(Enum):
    """Severity levels emitted by preflight checks."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class Diagnostic:
    """One actionable preflight or quality-lint message."""

    code: str
    severity: DiagnosticSeverity
    message: str
    path: Path | None = None
    line: int | None = None
    hint: str | None = None

    def location(self) -> str:
        """Return a compact human-readable location string."""
        if self.path is None:
            return ""
        location = str(self.path)
        if self.line is not None:
            location = f"{location}:{self.line}"
        return location


@dataclass
class DiagnosticReport:
    """A collection of diagnostics with summary and formatting helpers."""

    diagnostics: list[Diagnostic] = field(default_factory=list)

    def add(self, diagnostic: Diagnostic) -> None:
        """Append one diagnostic to the report."""
        self.diagnostics.append(diagnostic)

    def extend(self, diagnostics: list[Diagnostic]) -> None:
        """Append several diagnostics to the report."""
        self.diagnostics.extend(diagnostics)

    @property
    def errors(self) -> list[Diagnostic]:
        """Return diagnostics that should always fail doctor."""
        return [
            diagnostic
            for diagnostic in self.diagnostics
            if diagnostic.severity is DiagnosticSeverity.ERROR
        ]

    @property
    def warnings(self) -> list[Diagnostic]:
        """Return diagnostics that fail only when strict mode is requested."""
        return [
            diagnostic
            for diagnostic in self.diagnostics
            if diagnostic.severity is DiagnosticSeverity.WARNING
        ]

    @property
    def infos(self) -> list[Diagnostic]:
        """Return informational diagnostics."""
        return [
            diagnostic
            for diagnostic in self.diagnostics
            if diagnostic.severity is DiagnosticSeverity.INFO
        ]

    def exit_code(self, *, strict: bool) -> int:
        """Return a process-style exit code for this report."""
        if self.errors or (strict and self.warnings):
            return 1
        return 0

    def format_text(self, *, strict: bool = False) -> str:
        """Render the report as plain text for CLI output."""
        lines: list[str] = ["papercrown doctor"]
        max_items_per_group = 20
        if not self.diagnostics:
            lines.append("  OK: no issues found")
            return "\n".join(lines)

        for severity in (
            DiagnosticSeverity.ERROR,
            DiagnosticSeverity.WARNING,
            DiagnosticSeverity.INFO,
        ):
            group = [
                diagnostic
                for diagnostic in self.diagnostics
                if diagnostic.severity is severity
            ]
            if not group:
                continue
            lines.append(f"  {severity.value.upper()} ({len(group)})")
            for diagnostic in group[:max_items_per_group]:
                location = diagnostic.location()
                suffix = f" [{location}]" if location else ""
                lines.append(f"    {diagnostic.code}: {diagnostic.message}{suffix}")
                if diagnostic.hint:
                    lines.append(f"      hint: {diagnostic.hint}")
            omitted = len(group) - max_items_per_group
            if omitted > 0:
                lines.append(f"    ... {omitted} more {severity.value} diagnostic(s)")

        lines.append(
            "  result: "
            + ("failed" if self.exit_code(strict=strict) else "passed")
            + (" (strict)" if strict else "")
        )
        return "\n".join(lines)
