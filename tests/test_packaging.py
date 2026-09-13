"""Guard the packaging metadata against drift.

Two failure modes shipped together and neither was caught, because CI only ever
ran a single test module:

  * packages that are imported but never declared -- faiss, scikit-learn and
    youtube-transcript-api. Users had no way to discover the install command,
    and `pip install ailog[search]` produced a module that still raised on
    import.
  * extras that nothing imports -- `markdown` for the html/obsidian extras and
    `jieba` for search. Users installed a dependency that no code path touched.

These tests make both impossible to reintroduce silently.
"""

from __future__ import annotations

import ast
import sys
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = REPO_ROOT / "ailog"

# Distribution name -> importable module name, where they differ.
DIST_TO_MODULE = {
    "fpdf2": "fpdf",
    "notion-client": "notion_client",
    "youtube-transcript-api": "youtube_transcript_api",
    "faiss-cpu": "faiss",
    "scikit-learn": "sklearn",
    "sentence-transformers": "sentence_transformers",
}

# Test tooling: declared for the test run, never imported by the package.
TOOLING_ONLY = {"pytest", "pytest-cov"}

# Imported on purpose but deliberately not declared: `privacy-guard` is an
# alternative engine to `ghostguard`, picked up opportunistically.
ALLOWED_UNDECLARED_MODULES = {"privacy_guard"}


def _normalise(name: str) -> str:
    return name.strip().lower().replace("-", "_")


def _requirement_name(spec: str) -> str:
    """`"faiss-cpu>=1.7"` -> `"faiss-cpu"`."""
    for sep in (">=", "<=", "==", "!=", "~=", ">", "<", "[", ";", " "):
        spec = spec.split(sep)[0]
    return spec.strip()


def _load_pyproject() -> dict:
    with open(REPO_ROOT / "pyproject.toml", "rb") as handle:
        return tomllib.load(handle)


@pytest.fixture(scope="module")
def declared() -> dict[str, set[str]]:
    """Every declared distribution name, grouped by where it is declared."""
    project = _load_pyproject()["project"]
    groups = {"dependencies": set()}
    for name in project.get("dependencies", []):
        groups["dependencies"].add(_requirement_name(name))
    for extra, specs in project.get("optional-dependencies", {}).items():
        modules = set()
        for spec in specs:
            spec = _requirement_name(spec)
            # `ailog[search,dev]` style self references
            if spec and not spec.startswith("ailog"):
                groups.setdefault(extra, set()).add(spec)
        groups.setdefault(extra, modules)
    return groups


def _imported_modules() -> set[str]:
    """Every top-level module imported anywhere in the package."""
    found: set[str] = set()
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    found.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.level:  # relative import, stays inside the package
                    continue
                if node.module:
                    found.add(node.module.split(".")[0])
    return found


def _third_party_modules() -> set[str]:
    return {
        module
        for module in _imported_modules()
        if module != "ailog"
        and module not in sys.stdlib_module_names
        and not module.startswith("_")
    }


def test_every_imported_package_is_declared(declared):
    """Nothing may be imported without being declared somewhere."""
    declared_modules = {
        DIST_TO_MODULE.get(dist, _normalise(dist))
        for dists in declared.values()
        for dist in dists
        if dist not in TOOLING_ONLY
    }
    declared_modules |= ALLOWED_UNDECLARED_MODULES

    missing = sorted(_third_party_modules() - declared_modules)
    assert missing == [], (
        "imported but not declared in pyproject.toml: "
        f"{missing}. Add them to an optional-dependencies extra."
    )


def test_every_declared_package_is_imported(declared):
    """No extra may declare something the package never imports."""
    imported = _third_party_modules() | ALLOWED_UNDECLARED_MODULES

    stale: dict[str, list[str]] = {}
    for group, dists in declared.items():
        for dist in sorted(dists):
            if dist in TOOLING_ONLY:
                continue
            module = DIST_TO_MODULE.get(dist, _normalise(dist))
            if module not in imported:
                stale.setdefault(group, []).append(dist)

    assert stale == {}, (
        "declared but never imported, so the extra is misleading: "
        f"{stale}. Drop them or wire up the code that needs them."
    )


def test_search_extra_covers_what_engine_imports():
    """`ailog[search]` must actually make `ailog.search` importable."""
    project = _load_pyproject()["project"]
    search = {_requirement_name(s) for s in project["optional-dependencies"]["search"]}
    # engine.py imports numpy at module scope, and picks a real backend from
    # sentence-transformers or scikit-learn, then builds a FAISS index.
    assert {"numpy", "scikit-learn", "faiss-cpu"} <= search


def test_core_package_has_no_hard_dependencies():
    """The core format/CLI must stay installable with nothing but the stdlib."""
    assert _load_pyproject()["project"].get("dependencies", []) == []


def test_source_files_are_utf8_without_bom():
    """The spec mandates UTF-8 without BOM; keep the sources consistent.

    A stray BOM is invisible to Python's tokenizer but breaks every tool that
    reads the file as text -- `ast.parse`, most linters, and diff tooling.
    Four files had one.
    """
    suffixes = {".py", ".js", ".ts", ".json", ".yml", ".yaml", ".toml", ".md", ".sh"}
    offenders = []
    for path in sorted(REPO_ROOT.rglob("*")):
        if not path.is_file() or path.suffix not in suffixes:
            continue
        if ".git" in path.parts or "node_modules" in path.parts:
            continue
        if path.read_bytes().startswith(b"\xef\xbb\xbf"):
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert offenders == [], f"files start with a UTF-8 BOM: {offenders}"
