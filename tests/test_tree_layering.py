"""The one structural rule of the new tree: `catalog/` may not import `core/`.

Step 5's gate names it, and it is not decoration. `catalog/` fetches and parses;
every gate in the project is pure and lives in `core/`. The moment a source
module can reach a gate, it can start deciding — and then "the OPAC returns the
unfiltered set for an unknown parameter" stops being a fact about an API and
becomes a bug in a judgement three layers away.

It is a static check on purpose. Importing `catalog` and inspecting it would
prove only that the modules loaded today do not; reading the source proves it of
every module in the package, including one added next week and not yet imported
by anything.
"""

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "catalog"
CORE = ROOT / "core"


def imported_modules(path: Path) -> set:
    """Every module name this file imports, however it spells it."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            if node.level:                       # from . import x  /  from .http import y
                out.add(f".{node.module}" if node.module else ".")
            elif node.module:
                out.add(node.module)
    return out


def sources(package: Path):
    return sorted(p for p in package.glob("*.py"))


@pytest.mark.parametrize("path", sources(CATALOG), ids=lambda p: p.name)
def test_no_catalog_module_imports_core(path):
    offenders = sorted(m for m in imported_modules(path)
                       if m == "core" or m.startswith("core."))
    assert offenders == [], (
        f"catalog/{path.name} imports {offenders}. A source module never "
        "decides: move the judgement into core/, or the helper it needs into "
        "catalog/ where its convention belongs (see `title_of` and "
        "`strip_disambiguator`).")


@pytest.mark.parametrize("path", sources(CORE), ids=lambda p: p.name)
def test_no_core_module_opens_a_socket(path):
    """`core/` is pure. It may read `catalog/langs.py`'s vocabulary and nothing
    else of `catalog/`, because everything else there does I/O."""
    allowed = {"catalog", "catalog.langs"}
    reached = sorted(m for m in imported_modules(path)
                     if (m == "catalog" or m.startswith("catalog.")) and m not in allowed)
    assert reached == [], (
        f"core/{path.name} imports {reached}. core/ is offline by construction; "
        "only catalog/langs.py, which is a table, may be read from here.")
    assert "requests" not in imported_modules(path)


def test_every_core_module_is_importable_without_the_network():
    """`conftest.py` blocks `socket.connect` for the whole session, so an import
    that reached a catalogue would fail here rather than quietly succeed."""
    for path in sources(CORE):
        if path.name == "__init__.py":
            continue
        name = f"core.{path.stem}"
        __import__(name)
        assert name in sys.modules
