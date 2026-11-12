"""The request for one view of a list, checked against the registry before anything reaches SQL."""

from dataclasses import dataclass

from northstar.errors import ValidationError
from northstar.lists.kinds import Reference
from northstar.lists.listdef import PAGE_SIZES, ListDef
from northstar.lists.registry import Catalog

_ALLOWED = {"columns", "filters", "search", "sort", "group", "page", "page_size", "params"}
# A fixed list (not customisable) takes only a sort, a page and what its scope needs.
_CUSTOM = {"columns", "filters", "search", "group", "page_size"}
MAX_COLUMNS = 60
MAX_FILTERS = 30
MAX_SEARCH = 100


@dataclass(frozen=True)
class Condition:
    key: str
    operator: str
    value: object                                   # already read by the field's kind


class ConditionProblem(ValidationError):
    """A filter that cannot be used, and which one: its place in the list (`index`) and the part that is wrong (`part`: "field",
    "operator" or "value", or None when the condition as a whole is not shaped right). To a list it is an ordinary ValidationError."""

    def __init__(self, message: str, index: int, part: str | None):
        super().__init__(message)
        self.index = index
        self.part = part


def parse_conditions(catalog: Catalog, base: str, raw, refusal=None) -> tuple[Condition, ...]:
    """The filters of a request, read against the registry from table `base`: each field one the registry offers, each operator one
    its kind allows, each value one its kind can read, and no field twice. `refusal`, when given, is asked about every field and
    answers with why it may not be used (or None): a report's own exclusions. A problem is a ConditionProblem saying which condition
    and which part of it."""
    if not isinstance(raw, (list, tuple)) or len(raw) > MAX_FILTERS:
        raise ValidationError("The filters must be a list.")
    filters, seen = [], set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict) or set(item) - {"field", "operator", "value"} or "field" not in item:
            raise ConditionProblem("Each filter needs a field, an operator and a value.", index, None)
        key = item["field"]
        try:
            resolved = catalog.resolve(base, key)
        except ValidationError as error:
            raise ConditionProblem(str(error), index, "field") from None
        if refusal is not None and (why := refusal(key)):
            raise ConditionProblem(why, index, "field")
        if key in seen:
            raise ConditionProblem("A column can have one filter.", index, "field")
        seen.add(key)
        kind = Reference() if resolved.relation else resolved.kind      # a relation is filtered by the id it points at
        operator = item.get("operator")
        try:
            kind.check_operator(operator)
        except ValidationError as error:
            raise ConditionProblem(str(error), index, "operator") from None
        try:
            filters.append(Condition(key, operator, kind.read(operator, item.get("value"))))
        except ValidationError as error:
            raise ConditionProblem(str(error), index, "value") from None
    return tuple(filters)


@dataclass(frozen=True)
class ListRequest:
    columns: tuple[str, ...]
    filters: tuple[Condition, ...]
    search: str
    sort_key: str
    direction: str
    group: str | None
    page: int
    page_size: int
    params: tuple[tuple[str, int], ...] = ()          # what the list's scope needs, by name: the id of a record


def _whole(value, name: str, low: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < low:
        raise ValidationError(f"The {name} must be a whole number of {low} or more.")
    return value


def parse_request(catalog: Catalog, definition: ListDef, data: dict | None) -> ListRequest:
    """The request as a ListRequest, or a ValidationError that says what is wrong. Nothing in `data` is trusted."""
    data = data or {}
    if not isinstance(data, dict):
        raise ValidationError("The request must be an object.")
    unknown = sorted(set(data) - _ALLOWED)
    if unknown:
        raise ValidationError(f"Unknown request field: {', '.join(map(str, unknown))}.")
    base = definition.table
    if not definition.customisable and _CUSTOM & set(data):
        raise ValidationError("That list cannot be changed.")

    raw_params = data.get("params", {})
    if not isinstance(raw_params, dict) or set(raw_params) != set(definition.params):
        raise ValidationError(f"That list needs: {', '.join(definition.params) or 'nothing'}.")
    params = tuple((name, _whole(raw_params[name], name, 1)) for name in definition.params)

    columns = data.get("columns", definition.columns)
    if not isinstance(columns, (list, tuple)) or not columns or len(columns) > MAX_COLUMNS:
        raise ValidationError("Choose at least one column.")
    if not all(isinstance(key, str) for key in columns):
        raise ValidationError("That column does not exist.")
    if len(set(columns)) != len(columns):
        raise ValidationError("A column can be shown once.")
    for key in columns:
        catalog.resolve(base, key)

    filters = parse_conditions(catalog, base, data.get("filters", []))

    search = data.get("search", "")
    if not isinstance(search, str) or len(search) > MAX_SEARCH:
        raise ValidationError(f"Search for up to {MAX_SEARCH} characters.")

    sort = data.get("sort")
    if sort is None:
        sort_key, direction = definition.sort
    else:
        if not isinstance(sort, dict) or set(sort) - {"field", "direction"} or "field" not in sort:
            raise ValidationError("Sort by a column, ascending or descending.")
        sort_key, direction = sort["field"], sort.get("direction", "asc")
    catalog.resolve(base, sort_key)
    if not definition.customisable and sort_key not in definition.columns:
        raise ValidationError("Sort by one of the columns.")
    if direction not in ("asc", "desc"):
        raise ValidationError("Sort ascending or descending.")

    group = data.get("group")
    if group is not None:
        grouped = catalog.resolve(base, group)
        if not grouped.groupable:
            raise ValidationError(f"{grouped.labels[-1]} cannot be grouped.")

    page = _whole(data.get("page", 1), "page", 1)
    page_size = data.get("page_size", definition.page_size)
    if definition.customisable and page_size not in PAGE_SIZES:     # a fixed list has its own size, which is not one a person chooses
        raise ValidationError(f"Show {', '.join(map(str, PAGE_SIZES))} rows per page.")
    return ListRequest(tuple(columns), filters, search.strip(), sort_key, direction, group, page, page_size, params)
