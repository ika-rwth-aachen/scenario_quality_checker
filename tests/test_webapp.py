"""Tests for the HTTP interface of the Scenario Quality Checker."""

import csv
import io
import shutil
import time
import zipfile

import pytest

from conftest import created, upload


def test_health_and_thresholds(client):
    """The service reports itself and its default limits."""
    assert client.get("/api/health").json()["status"] == "ok"

    payload = client.get("/api/thresholds").json()

    assert payload["defaults"] == {
        "acceleration_warning": 9.8,
        "acceleration_error": 29.4,
        "sideslip_warning": 0.1,
        "sideslip_error": 0.2,
    }


def test_index_and_examples_are_served(client):
    """The frontend and the bundled example list are reachable."""
    assert client.get("/").status_code == 200

    examples = client.get("/api/examples").json()["examples"]

    assert "envelope_dynamic_error_1.xosc" in examples


def test_index_offers_the_legal_notices(client):
    """The imprint link and the data privacy controls reach the user."""
    body = client.get("/").text

    assert "https://scenario.center/imprint/" in body
    assert "https://scenario.center/privacy-policy/" in body
    assert 'id="data-privacy"' in body
    assert 'id="forget-session"' in body


def test_index_offers_the_help_dialog(client):
    """The help button and the dialog it fills reach the user."""
    body = client.get("/").text

    assert 'id="help"' in body
    assert 'id="help-dialog"' in body
    assert 'id="help-content"' in body


def test_help_explains_the_web_interface(client):
    """
    The help must keep naming what the interface actually offers.

    Like the privacy notice, it repeats configurable defaults and labels that
    live in the code, and help that quietly disagrees with the app misleads
    rather than helps.
    """
    payload = client.get("/api/help").json()

    help_text = payload["text"]
    assert ".xosc" in help_text
    assert ".xodr" in help_text
    assert "Check quality" in help_text
    assert "Thresholds" in help_text
    assert "20 MiB" in help_text
    assert "50 files" in help_text
    assert "not done" in help_text

    assert "<h2>" in payload["html"]
    assert "<table>" in payload["html"]


def test_index_offers_the_about_dialog(client):
    """The about button and the dialog it fills reach the user."""
    body = client.get("/").text

    assert 'id="about"' in body
    assert 'id="about-dialog"' in body
    assert 'id="about-content"' in body


def test_about_carries_the_funding_acknowledgement(client):
    """
    The acknowledgement is a grant obligation, so it must survive rendering.

    The images are asserted on because they are the fragile part: the renderer
    disables embedded HTML, so an <img> tag written by hand would be escaped
    into visible text instead of a logo.
    """
    payload = client.get("/api/about").json()

    about = payload["text"]
    assert "SYNERGIES" in about
    assert "Funded by the European Union" in about
    assert "CINEA" in about
    assert "github.com/ika-rwth-aachen/scenario_quality_checker" in about

    html = payload["html"]
    assert '<img src="/branding/synergies.svg"' in html
    assert '<img src="/branding/funded_by_eu.svg"' in html


def test_branding_assets_used_by_the_about_dialog_are_served(client):
    """
    A renamed or unpackaged logo must fail here, not as a broken image.

    The mount is conditional on the directory existing, so this also covers the
    case where the assets are missing from an installed package entirely.
    """
    for name in ("synergies.svg", "funded_by_eu.svg"):
        response = client.get(f"/branding/{name}")

        assert response.status_code == 200, name
        # Without a viewBox the logos cannot be scaled down for the dialog:
        # they would be cropped to their top-left corner instead.
        assert "viewBox" in response.text, name


def test_data_privacy_notice_documents_application_processing(client):
    """
    The notice must keep naming what the application actually does.

    Asserting on the limits is the point: they are configurable defaults that
    someone will eventually change, and a privacy notice that quietly disagrees
    with the code is worse than none.
    """
    payload = client.get("/api/data-privacy").json()

    notice = payload["text"]
    assert "sqc_session" in notice
    assert "1 hour" in notice
    assert "20 MiB" in notice
    assert "50 files" in notice
    assert "200 MiB" in notice
    assert "Delete my uploads now" in notice

    assert "<h2>" in payload["html"]


def test_packaged_markdown_renders_without_embedded_html(tmp_path):
    """
    The renderer must neutralise HTML and send links away safely.

    The notice itself carries neither today, so rendering it would not exercise
    either guarantee - and the frontend assigns the result with innerHTML.
    """
    from quality_checker.webapp.server import render_markdown

    source = tmp_path / "sample.md"
    source.write_text(
        "[policy](https://scenario.center/privacy-policy/)\n\n<script>alert(1)</script>\n",
        encoding="utf-8",
    )

    html = render_markdown(source)

    assert 'target="_blank" rel="noopener noreferrer"' in html
    assert "<script>" not in html


def test_clearing_a_session_removes_its_files(client, example):
    """The erase button's endpoint really drops the uploads, not just the cookie."""
    from quality_checker.webapp.server import WORK_ROOT

    result = created(
        client.post("/api/checks", files=upload(example("envelope_file_error_1.xosc")))
    )
    session_id = client.cookies["sqc_session"]
    assert (WORK_ROOT / session_id).is_dir()

    assert client.delete("/api/session").json() == {"cleared": True}

    assert not (WORK_ROOT / session_id).exists()
    assert "sqc_session" not in client.cookies
    assert client.get(f"/api/runs/{result['run_id']}").status_code == 404


def test_valid_scenario_reports_no_issues(client, example):
    """A clean scenario checks out without findings."""
    result = created(
        client.post(
            "/api/checks", files=upload(example("envelope_xsd_valid_v1-2.xosc"))
        )
    )

    assert result["status"]["scenario_parsed"] is True
    assert result["counts"] == {"errors": 0, "warnings": 0}
    assert result["findings"] == []


def test_scenario_with_issues_reports_findings(client, example):
    """A scenario with entity problems reports them as errors."""
    result = created(
        client.post("/api/checks", files=upload(example("envelope_file_error_1.xosc")))
    )

    assert result["counts"]["errors"] > 0
    assert any(f["severity"] == "error" for f in result["findings"])


def test_plots_are_rendered_and_served(client, example):
    """Every advertised plot URL returns a PNG."""
    result = created(
        client.post(
            "/api/checks", files=upload(example("envelope_dynamic_error_1.xosc"))
        )
    )

    assert {plot["name"] for plot in result["plots"]} == {
        "speed",
        "acceleration",
        "swimangle",
        "paths",
    }
    for plot in result["plots"]:
        response = client.get(plot["url"])
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        assert response.content.startswith(b"\x89PNG")


def test_unknown_plot_is_rejected(client, example):
    """Only the known plot names are addressable."""
    result = created(
        client.post(
            "/api/checks", files=upload(example("envelope_dynamic_error_1.xosc"))
        )
    )

    assert (
        client.get(f"/api/runs/{result['run_id']}/plots/secrets.png").status_code == 404
    )


def test_reports_can_be_downloaded(client, example):
    """The PDF and CSV reports are generated on demand."""
    result = created(
        client.post(
            "/api/checks", files=upload(example("envelope_dynamic_error_1.xosc"))
        )
    )

    pdf = client.get(result["downloads"]["pdf"])
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF-")

    report = client.get(result["downloads"]["csv"])
    assert report.status_code == 200
    rows = list(csv.reader(io.StringIO(report.text)))
    # The scenario_file column must not leak the server-side temporary path.
    assert rows[0] == ["scenario_file", "envelope_dynamic_error_1.xosc"]


def test_a_run_can_be_fetched_again(client, example):
    """Results stay addressable for the session that created them."""
    result = created(
        client.post("/api/checks", files=upload(example("envelope_file_error_1.xosc")))
    )

    again = client.get(f"/api/runs/{result['run_id']}")

    assert again.status_code == 200
    assert again.json()["file_name"] == result["file_name"]
    assert again.json()["counts"] == result["counts"]


def test_unknown_run_is_not_found(client):
    """Run ids from other sessions or old processes are rejected."""
    assert client.get("/api/runs/0123456789abcdef0123456789abcdef").status_code == 404


def test_example_can_be_checked_without_uploading(client):
    """The bundled examples are checkable by name."""
    result = created(
        client.post("/api/checks", data={"example": "envelope_file_error_1.xosc"})
    )

    assert result["file_name"] == "envelope_file_error_1.xosc"


def test_unknown_example_is_not_found(client):
    """An example name that does not exist is a 404, not a crash."""
    assert client.post("/api/checks", data={"example": "nope.xosc"}).status_code == 404


def test_missing_input_is_rejected(client):
    """Neither an upload nor an example means nothing to check."""
    response = client.post("/api/checks")

    assert response.status_code == 400
    assert "scenario" in response.json()["detail"]


def test_wrong_suffix_is_rejected(client):
    """Only .xosc files are accepted as scenarios."""
    response = client.post(
        "/api/checks", files={"scenario": ("notes.txt", b"hello", "text/plain")}
    )

    assert response.status_code == 400
    assert ".xosc" in response.json()["detail"]


def test_empty_upload_is_rejected(client):
    """An empty file cannot be checked."""
    response = client.post(
        "/api/checks", files={"scenario": ("a.xosc", b"", "application/xml")}
    )

    assert response.status_code == 400


def test_oversized_upload_is_rejected(client, monkeypatch):
    """Uploads past the configured limit are refused with 413."""
    from quality_checker.webapp import server

    monkeypatch.setattr(server, "MAX_UPLOAD_BYTES", 512)

    response = client.post(
        "/api/checks", files={"scenario": ("big.xosc", b"x" * 4096, "application/xml")}
    )

    assert response.status_code == 413


def test_threshold_override_changes_severities(client, example):
    """A lower warning limit turns quiet entities into warnings."""
    baseline = created(
        client.post(
            "/api/checks", files=upload(example("envelope_xsd_valid_v1-1.xosc"))
        )
    )

    lowered = created(
        client.post(
            "/api/checks",
            files=upload(example("envelope_xsd_valid_v1-1.xosc")),
            data={"acceleration_warning": "0.05"},
        )
    )

    assert lowered["thresholds"]["acceleration_warning"] == 0.05
    assert lowered["counts"]["warnings"] > baseline["counts"]["warnings"]
    # The process-wide defaults must be unaffected.
    assert (
        client.get("/api/thresholds").json()["defaults"]["acceleration_warning"] == 9.8
    )


def test_invalid_threshold_is_rejected(client, example):
    """Negative or inverted limits are refused with an explanation."""
    negative = client.post(
        "/api/checks",
        files=upload(example("envelope_xsd_valid_v1-1.xosc")),
        data={"acceleration_warning": "-1"},
    )
    assert negative.status_code == 400
    assert "positive" in negative.json()["detail"]

    inverted = client.post(
        "/api/checks",
        files=upload(example("envelope_xsd_valid_v1-1.xosc")),
        data={"acceleration_warning": "50", "acceleration_error": "10"},
    )
    assert inverted.status_code == 400
    assert "must not exceed" in inverted.json()["detail"]


def test_uploaded_map_is_linked_where_the_scenario_expects_it(client, example):
    """A map upload resolves the scenario's LogicFile reference."""
    scenario = example("envelope_dynamic_error_1.xosc")
    map_bytes = b"<OpenDRIVE><road id='1' length='10'></road></OpenDRIVE>"

    result = created(
        client.post(
            "/api/checks",
            files={
                "scenario": (scenario.name, scenario.read_bytes(), "application/xml"),
                "map": ("unrelated_name.xodr", map_bytes, "application/xml"),
            },
        )
    )

    assert result["map"]["uploaded"] is True
    assert result["map"]["referenced_by_scenario"] is True
    # Stored under the referenced name, not the uploaded one.
    assert result["map"]["linked_as"].endswith("envelope_1.xodr")
    assert result["map"]["note"] is None


def test_missing_map_is_pointed_out(client, example):
    """A scenario referencing a map says so when none was uploaded."""
    result = created(
        client.post(
            "/api/checks", files=upload(example("envelope_dynamic_error_1.xosc"))
        )
    )

    assert result["map"]["uploaded"] is False
    assert result["map"]["referenced_by_scenario"] is True
    assert "Upload it as well" in result["map"]["note"]


def test_map_reference_outside_the_upload_area_is_refused(client):
    """An absolute LogicFile path must not be written to."""
    scenario = (
        b"<OpenSCENARIO><FileHeader revMajor='1' revMinor='0' date='2024-01-01T00:00:00' "
        b"description='d' author='a'/><RoadNetwork><LogicFile filepath='/etc/passwd'/>"
        b"</RoadNetwork></OpenSCENARIO>"
    )

    result = created(
        client.post(
            "/api/checks",
            files={
                "scenario": ("absolute.xosc", scenario, "application/xml"),
                "map": ("m.xodr", b"<OpenDRIVE/>", "application/xml"),
            },
        )
    )

    assert result["map"]["linked_as"].endswith("m.xodr")
    assert "outside the upload area" in result["map"]["note"]


def test_wrong_map_suffix_is_rejected(client, example):
    """Only OpenDRIVE files are accepted as maps."""
    scenario = example("envelope_xsd_valid_v1-2.xosc")

    response = client.post(
        "/api/checks",
        files={
            "scenario": (scenario.name, scenario.read_bytes(), "application/xml"),
            "map": ("payload.exe", b"binary", "application/octet-stream"),
        },
    )

    assert response.status_code == 400
    assert ".xodr" in response.json()["detail"]


def batch_files(example, names):
    """Build the repeated multipart field a batch request expects."""
    return [
        ("scenarios", (name, example(name).read_bytes(), "application/xml"))
        for name in names
    ]


BATCH_NAMES = [
    "envelope_dynamic_error_1.xosc",
    "envelope_file_error_1.xosc",
    "envelope_xml_not_loadable.xosc",
]


def test_batch_summarizes_every_file(client, example):
    """Each uploaded scenario becomes one row of the aggregated table."""
    batch = created(
        client.post("/api/batches", files=batch_files(example, BATCH_NAMES))
    )

    assert [row["file_name"] for row in batch["files"]] == BATCH_NAMES
    unloadable = batch["files"][2]
    assert unloadable["xml_loadable"] is False
    assert unloadable["n_file_errors"] is None


def test_batch_reports_can_be_downloaded(client, example):
    """The aggregated PDF and CSV cover the whole batch."""
    batch = created(
        client.post("/api/batches", files=batch_files(example, BATCH_NAMES))
    )

    pdf = client.get(batch["downloads"]["pdf"])
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF-")

    report = client.get(batch["downloads"]["csv"])
    assert report.status_code == 200
    rows = list(csv.reader(io.StringIO(report.text)))
    assert rows[0][0] == "scenario_file"
    assert [row[0] for row in rows[1:]] == BATCH_NAMES


def test_batch_rows_drill_down_into_a_full_result(client, example):
    """Opening a batch row yields the detailed result including plots."""
    batch = created(
        client.post("/api/batches", files=batch_files(example, BATCH_NAMES))
    )

    response = client.get(f"/api/runs/{batch['files'][0]['run_id']}")

    assert response.status_code == 200
    result = response.json()
    assert result["file_name"] == BATCH_NAMES[0]
    assert result["plots"], "plots are rendered lazily when a row is opened"
    assert client.get(result["plots"][0]["url"]).status_code == 200


def test_batch_accepts_a_zip_archive(client, example):
    """A .zip is unpacked and its scenarios are checked."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name in BATCH_NAMES:
            archive.writestr(f"nested/{name}", example(name).read_bytes())
        archive.writestr("readme.txt", "ignored")
    buffer.seek(0)

    batch = created(
        client.post(
            "/api/batches",
            files=[("scenarios", ("pack.zip", buffer.read(), "application/zip"))],
        )
    )

    assert sorted(row["file_name"] for row in batch["files"]) == sorted(BATCH_NAMES)


def test_zip_path_traversal_is_refused(client):
    """Archive members must stay inside the upload directory."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("../escaped.xosc", "<OpenSCENARIO/>")
    buffer.seek(0)

    response = client.post(
        "/api/batches",
        files=[("scenarios", ("bad.zip", buffer.read(), "application/zip"))],
    )

    assert response.status_code == 400
    assert "escapes" in response.json()["detail"]


def test_batch_without_scenarios_is_rejected(client):
    """An archive holding no .xosc has nothing to check."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("readme.txt", "nothing here")
    buffer.seek(0)

    response = client.post(
        "/api/batches",
        files=[("scenarios", ("empty.zip", buffer.read(), "application/zip"))],
    )

    assert response.status_code == 400
    assert "No .xosc" in response.json()["detail"]


def test_batch_file_count_is_capped(client, example, monkeypatch):
    """Too many files at once are refused before any checking happens."""
    from quality_checker.webapp import server

    monkeypatch.setattr(server, "MAX_BATCH_FILES", 2)

    response = client.post("/api/batches", files=batch_files(example, BATCH_NAMES))

    assert response.status_code == 400
    assert "at most 2" in response.json()["detail"].lower()


def test_runs_are_private_to_their_session(client, example):
    """A second browser session cannot read another session's run."""
    result = created(
        client.post("/api/checks", files=upload(example("envelope_file_error_1.xosc")))
    )
    client.cookies.clear()

    assert client.get(f"/api/runs/{result['run_id']}").status_code == 404


def test_cleanup_keeps_directories_another_process_is_using():
    """
    Startup cleanup must not delete a co-tenant's live working directories.

    A second worker, a reloaded server or a parallel test run shares the working
    root. Its directories are unknown to this process but actively in use, so only
    directories older than the session TTL may be removed.
    """
    from quality_checker.webapp.server import WORK_ROOT, SessionStore

    store = SessionStore(ttl_seconds=3600)
    fresh = WORK_ROOT / ("a" * 32)
    stale = WORK_ROOT / ("b" * 32)
    for directory in (fresh, stale):
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "upload.xosc").write_text("<OpenSCENARIO/>")
    # Backdate the stale directory well past the TTL.
    import os

    old = time.time() - 7200
    os.utime(stale, (old, old))

    store.cleanup_orphaned_directories()

    assert (fresh / "upload.xosc").is_file(), "a co-tenant's fresh upload was deleted"
    assert not stale.exists()
    shutil.rmtree(fresh, ignore_errors=True)


def test_session_store_stays_bounded():
    """Unbounded traffic must not grow the session registry without limit."""
    from quality_checker.webapp.server import SessionStore

    # No eviction grace: every session is immediately a candidate, which is the
    # old behaviour and the one that keeps the registry bounded.
    store = SessionStore(ttl_seconds=3600, max_sessions=5, eviction_grace_seconds=0)
    for index in range(50):
        store.get_or_create(f"{index:032x}")

    assert len(store._sessions) <= 5


def test_active_sessions_are_not_evicted_by_new_ones():
    """
    A burst of new sessions must not throw out the ones people are using.

    Session creation is anonymous and free, so without this the cheapest denial
    of service available is to open MAX_SESSIONS connections and watch every
    working directory get deleted.
    """
    from quality_checker.webapp.server import SessionCapacityError, SessionStore

    store = SessionStore(ttl_seconds=3600, max_sessions=3, eviction_grace_seconds=60)
    active = [store.get_or_create(f"{index:032x}") for index in range(3)]

    with pytest.raises(SessionCapacityError):
        store.get_or_create("f" * 32)

    assert all(session.session_id in store._sessions for session in active)
