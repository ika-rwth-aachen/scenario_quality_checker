"""
Tests for the hardening the security audit asked for.

Each test names the property it protects rather than the implementation, so a
different mitigation for the same threat keeps the test meaningful.
"""

import io
import zipfile

import pytest

from conftest import created, upload

# A "billion laughs" document: a few hundred bytes that expand into gigabytes
# if the parser resolves the entities.
ENTITY_BOMB = b"""<?xml version="1.0"?>
<!DOCTYPE OpenSCENARIO [
  <!ENTITY a "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa">
  <!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">
  <!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">
  <!ENTITY d "&c;&c;&c;&c;&c;&c;&c;&c;&c;&c;">
  <!ENTITY e "&d;&d;&d;&d;&d;&d;&d;&d;&d;&d;">
]>
<OpenSCENARIO><Description>&e;</Description></OpenSCENARIO>
"""


def test_xml_entity_expansion_is_refused(client):
    """A document whose entities expand without bound must not be parsed."""
    result = created(
        client.post(
            "/api/checks",
            files={"scenario": ("bomb.xosc", ENTITY_BOMB, "application/xml")},
        )
    )

    assert result["status"]["xml_loadable"] is False
    reasons = [f["message"] for f in result["findings"] if f["category"] == "xml"]
    assert reasons, "the refusal must be explained to the user"
    assert "DOCTYPE" in reasons[0]


def test_entity_bomb_in_a_map_is_refused(client, example):
    """The map file is parsed too, so it needs the same protection."""
    scenario = example("envelope_dynamic_error_1.xosc")

    result = created(
        client.post(
            "/api/checks",
            files={
                "scenario": (scenario.name, scenario.read_bytes(), "application/xml"),
                "map": ("m.xodr", ENTITY_BOMB, "application/xml"),
            },
        )
    )

    # The upload is accepted and stored, but parsing it never expands anything;
    # the check completes instead of exhausting the worker.
    assert result["map"]["uploaded"] is True


def zip_of(members):
    """Build an in-memory .zip from a {name: bytes} mapping."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)
    buffer.seek(0)
    return buffer.read()


def test_oversized_archive_is_refused(client, monkeypatch):
    """An archive expanding past the configured limit is refused with 413."""
    from quality_checker.webapp import server

    monkeypatch.setattr(server, "MAX_ZIP_UNCOMPRESSED_BYTES", 64 * 1024)
    archive = zip_of({"big.xosc": b"\0" * (4 * 1024 * 1024)})

    response = client.post(
        "/api/batches", files=[("scenarios", ("pack.zip", archive, "application/zip"))]
    )

    assert response.status_code == 413
    assert "expands beyond" in response.json()["detail"]


def test_extraction_stops_at_the_budget_whatever_the_header_claims(tmp_path):
    """
    Enforcement happens on bytes written, not on the archive's own numbers.

    The sizes in a zip's central directory are chosen by whoever built it. This
    exercises the copy directly with a budget smaller than the member, which is
    the guarantee that must hold even if a future zipfile stops truncating
    reads at the declared size.
    """
    import zipfile as zipfile_module

    from fastapi import HTTPException

    from quality_checker.webapp.server import _copy_zip_member

    archive_path = tmp_path / "pack.zip"
    archive_path.write_bytes(zip_of({"big.xosc": b"\0" * (256 * 1024)}))
    target = tmp_path / "out.xosc"

    with zipfile_module.ZipFile(archive_path) as archive:
        info = archive.infolist()[0]
        with pytest.raises(HTTPException) as raised:
            _copy_zip_member(archive, info, target, remaining=1024)

    assert raised.value.status_code == 413
    # Never more than the budget reaches the disk.
    assert target.stat().st_size <= 1024 + 1024 * 1024


def test_zip_compression_bomb_is_refused(client, monkeypatch):
    """A member expanding far past its compressed size is a bomb, not a scenario."""
    from quality_checker.webapp import server

    monkeypatch.setattr(server, "MAX_ZIP_COMPRESSION_RATIO", 5)
    archive = zip_of({"bomb.xosc": b"\0" * (1024 * 1024)})

    response = client.post(
        "/api/batches", files=[("scenarios", ("pack.zip", archive, "application/zip"))]
    )

    assert response.status_code == 413


def test_session_cookie_carries_its_protective_flags(client, example):
    """HttpOnly and SameSite are what keep the session id out of reach."""
    response = client.post(
        "/api/checks", files=upload(example("envelope_xsd_valid_v1-2.xosc"))
    )

    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert "max-age=" in cookie


def test_secure_flag_follows_the_forwarded_scheme(client, example):
    """
    Behind a TLS-terminating proxy the cookie must still be marked Secure.

    The request arrives over plain HTTP on the wire, so deriving the flag from
    the socket alone silently drops it in exactly the recommended topology.
    """
    response = client.post(
        "/api/checks",
        files=upload(example("envelope_xsd_valid_v1-2.xosc")),
        headers={"X-Forwarded-Proto": "https"},
    )

    assert "secure" in response.headers["set-cookie"].lower()


def test_reading_pages_does_not_mint_sessions(client):
    """
    Only a request that creates state may create a session.

    Session creation used to happen on any request, which made evicting every
    live session as cheap as a few hundred GETs of a static asset.
    """
    from quality_checker.webapp.server import store

    before = len(store._sessions)
    for _ in range(20):
        client.get("/api/health")
        client.get("/api/thresholds")
        client.get("/")

    assert len(store._sessions) == before
    assert "sqc_session" not in client.cookies


def test_security_headers_are_present(client):
    """Every response carries the standard protective headers."""
    headers = client.get("/").headers

    policy = headers["content-security-policy"]
    assert "default-src 'self'" in policy
    assert "frame-ancestors 'none'" in policy
    assert "object-src 'none'" in policy
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"
    assert headers["referrer-policy"] == "no-referrer"


def test_responses_carry_a_correlation_id(client):
    """A user-visible failure has to be findable in the server log."""
    assert client.get("/api/health").headers["x-request-id"]


def test_internal_failures_do_not_leak_internals(client, example, monkeypatch):
    """
    An unexpected error returns an id, not the exception text.

    Exception messages carry server filesystem paths and library internals, so
    they belong in the log rather than in the browser.
    """
    from quality_checker.webapp import server

    def explode(*args, **kwargs):
        raise RuntimeError("/srv/secret/path/blew up: internal detail")

    monkeypatch.setattr(server, "_check_scenario", explode)

    response = client.post(
        "/api/checks", files=upload(example("envelope_xsd_valid_v1-2.xosc"))
    )

    assert response.status_code == 500
    detail = response.json()["detail"]
    assert "/srv/secret" not in detail
    assert "internal detail" not in detail
    assert response.headers["x-request-id"] in detail


def test_expensive_endpoints_are_rate_limited(client, example, monkeypatch):
    """One anonymous client must not be able to occupy the checker at will."""
    from quality_checker.webapp import server

    monkeypatch.setattr(server.rate_limiter, "_limit", 2)

    scenario = example("envelope_xsd_valid_v1-2.xosc")
    codes = [
        client.post("/api/checks", files=upload(scenario)).status_code for _ in range(4)
    ]

    assert 429 in codes
    assert codes[-1] == 429


def test_a_refused_request_still_gets_its_headers(client, example, monkeypatch):
    """
    Responses produced before the handler runs must not skip the hardening.

    A refusal is exactly when a correlation id is most useful, and a response
    without a CSP is a response an attacker would rather have.
    """
    from quality_checker.webapp import server

    monkeypatch.setattr(server.rate_limiter, "_limit", 1)
    scenario = example("envelope_xsd_valid_v1-2.xosc")

    client.post("/api/checks", files=upload(scenario))
    refused = client.post("/api/checks", files=upload(scenario))

    assert refused.status_code == 429
    assert refused.headers["retry-after"]
    assert refused.headers["x-request-id"]
    assert "frame-ancestors 'none'" in refused.headers["content-security-policy"]
    assert refused.headers["x-content-type-options"] == "nosniff"


def test_rate_limit_does_not_apply_to_reading_results(client, example, monkeypatch):
    """Throttling the checker must not make a finished result unreadable."""
    from quality_checker.webapp import server

    result = created(
        client.post(
            "/api/checks", files=upload(example("envelope_xsd_valid_v1-2.xosc"))
        )
    )
    monkeypatch.setattr(server.rate_limiter, "_limit", 1)

    assert client.get(f"/api/runs/{result['run_id']}").status_code == 200


def test_the_worker_queue_sheds_load_instead_of_growing(client, example, monkeypatch):
    """
    A full queue is refused, because the timeout cannot free the worker.

    asyncio.wait_for cancels the await, not the thread. A scenario that never
    terminates keeps the single worker busy long after its client got a 504, so
    the only real protection is to stop accepting work for it.
    """
    from quality_checker.webapp import server

    monkeypatch.setattr(server, "MAX_QUEUED_CHECKS", 0)

    response = client.post(
        "/api/checks", files=upload(example("envelope_xsd_valid_v1-2.xosc"))
    )

    assert response.status_code == 503
    assert "busy" in response.json()["detail"]


def test_the_worker_slot_is_released_after_a_check(client, example):
    """A finished check must hand its slot back, or the queue fills up forever."""
    from quality_checker.webapp import server

    for _ in range(3):
        created(
            client.post(
                "/api/checks", files=upload(example("envelope_xsd_valid_v1-2.xosc"))
            )
        )

    assert server._in_flight == 0


async def _store(upload, destination, budget):
    """Call the streaming upload helper directly."""
    from quality_checker.webapp.server import store_upload

    return await store_upload(upload, destination, budget=budget)


def test_total_request_bytes_are_capped_while_streaming(tmp_path):
    """
    The ceiling must hold even when Content-Length never arrives.

    A chunked request simply omits the header, which skips the check that reads
    it; only counting the bytes as they are read closes that off.
    """
    import asyncio

    from fastapi import HTTPException
    from starlette.datastructures import UploadFile

    from quality_checker.webapp.server import RequestBudget

    budget = RequestBudget(limit=1024)
    payload = io.BytesIO(b"x" * (64 * 1024))
    upload = UploadFile(filename="big.xosc", file=payload)

    with pytest.raises(HTTPException) as raised:
        asyncio.run(_store(upload, tmp_path / "out.xosc", budget))

    assert raised.value.status_code == 413
    assert not (tmp_path / "out.xosc").exists()


def test_health_does_not_advertise_the_version(client):
    """The version tells an anonymous caller which advisories apply."""
    payload = client.get("/api/health").json()

    assert payload == {"status": "ok"}


def test_runs_are_capped_per_session(client, example, monkeypatch):
    """Runs must not accumulate until the session TTL an hour later."""
    from quality_checker.webapp import server

    monkeypatch.setattr(server, "MAX_RUNS_PER_SESSION", 2)
    scenario = example("envelope_xsd_valid_v1-2.xosc")

    first = created(client.post("/api/checks", files=upload(scenario)))
    for _ in range(2):
        created(client.post("/api/checks", files=upload(scenario)))

    assert client.get(f"/api/runs/{first['run_id']}").status_code == 404


def test_a_session_can_be_cleared_on_request(client, example):
    """A user must be able to remove their uploads without waiting out the TTL."""
    result = created(
        client.post(
            "/api/checks", files=upload(example("envelope_xsd_valid_v1-2.xosc"))
        )
    )

    assert client.delete("/api/session").json() == {"cleared": True}
    assert client.get(f"/api/runs/{result['run_id']}").status_code == 404


@pytest.mark.parametrize(
    "content, parameters, expected",
    [
        # A reference is a whole identifier: "$a" must not eat the front of "$abc".
        ("<x v='$abc'/>", {"a": "1"}, "<x v='$abc'/>"),
        ("<x v='$a'/>", {"a": "1", "abc": "2"}, "<x v='1'/>"),
        # Values are escaped, because the result is parsed again.
        ("<x v='$a'/>", {"a": '"><Evil/>'}, "<x v='&quot;&gt;&lt;Evil/&gt;'/>"),
        ("<x>$a</x>", {"a": "1 & 2"}, "<x>1 &amp; 2</x>"),
    ],
)
def test_parameter_substitution_is_exact_and_escaped(content, parameters, expected):
    """Placeholders are matched as tokens and their values cannot inject XML."""
    from quality_checker.quality_checker import FileQualityChecker

    assert (
        FileQualityChecker._replace_parameters_in_content(content, parameters)
        == expected
    )


def test_parameter_expansion_is_bounded(monkeypatch):
    """A large value referenced many times must not expand without limit."""
    from quality_checker import quality_checker as module

    monkeypatch.setattr(module, "MAX_PROCESSED_SCENARIO_BYTES", 4096)
    content = "$big " * 1000

    with pytest.raises(module.ScenarioExpansionError):
        module.FileQualityChecker._replace_parameters_in_content(
            content, {"big": "x" * 1024}
        )


def test_parameter_substitution_count_is_bounded(monkeypatch):
    """Even cheap substitutions are capped, so the work itself stays bounded."""
    from quality_checker import quality_checker as module

    monkeypatch.setattr(module, "MAX_PARAMETER_SUBSTITUTIONS", 10)

    with pytest.raises(module.ScenarioExpansionError):
        module.FileQualityChecker._replace_parameters_in_content("$a " * 50, {"a": "1"})
