"""Where report definitions come from. The framework reads a definition only through this module, never by importing one, so adding a
report edits no framework file."""

from northstar.errors import NotFoundError
from northstar.reports.reportdef import ReportDef, check

_DEFINITIONS: dict[str, ReportDef] = {}


def register(definition: ReportDef) -> None:
    """Make a report available. It is checked first, so a broken definition stops the application starting."""
    check(definition)
    if definition.key in _DEFINITIONS:
        raise ValueError(f"The report {definition.key} is already registered.")
    _DEFINITIONS[definition.key] = definition


def get_report(key: str) -> ReportDef:
    try:
        return _DEFINITIONS[key]
    except (KeyError, TypeError):
        raise NotFoundError("That report does not exist.") from None


def visible_to(user) -> list[ReportDef]:
    """The reports this person may see, by title."""
    return sorted((d for d in _DEFINITIONS.values() if user["is_admin"] or not d.admin_only), key=lambda d: (d.title.lower(), d.key))
