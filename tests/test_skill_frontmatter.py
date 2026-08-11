"""Smoke test: SKILL.md frontmatter is valid and the skill is cross-host ready.

This gives the "works on WorkBuddy / Claude Code / Copilot CLI / Amp / OpenClaw"
claim some backing: it checks the Agent Skills frontmatter parses and meets the
open-standard basics, and that the venv resolution is platform-adaptive (not
Windows-only). Runs on stdlib only — no third-party deps — so it works in CI.

Repo layout: tests/ is at <root>/tests, so repo root is parent.parent.
"""
import importlib.util
import os
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SKILL_MD = ROOT / "SKILL.md"


def _load_frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise AssertionError("SKILL.md must start with YAML frontmatter (---)")
    lines = text.splitlines()
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    assert end is not None, "SKILL.md frontmatter has no closing ---"
    meta = {}
    for line in lines[1:end]:
        if line and not line[0].isspace() and ":" in line:
            key, _, val = line.partition(":")
            meta[key.strip()] = val.strip()
    return meta


def _load_teach():
    sys.path.insert(0, str(ROOT / "tools" / "common"))
    spec = importlib.util.spec_from_file_location("teach_smoke", ROOT / "teach.py")
    teach = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(teach)
    return teach


def test_skill_frontmatter_present():
    assert SKILL_MD.exists(), "SKILL.md missing at repo root"


def test_frontmatter_name_is_valid_skill_id():
    meta = _load_frontmatter(SKILL_MD)
    assert "name" in meta, "frontmatter missing 'name'"
    name = meta["name"]
    assert re.fullmatch(r"[a-z0-9-]+", name), (
        f"skill name must be lowercase ASCII+hyphen (Agent Skills rule): {name!r}"
    )
    assert name == "book-learning-tutor", (
        f"name must equal the skill directory slug: {name!r}"
    )


def test_frontmatter_has_description_and_version():
    meta = _load_frontmatter(SKILL_MD)
    assert meta.get("description"), "frontmatter missing non-empty 'description'"
    assert re.fullmatch(r"\d+\.\d+\.\d+", meta.get("version", "")), (
        f"version must be semver x.y.z: {meta.get('version')!r}"
    )


def test_venv_path_is_cross_platform():
    # SKILL.md must not prescribe a Windows-only venv path as the only option
    text = SKILL_MD.read_text(encoding="utf-8")
    assert "Scripts" in text and "bin" in text, (
        "SKILL.md should show both Scripts/ (Windows) and bin/ (POSIX) venv paths"
    )


def test_teach_venv_resolution_is_adaptive():
    teach = _load_teach()
    venv_py = teach._venv_python()
    norm = str(venv_py).replace("\\", "/")
    if os.name == "nt":
        assert norm.endswith("Scripts/python.exe")
    else:
        assert norm.endswith("bin/python")


def test_safe_name_sanitizes_illegal_chars():
    teach = _load_teach()
    cleaned = teach.safe_name('a/b:c*?"<>|')
    assert "/" not in cleaned and ":" not in cleaned and "*" not in cleaned
    assert teach.safe_name("   ") == "untitled"
