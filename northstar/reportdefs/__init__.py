"""The reports Northstar offers. Each is code: its parameters, the sections of its result and a calculation. The framework in
northstar/reports reads a definition through `northstar.reports.loader` and never imports one, so adding a report edits no framework
file. There are none yet: the first is added with the report that proves the framework."""

from northstar.reports import loader  # noqa: F401  (the place definitions register themselves)
