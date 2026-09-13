# src/cs1090a_spec_driven_development/contracts/__init__.py
# THE CONTRACT PACKAGE, DELIBERATELY EMPTY OF LOGIC AND OF RE-EXPORTS.
#
# Every boundary type in this service lives under this package, and nothing
# else does. That separation is load-bearing rather than tidy: the architecture
# gate can assert that `contracts` imports nothing from the rest of the
# application, which is what makes "the contract does not depend on the
# implementation" a checked fact instead of an intention.
#
# NO RE-EXPORTS HERE. Hoisting names into this file would let a caller import
# from `contracts` without naming the module that defines the type, and the
# import graph would stop showing which boundary a caller actually depends on.
