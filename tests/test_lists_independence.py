"""The list engine does not know Northstar. It may use the standard library, the error types and itself, and nothing else:
no household table, no currency, no rate. What is particular to Northstar lives outside `northstar/lists/` and is handed to the
engine as data and functions."""

import ast
import pathlib
import re
import sys

ENGINE = pathlib.Path(__file__).parent.parent / "northstar" / "lists"
ALLOWED_NORTHSTAR = {"northstar.errors", "northstar.lists"}
FORBIDDEN = re.compile(r"(currency|currencies|exchange|balances?|accounts?|net_?worth)", re.IGNORECASE)


def imports(path: pathlib.Path):
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            yield node.module


def test_an_engine_module_imports_only_the_standard_library_the_errors_and_itself():
    for path in ENGINE.glob("*.py"):
        for name in imports(path):
            top = name.split(".")[0]
            ok = top in sys.stdlib_module_names or name in ALLOWED_NORTHSTAR or name.startswith("northstar.lists")
            assert ok, f"{path.name} imports {name}, which is not part of the engine"


def test_no_engine_module_names_money_or_the_household():
    """A cheap check on the words, because the boundary above cannot see a table name written in a string."""
    for path in ENGINE.glob("*.py"):
        found = FORBIDDEN.search(path.read_text(encoding="utf-8"))
        assert not found, f"{path.name} mentions {found.group(0)}"
