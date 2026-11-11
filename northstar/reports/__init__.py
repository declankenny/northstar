"""The report framework: a Reports area where each report is a definition in code, and everything else is shared behaviour here.

A report declares its parameters, the sections of its result and a calculation. The framework checks a definition when it is
registered, reads and checks a request, builds the context a calculation runs in, checks what the calculation returns and
packages it. A calculation never reads raw filters, never works out who may see what, and never returns a partial result.
See docs/design/reporting/design.md.
"""
