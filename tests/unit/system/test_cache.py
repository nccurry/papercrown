"""Unit tests for content-addressed cache helpers."""

from __future__ import annotations

from papercrown.system.cache import ArtifactCache, fingerprint_files


def test_fingerprint_changes_when_file_content_changes(tmp_path):
    source = tmp_path / "source.md"
    source.write_text("one", encoding="utf-8")
    first = fingerprint_files([source], extra={"profile": "digital"})

    source.write_text("two", encoding="utf-8")
    second = fingerprint_files([source], extra={"profile": "digital"})

    assert first != second


def test_artifact_cache_requires_output_file_and_matching_fingerprint(tmp_path):
    state = tmp_path / "state.json"
    output = tmp_path / "out.pdf"
    cache = ArtifactCache.load(state)

    assert cache.hit(output, "abc") is False

    output.write_bytes(b"pdf")
    cache.record(output, "abc")
    cache.save()

    reloaded = ArtifactCache.load(state)
    assert reloaded.hit(output, "abc") is True
    assert reloaded.hit(output, "def") is False
