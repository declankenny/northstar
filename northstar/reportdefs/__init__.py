"""The reports Northstar offers. Each is code: its parameters, the sections of its result and a calculation. The framework in
northstar/reports reads a definition through `northstar.reports.loader` and never imports one, so adding a report edits no framework
file. Each report registers itself when its module is imported, and this package imports them all."""

from northstar.reports import loader  # noqa: F401  (the place definitions register themselves)
from northstar.reportdefs import assets_liabilities  # noqa: F401,E402
from northstar.reportdefs import net_worth_bridge  # noqa: F401,E402
