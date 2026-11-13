"""The shapes a calculation returns for each kind of section, as named types, for report authors and for reading code.

They are annotations: nothing here checks anything. `northstar.reports.sections` is what checks a payload, at run time, and a test
fails if the two ever disagree about which fields exist. `frontend/src/reports/types.ts` has the same shapes, with the kind-to-payload
mapping a renderer uses.
"""

from typing import Literal, NotRequired, TypedDict

# -- links --


class EntityLink(TypedDict):
    to: Literal["account", "balance"]
    id: int


class ListLink(TypedDict):
    to: Literal["list"]
    list: str
    filters: NotRequired[list[dict]]


Link = EntityLink | ListLink

# -- summary --


class SummaryItem(TypedDict):
    key: str
    label: str
    kind: Literal["money", "count", "date", "text"]
    value: int | str
    currency: NotRequired[str]                      # money only, when it is not in the system currency
    note: NotRequired[str]


class SummaryData(TypedDict):
    items: list[SummaryItem]


# -- series --


class SeriesPoint(TypedDict):
    x: str                                          # a date
    value: int


class SeriesLine(TypedDict):
    key: str
    label: str
    kind: Literal["money", "count"]
    points: list[SeriesPoint]


class SeriesData(TypedDict):
    series: list[SeriesLine]


# -- hierarchy --


class Colour(TypedDict):
    kind: str                                       # what the id is the id of, such as "account_type"
    id: int                                         # the entity's id, from 1: the page turns it into a slot of the palette


class HierarchyNode(TypedDict):
    id: str
    label: str
    value: int                                      # signed financial value; a parent equals the sum of its children
    size: NotRequired[int]                          # a leaf of a sized section only; the framework adds each parent's
    link: NotRequired[Link]
    opening: NotRequired[int]                       # a comparison between two dates: the amount at each end, of which `value` is the change
    closing: NotRequired[int]
    note: NotRequired[str]                          # one short line the report writes, such as a balance date
    colour: NotRequired[Colour]                     # the entity the colour comes from; without one a node takes its parent's
    children: NotRequired[list["HierarchyNode"]]


class HierarchyData(TypedDict):
    nodes: list[HierarchyNode]


# -- rows --


class NativeMoney(TypedDict):
    minor: int
    currency: str


class Column(TypedDict):
    key: str
    label: str
    kind: Literal["text", "money", "native_money", "date", "count"]


class Row(TypedDict):
    id: str
    cells: dict[str, str | int | NativeMoney | None]
    link: NotRequired[Link]


class RowsData(TypedDict):
    columns: list[Column]
    rows: list[Row]


SectionPayload = SummaryData | SeriesData | HierarchyData | RowsData
PAYLOADS = {"summary": SummaryData, "series": SeriesData, "hierarchy": HierarchyData, "rows": RowsData}


class Note(TypedDict):
    code: str
    text: str
    section: NotRequired[str]
