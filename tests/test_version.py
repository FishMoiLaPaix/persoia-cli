#!/usr/bin/env python3
"""Tests for `cmd_version` output in `persoia.py`.

These guard the contract the CI smoke test relies on (first line stays
`persoia X.Y.Z`, machine-parseable) and the frozen-binary behaviour added to
disambiguate which executable is running when several copies coexist
(cf. ia-perso#818).

Run with: pytest tests/test_version.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# The CLI ships as a single script under src/; import it the way CI does.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import persoia  # noqa: E402

# The exact regex the Jenkins smoke test greps for on the built binary.
_SMOKE_RE = re.compile(r"^persoia [0-9]+\.[0-9]+\.[0-9]+$")


def test_version_from_source_prints_single_line(monkeypatch, capsys) -> None:
    # Running from source (not frozen): no executable path, just the version.
    monkeypatch.delattr(persoia.sys, "frozen", raising=False)
    persoia.cmd_version()
    lines = capsys.readouterr().out.splitlines()
    assert lines == [f"persoia {persoia.__version__}"]


def test_version_first_line_matches_smoke_test_regex(monkeypatch, capsys) -> None:
    # Even when frozen, the FIRST line must stay `persoia X.Y.Z` so the CI
    # smoke test (`grep -qE '^persoia [0-9]+\.[0-9]+\.[0-9]+$'`) keeps passing.
    monkeypatch.setattr(persoia.sys, "frozen", True, raising=False)
    monkeypatch.setattr(persoia.sys, "executable", "/opt/persoia/persoia", raising=False)
    persoia.cmd_version()
    first_line = capsys.readouterr().out.splitlines()[0]
    assert _SMOKE_RE.match(first_line), first_line


def test_version_when_frozen_shows_executable_path(monkeypatch, capsys) -> None:
    monkeypatch.setattr(persoia.sys, "frozen", True, raising=False)
    monkeypatch.setattr(persoia.sys, "executable", "/opt/persoia/persoia", raising=False)
    persoia.cmd_version()
    out = capsys.readouterr().out
    lines = out.splitlines()
    assert lines[0] == f"persoia {persoia.__version__}"
    # Second line carries the resolved executable path.
    assert len(lines) == 2
    assert str(Path("/opt/persoia/persoia").resolve()) in lines[1]
