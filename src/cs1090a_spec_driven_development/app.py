# src/cs1090a_spec_driven_development/app.py
# THE ASGI APPLICATION. Transport only.
#
# API AS CODE, AND THE OPENAPI DOCUMENT IS GENERATED RATHER THAN WRITTEN. Every
# route declares pydantic request and response models, so the published schema
# is a FUNCTION of the types. A hand-maintained OpenAPI file is a second
# declaration of the same fact and drifts the first time someone edits one of
# them.
#
# THIS MODULE HOLDS NO DOMAIN RULES, AND THAT IS MECHANICALLY ENFORCED RATHER
# THAN MERELY INTENDED. mutmut 3 skips any decorated function, so every line
# inside an @app.post handler is invisible to mutation testing. A rule written
# here could be wrong in a way no test would notice and no mutant could reveal.
# Each handler therefore delegates in ONE line to an undecorated domain function
# that IS mutated.
#
# THE HANDLERS ARE SYNCHRONOUS ON PURPOSE. `determine` is pure CPU over a small
# object graph with no I/O; declaring it `async def` would run it on the event
# loop and block every other request for its duration. FastAPI runs a sync
# handler in a threadpool, which is the correct place for work that never
# awaits.

from importlib.metadata import version as distribution_version

from fastapi import FastAPI

from cs1090a_spec_driven_development.contracts.fmla import (
    Determination,
    DeterminationRequest,
    determine,
)
from cs1090a_spec_driven_development.contracts.health import HealthReport, ServiceStatus

DISTRIBUTION = "cs1090a-spec-driven-development"

app = FastAPI(
    title="Statutory Leave Compliance",
    description=(
        "FMLA eligibility determinations, with the rule chain that produced them. "
        "Every rule cites the provision of 29 CFR part 825 it applied."
    ),
    version=distribution_version(DISTRIBUTION),
)


@app.get(
    "/health",
    response_model=HealthReport,
    summary="Report whether the service can serve requests",
)
def health() -> HealthReport:
    """Report liveness.

    THE VERSION IS READ FROM INSTALLED METADATA, NOT RESTATED HERE. A literal
    would be a second copy of the number in pyproject.toml, and the copy that
    goes stale is always the one nobody looks at -- so the endpoint whose job is
    to say what is running would be the thing reporting a version that is not.
    """
    return HealthReport(
        status=ServiceStatus.OK,
        service=DISTRIBUTION,
        version=distribution_version(DISTRIBUTION),
    )


@app.post(
    "/fmla/determinations",
    response_model=Determination,
    summary="Determine FMLA eligibility, and return the rule chain that decided it",
)
def create_determination(request: DeterminationRequest) -> Determination:
    """Issue a determination.

    ONE LINE, DELIBERATELY. Everything a regulator would ask about lives in the
    domain module, where it is typed, unit-tested and mutation-tested. This
    function's only responsibility is that an HTTP request becomes a validated
    DeterminationRequest and a Determination becomes a response body -- both of
    which FastAPI does from the annotations.
    """
    return determine(request)
