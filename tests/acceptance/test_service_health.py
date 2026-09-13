# tests/acceptance/test_service_health.py
# SLICE 1, THE OUTERMOST TEST. Deliberately the least interesting behaviour in
# the product.
#
# WHY SOMETHING THIS TRIVIAL COMES FIRST. This test's real subject is the
# HARNESS, not health. When slice 2 goes red we need to know the failure is the
# domain model and not the transport, the ASGI wiring, or the import path. A
# first slice that exercises real behaviour cannot tell those apart, because
# everything is unproven at once.
#
# NO SOCKET IS BOUND. httpx's ASGITransport calls the application directly in
# process, so this test is hermetic: no port, no server lifecycle, no network.
# That is what lets the whole acceptance suite sit behind a git hook, and a hook
# that needs a running server is a hook people disable.
#
# PYDANTIC-FIRST, EVEN HERE. The assertion does not read raw JSON keys. It
# validates the response against the CONTRACT, so a field renamed in the model
# fails this test rather than silently changing the published payload. Reading
# `body["status"]` would pass against any dict that happened to have that key.

import pytest
from httpx import ASGITransport, AsyncClient

from cs1090a_spec_driven_development.app import app
from cs1090a_spec_driven_development.contracts.health import HealthReport, ServiceStatus


@pytest.mark.acceptance
@pytest.mark.anyio
async def test_health_endpoint_reports_a_valid_health_report() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://spec-governance") as client:
        response = await client.get("/health")

    assert response.status_code == 200

    # STRONG ASSERTIONS, per section 2.1.2 of the source. The book's Listing 2.1
    # passes when the function returns everything; asserting only "a body came
    # back" would pass against an empty object, a 200 with no body, or a payload
    # from an entirely different route.
    report = HealthReport.model_validate(response.json())
    assert report.status is ServiceStatus.OK
    assert report.service == "cs1090a-spec-driven-development"
    assert report.version == "0.1.0"
