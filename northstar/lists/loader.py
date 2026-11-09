"""Where list definitions come from. The framework reads a definition only through this module, never by importing one, so
where definitions are kept can change later without touching anything else."""

from northstar.errors import NotFoundError
from northstar.lists.listdef import ListDef

_DEFINITIONS: dict[str, ListDef] = {}


def register(definition: ListDef) -> None:
    """Make a list available. Definitions are code, registered when the module that holds them is imported."""
    if definition.key in _DEFINITIONS:
        raise ValueError(f"The list {definition.key} is already registered.")
    _DEFINITIONS[definition.key] = definition


def get_list_definition(key: str) -> ListDef:
    try:
        return _DEFINITIONS[key]
    except (KeyError, TypeError):
        raise NotFoundError("That list does not exist.") from None
