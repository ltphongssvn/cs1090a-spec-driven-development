# src/cs1090a_spec_driven_development/__init__.py
# THE PACKAGE ROOT, DELIBERATELY EMPTY OF LOGIC.
#
# An __init__.py that re-exports submodules turns `import package` into an
# import of EVERYTHING, so a slow or failing module breaks callers that never
# used it. Names are imported from the module that defines them.
#
# This file exists because the wheel target names this directory, and because
# src layout requires the package to be importable only once INSTALLED -- which
# is the point: tests exercise what ships.
