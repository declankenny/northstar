"""The server and the TypeScript files each list the views of every kind of report section, and the lists must be the same. Step 1 has
types only; the test that every view has a component is added with the renderers. Synthetic data only."""

import re
from pathlib import Path

from northstar.reports import sections

TS = (Path(__file__).resolve().parent.parent / "frontend" / "src" / "reports" / "views.ts").read_text(encoding="utf-8")


def _names(text: str) -> tuple[str, ...]:
    return tuple(re.findall(r'"([a-z_]+)"', text))


def test_the_typescript_view_vocabulary_is_the_servers():
    block = re.search(r"export const VIEWS = \{(.*?)\} as const;", TS, re.S)
    assert block, "views.ts has no VIEWS"
    found = {kind: _names(views) for kind, views in re.findall(r"(\w+):\s*\[(.*?)\]", block.group(1))}
    assert found == {kind: tuple(views) for kind, views in sections.VIEWS.items()}


def test_the_views_that_need_size_agree_too():
    block = re.search(r"export const VIEWS_THAT_NEED_SIZE = \[(.*?)\] as const;", TS, re.S)
    assert block, "views.ts has no VIEWS_THAT_NEED_SIZE"
    assert set(_names(block.group(1))) == set(sections.NEEDS_SIZE)


def test_every_kind_the_server_accepts_has_views_and_none_is_reserved():
    assert set(sections.VIEWS) == set(sections.KINDS)
    assert not set(sections.RESERVED) & set(sections.VIEWS)
