"""Everything a list's columns can be, as a tree a page can offer: the list's own columns, and below each relation the columns of the
record it points at, and so on.

A relation is both a leaf (it shows the display value of what it points at, and filters by a choice of those records) and a branch
(when its table has more to offer). The tree is made from the registry through the same `resolve` that checks a request, so it
offers a key exactly when a request would accept it: nothing denied, nothing past the depth limit, no table twice in a path, and no
walking into a table that only shows its name. Nothing in it is written per list.
"""

from northstar.errors import ValidationError
from northstar.lists.kinds import OPERATOR_NAMES, Category, Reference, Scaled
from northstar.lists.listdef import ListDef
from northstar.lists.registry import Catalog, Resolved


def _node(resolved: Resolved) -> dict:
    """What a page needs to know about one column: how to name it, draw it, and filter by it."""
    filtered_by = Reference() if resolved.relation is not None else resolved.kind        # a relation is filtered by a choice of records
    node = {
        "key": resolved.key, "label": resolved.labels[-1], "path_label": resolved.label, "kind": resolved.kind.code,
        "scale": resolved.kind.scale if isinstance(resolved.kind, Scaled) else None,
        "operators": [{"name": name, "label": OPERATOR_NAMES[name]} for name in filtered_by.operators],
        "choices": None,                                # "records" (see choices() in query.py), "values", or None: nothing to pick from
    }
    if resolved.relation is not None:
        node["choices"] = "records"
    elif isinstance(resolved.kind, Category):
        node["choices"], node["values"] = "values", list(resolved.kind.values)
    return node


def field_tree(catalog: Catalog, definition: ListDef) -> dict:
    """The tree of columns for a list: {"fields": [...], "relations": [... each with "children": the same shape, or None]}."""
    base = definition.table

    def walk(table: str, prefix: str, skip: str | None) -> dict:
        fields, relations = [], []
        for name in catalog.tables[table].fields:
            if name == skip:
                continue                                # the display column of a related record is the relation itself
            try:
                fields.append(_node(catalog.resolve(base, prefix + name)))
            except ValidationError:
                continue                                # a request would refuse it, so it is not offered
        for relation in catalog.relations(table).values():
            try:
                node = _node(catalog.resolve(base, prefix + relation.key))
            except ValidationError:
                continue
            target = catalog.tables[relation.target]
            children = walk(relation.target, prefix + relation.key + ".", target.display) if target.walkable else None
            node["children"] = children if children and (children["fields"] or children["relations"]) else None
            relations.append(node)
        relations.sort(key=lambda n: (n["label"].lower(), n["key"]))      # the database lists foreign keys in its own order: a person reads by name
        return {"fields": fields, "relations": relations}

    return walk(base, "", None)
