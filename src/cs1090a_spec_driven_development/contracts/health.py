# src/cs1090a_spec_driven_development/contracts/health.py
# CONTRACT AS CODE. The published shape of the health response, declared before
# the route that returns it.
#
# WHY A MODEL FOR SOMETHING THIS SMALL. A route returning a bare dict publishes
# a contract that exists nowhere: nothing types it, nothing validates it, and
# the generated OpenAPI document describes it as an untyped object. The moment a
# consumer binds to that shape, an unreviewed dict literal has become an API.
#
# THE ENUM IS NOT DECORATION. `status: str` accepts "ok", "OK", "okay",
# "healthy" and "" -- four of which are typos and one of which is a lie. A
# closed set makes the illegal values unrepresentable rather than merely
# discouraged, which is this project's third standing construction constraint.

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ServiceStatus(StrEnum):
    """The states this service will admit to being in.

    DEGRADED EXISTS DELIBERATELY, even though nothing emits it yet. A binary
    up/down forces a service that is serving reads but failing writes to claim
    one or the other, and both claims are false.
    """

    OK = "ok"
    DEGRADED = "degraded"


class HealthReport(BaseModel):
    """What `GET /health` returns.

    FROZEN AND EXTRA-FORBIDDING. `extra="forbid"` means a field added to the
    payload but not to this model is an ERROR rather than silently dropped --
    which is the difference between a contract and a suggestion. `frozen=True`
    means a handler cannot mutate a report after constructing it, so the value
    validated is the value served.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: ServiceStatus = Field(
        description="Whether the service considers itself able to serve requests.",
    )
    service: str = Field(
        description="The distribution name, so a response identifies its own origin.",
    )
    version: str = Field(
        description="The running version, read from package metadata rather than restated.",
    )
