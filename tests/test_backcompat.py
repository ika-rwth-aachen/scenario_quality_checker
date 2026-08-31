"""
The CLI and the library API predate the web interface.

scenario.generator calls quality_check_single() and the checker's private
helpers directly, so these signatures and defaults must not drift.
"""

import inspect

import pytest

from quality_checker.config import Config
from quality_checker.quality_checker import (
    DEFAULT_SCHEMA_PATH,
    FileQualityChecker,
    quality_check_single,
)
from quality_checker.thresholds import Thresholds


def test_checker_works_without_the_new_arguments(example):
    """The pre-existing four-argument constructor still runs the pipeline."""
    checker = FileQualityChecker(
        example("envelope_xsd_valid_v1-2.xosc"), DEFAULT_SCHEMA_PATH, None, False
    )

    assert checker.xml_loadable
    assert checker.xsd_valid
    assert checker.scenario is not None
    assert checker.thresholds == Thresholds.default()


def test_quality_check_single_keeps_its_parameter_order():
    """New options are appended, so existing positional calls keep working."""
    parameters = list(inspect.signature(quality_check_single).parameters)

    assert parameters[:7] == [
        "file_path",
        "out_path",
        "schema_path",
        "esmini_path",
        "out_pdf",
        "out_csv",
        "print_log",
    ]


def test_private_helpers_used_by_consumers_exist():
    """scenario.generator reaches into these to report metric peaks."""
    for name in (
        "_get_dynamic_data",
        "_build_dynamic_data_df",
        "_calculate_acceleration_swimangle",
    ):
        assert callable(getattr(FileQualityChecker, name))


def test_work_dir_keeps_intermediate_files_out_of_the_cwd(
    example, tmp_path, monkeypatch
):
    """An injected work_dir replaces the default ./results/tmp location."""
    monkeypatch.chdir(tmp_path)
    work_dir = tmp_path / "elsewhere"

    FileQualityChecker(
        example("envelope_xsd_valid_v1-2.xosc"), DEFAULT_SCHEMA_PATH, work_dir=work_dir
    )

    assert work_dir.is_dir()
    assert not (tmp_path / "results").exists()


def test_default_thresholds_come_from_config():
    """Config stays the single source of the default limits."""
    defaults = Thresholds.default()

    # approx because Config states the limits as products such as 9.8 * 3.
    assert defaults.acceleration_warning == pytest.approx(
        Config.ACCELERATION_WARNING_THRESHOLD
    )
    assert defaults.acceleration_error == pytest.approx(
        Config.ACCELERATION_ERROR_THRESHOLD
    )
    assert defaults.sideslip_warning == pytest.approx(
        Config.SWIMANGLE_WARNING_THRESHOLD
    )
    assert defaults.sideslip_error == pytest.approx(Config.SWIMANGLE_ERROR_THRESHOLD)


def test_overriding_thresholds_leaves_config_untouched(example, tmp_path):
    """Per-run limits must not leak into the process-wide defaults."""
    original = Config.ACCELERATION_WARNING_THRESHOLD
    limits = Thresholds.from_mapping(
        {"acceleration_warning": 0.01, "acceleration_error": 999}
    )

    checker = FileQualityChecker(
        example("envelope_xsd_valid_v1-1.xosc"),
        DEFAULT_SCHEMA_PATH,
        thresholds=limits,
        work_dir=tmp_path,
    )

    assert checker.dynamic_errors[1], "a 0.01 m/s^2 warning limit should flag entities"
    assert Config.ACCELERATION_WARNING_THRESHOLD == original


def test_reports_create_their_output_directory(example, tmp_path):
    """Both report writers create out_path, which the web app relies on."""
    checker = FileQualityChecker(
        example("envelope_xsd_valid_v1-2.xosc"),
        DEFAULT_SCHEMA_PATH,
        work_dir=tmp_path / "tmp",
    )
    reports = tmp_path / "missing" / "reports"

    checker.create_single_report("Summary", reports)
    checker.create_csv("summary", reports, scenario_name="summary.xosc")

    assert (reports / "envelope_xsd_valid_v1-2.pdf").is_file()
    csv_text = (reports / "summary.csv").read_text()
    assert csv_text.splitlines()[0] == "scenario_file,summary.xosc"


def test_malformed_header_is_reported_instead_of_raised(tmp_path):
    """A file without a version header must not raise out of the constructor."""
    scenario = tmp_path / "no_header.xosc"
    scenario.write_text("<OpenSCENARIO><Storyboard/></OpenSCENARIO>")

    checker = FileQualityChecker(scenario, DEFAULT_SCHEMA_PATH, work_dir=tmp_path)

    assert checker.xml_loadable
    assert not checker.xsd_valid
    assert checker.xsd_errors
    assert "version" in checker.xsd_errors[0].lower()
