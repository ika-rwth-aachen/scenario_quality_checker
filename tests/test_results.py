"""Tests for the structured result model served to the browser."""

from quality_checker.quality_checker import DEFAULT_SCHEMA_PATH, FileQualityChecker
from quality_checker.thresholds import Thresholds
from quality_checker.webapp.results import (
    collect_findings,
    serialize_checker,
    summary_row_json,
)


def check(example, name, tmp_path, thresholds=None):
    """Run the checker on an example file inside a temporary working directory."""
    return FileQualityChecker(
        example(name), DEFAULT_SCHEMA_PATH, thresholds=thresholds, work_dir=tmp_path
    )


def test_dynamic_findings_carry_the_measured_peak(example, tmp_path):
    """A dynamics finding must name the entity, its peak and the limit."""
    checker = check(example, "envelope_dynamic_error_1.xosc", tmp_path)

    dynamic = [f for f in collect_findings(checker) if f["category"] in {"acceleration", "sideslip"}]

    assert dynamic, "the dynamic error example should produce dynamic findings"
    finding = dynamic[0]
    assert finding["entity"]
    assert finding["unit"] in {"m/s^2", "rad"}
    assert finding["peak_value"] > 0
    assert finding["peak_time"] >= 0
    assert finding["threshold"] > 0
    # The peak has to actually exceed the limit it is reported against.
    assert finding["peak_value"] > finding["threshold"]


def test_file_errors_become_categorized_findings(example, tmp_path):
    """The file_errors tuple is split into its four labelled categories."""
    checker = check(example, "envelope_file_error_1.xosc", tmp_path)

    findings = collect_findings(checker)
    categories = {f["category"] for f in findings}

    assert categories & {"entity_definition", "init_position", "intersection", "in_out"}
    assert all(f["severity"] == "error" for f in findings if f["category"] == "entity_definition")


def test_schema_errors_are_reported_as_errors(example, tmp_path):
    """An invalid file yields xsd findings and no parsed scenario."""
    checker = check(example, "envelope_xsd_not_valid_1.xosc", tmp_path)

    result = serialize_checker(checker, "run", "envelope_xsd_not_valid_1.xosc")

    assert result["status"]["xml_loadable"] is True
    assert result["status"]["xsd_valid"] is False
    assert result["status"]["scenario_parsed"] is False
    assert result["counts"]["errors"] > 0
    assert all(f["category"] == "xsd" for f in result["findings"])


def test_unloadable_xml_serializes_without_findings(example, tmp_path):
    """A file that is not XML must serialize cleanly rather than raise."""
    checker = check(example, "envelope_xml_not_loadable.xosc", tmp_path)

    result = serialize_checker(checker, "run", "envelope_xml_not_loadable.xosc")

    assert result["status"] == {
        "xml_loadable": False,
        "xsd_valid": False,
        "scenario_parsed": False,
        "simulation_status": "not done",
    }
    assert result["counts"] == {"errors": 0, "warnings": 0}
    assert result["metadata"]["road_users"] == {"total": 0, "by_type": {}}


def test_road_user_total_is_an_integer(example, tmp_path):
    """The checker stores 'total' as a string; the API must expose a number."""
    checker = check(example, "envelope_dynamic_error_1.xosc", tmp_path)

    road_users = serialize_checker(checker, "run", "x.xosc")["metadata"]["road_users"]

    assert isinstance(road_users["total"], int)
    assert road_users["total"] == sum(road_users["by_type"].values())


def test_findings_list_errors_before_warnings(example, tmp_path):
    """Severity ordering lets the UI render groups without re-sorting."""
    checker = check(example, "envelope_file_error_1.xosc", tmp_path)

    severities = [f["severity"] for f in collect_findings(checker)]

    assert severities == sorted(severities, key=lambda s: 0 if s == "error" else 1)


def test_serialized_urls_reference_the_run(example, tmp_path):
    """Plot and report URLs are built from the run id."""
    checker = check(example, "envelope_dynamic_error_1.xosc", tmp_path)

    result = serialize_checker(checker, "abc123", "x.xosc", plots=[("speed", "Speed over time")])

    assert result["plots"][0]["url"] == "/api/runs/abc123/plots/speed.png"
    assert result["downloads"] == {
        "pdf": "/api/runs/abc123/report.pdf",
        "csv": "/api/runs/abc123/report.csv",
    }


def test_reported_thresholds_are_the_ones_used(example, tmp_path):
    """Overridden limits must be echoed back, not the Config defaults."""
    limits = Thresholds.from_mapping({"acceleration_warning": 1.5})

    checker = check(example, "envelope_dynamic_error_1.xosc", tmp_path, thresholds=limits)
    result = serialize_checker(checker, "run", "x.xosc")

    assert result["thresholds"]["acceleration_warning"] == 1.5


def test_summary_row_maps_missing_counts_to_null(example, tmp_path):
    """to_summary_row()'s '-' placeholder becomes None for JSON."""
    checker = check(example, "envelope_xml_not_loadable.xosc", tmp_path)

    row = summary_row_json(checker, "run", "envelope_xml_not_loadable.xosc")

    assert row["n_file_errors"] is None
    assert row["n_dynamic_errors"] is None
    assert row["xml_loadable"] is False


def test_summary_row_keeps_real_counts(example, tmp_path):
    """A fully checked file reports integer counts."""
    checker = check(example, "envelope_file_error_1.xosc", tmp_path)

    row = summary_row_json(checker, "run", "envelope_file_error_1.xosc")

    assert isinstance(row["n_file_errors"], int)
    assert row["n_errors"] >= row["n_file_errors"]
