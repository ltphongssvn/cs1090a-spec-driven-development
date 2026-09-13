# src/cs1090a_spec_driven_development/app.py
# THE ASGI APPLICATION. Transport only.
#
# API AS CODE, AND THE OPENAPI DOCUMENT IS GENERATED RATHER THAN WRITTEN. Every
# route declares a pydantic response model, so the published schema is a
# FUNCTION of the types. A hand-maintained OpenAPI file is a second declaration
# of the same fact and drifts the first time someone edits only one of them.
#
# THIS MODULE HOLDS NO DOMAIN RULES, which is section 3.2.3 of the source
# enforced rather than remembered: routes handle HTTP, behaviour lives in
# services, and the boundary is checked by a gate rather than restated in each
# specification conversation.

from importlib.metadata import version as distribution_version

from fastapi import FastAPI

from cs1090a_spec_driven_development.contracts.health import HealthReport, ServiceStatus

DISTRIBUTION = "cs1090a-spec-driven-development"

app = FastAPI(
    title="Spec Governance",
    description=(
        "Governance for spec-driven development: how alive a specification is, "
        "where intent was lost, and whether the repair held."
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
