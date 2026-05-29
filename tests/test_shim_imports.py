"""Regression: the millet back-compat shims must re-export from
`millet_record`, NOT the pre-rename `meet_record` package.

Background: `millet/{capture,audio,utils,languages}.py` are thin shims
re-exporting the capture primitives that physically live in the
`millet-record` distribution.  Before the fix they imported
`from meet_record.*`, which only resolved on machines where the legacy
`meetscribe-record` (providing the old `meet_record` package) happened
to be co-installed.  On a clean `pip install millet-pipeline` (which
depends on `millet-record`, providing `millet_record`), every shim
raised `ModuleNotFoundError: meet_record`.

These tests assert the shims import successfully and that their source
references the new package name.
"""
from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

_SHIMS = ["capture", "audio", "utils", "languages"]


@pytest.mark.parametrize("modname", _SHIMS)
def test_shim_imports_cleanly(modname):
    mod = importlib.import_module(f"millet.{modname}")
    assert mod is not None


@pytest.mark.parametrize("modname", _SHIMS)
def test_shim_sources_reference_millet_record_not_meet_record(modname):
    """Guard against a regression to `from meet_record...`."""
    src_path = Path(importlib.import_module("millet").__file__).parent / f"{modname}.py"
    source = src_path.read_text(encoding="utf-8")
    # Parse imports; no `import`/`from` statement may target meet_record.
    tree = ast.parse(source)
    bad = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module == "meet_record" or node.module.startswith("meet_record."):
                bad.append(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "meet_record" or alias.name.startswith("meet_record."):
                    bad.append(alias.name)
    assert not bad, f"millet/{modname}.py still imports legacy meet_record: {bad}"


def test_capture_reexports_create_session():
    import millet.capture as cap
    assert hasattr(cap, "create_session")
    assert hasattr(cap, "check_prerequisites")
