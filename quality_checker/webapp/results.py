"""
Turn a FileQualityChecker into a browser-ready, structured result.

The CLI communicates through PDF and CSV reports, where prose is fine. A web UI
needs to filter, sort and label findings, so every finding is emitted as a record
with a severity, a category, the entity it concerns and - for the dynamics checks
- the measured peak and the limit it exceeded.
"""

from __future__ import annotations

import math

from ..thresholds import Thresholds

#: Labels for the four entries of FileQualityChecker.file_errors.
FILE_ERROR_CATEGORIES = (
    ("entity_definition", "Missing entity definition"),
    ("init_position", "Identical initial position"),
    ("intersection", "Intersecting entities"),
    ("in_out", "Missing in/out entity"),
)

#: (index in dynamic_errors, metric, severity) for the dynamics findings.
DYNAMIC_ERROR_SLOTS = (
    (0, "acceleration", "error"),
    (1, "acceleration", "warning"),
    (2, "swimangle", "error"),
    (3, "swimangle", "warning"),
)

#: Display label and unit per dynamics metric.
METRIC_LABELS = {
    "acceleration": ("Acceleration", "m/s^2"),
    "swimangle": ("Sideslip angle", "rad"),
}

#: The PNG files plot_dynamics() and plot_vehicle_paths() produce.
PLOT_FILES = (
    ("speed", "Speed over time", "speed_plot.png"),
    ("acceleration", "Acceleration over time", "acceleration_plot.png"),
    ("swimangle", "Sideslip angle over time", "swimangle_plot.png"),
    ("paths", "Vehicle paths", "vehicle_paths.png"),
)


def dynamic_peak(checker, entity_name, metric_name):
    """
    Return the largest absolute value of a metric and when it occurred.

    Args:
        checker: FileQualityChecker instance.
        entity_name: Entity to inspect.
        metric_name: Column name, 'acceleration' or 'swimangle'.
    return: (peak_value, peak_time) or None when no trace data is available.
    """
    try:
        positions, times = checker._get_dynamic_data()[entity_name]
        dataframe = checker._build_dynamic_data_df(positions, times)
        dataframe = checker._calculate_acceleration_swimangle(dataframe)
        values = dataframe[metric_name].abs().dropna()
        if values.empty:
            return None
        peak_index = values.idxmax()
        raw_time = dataframe.loc[peak_index, "time"]
        peak_time = (
            None if raw_time is None or math.isnan(raw_time) else float(raw_time)
        )
        return float(values.loc[peak_index]), peak_time
    except Exception:  # noqa: BLE001 - trace details are a nice-to-have.
        return None


def _finding(severity, category, message, **extra):
    """Build one finding record, dropping keys that carry no information."""
    finding = {"severity": severity, "category": category, "message": message}
    finding.update({key: value for key, value in extra.items() if value is not None})
    return finding


def _dynamic_finding(checker, entity_name, metric_name, severity, thresholds):
    """Build a dynamics finding enriched with the measured peak and the limit."""
    label, unit = METRIC_LABELS[metric_name]
    peak = dynamic_peak(checker, entity_name, metric_name)
    peak_value, peak_time = peak if peak else (None, None)

    message = f"{label} {severity} for {entity_name}"
    if metric_name == "swimangle":
        message += " (heading differs from direction of travel)"

    return _finding(
        severity,
        "acceleration" if metric_name == "acceleration" else "sideslip",
        message,
        entity=entity_name,
        metric=metric_name,
        unit=unit,
        peak_value=peak_value,
        peak_time=peak_time,
        threshold=thresholds.limit(metric_name, severity),
    )


def collect_findings(checker):
    """
    Return every finding of a completed check as a list of records.

    Args:
        checker: FileQualityChecker instance.
    return: List of finding dicts, errors first.
    """
    thresholds = getattr(checker, "thresholds", None) or Thresholds.default()
    findings = []

    for entry in getattr(checker, "xsd_errors", None) or []:
        findings.append(_finding("error", "xsd", str(entry)))

    file_errors = getattr(checker, "file_errors", None) or ([], [], [], [])
    for (category, label), entries in zip(FILE_ERROR_CATEGORIES, file_errors):
        for entry in entries or []:
            findings.append(
                _finding("error", category, f"{label}: {entry}", entity=str(entry))
            )

    dynamic_errors = getattr(checker, "dynamic_errors", None) or ([], [], [], [])
    for index, metric_name, severity in DYNAMIC_ERROR_SLOTS:
        if index >= len(dynamic_errors):
            continue
        for entity_name in dynamic_errors[index] or []:
            findings.append(
                _dynamic_finding(
                    checker, entity_name, metric_name, severity, thresholds
                )
            )

    for entry in getattr(checker, "position_resolution_warnings", None) or []:
        findings.append(_finding("warning", "position_resolution", str(entry)))

    findings.sort(key=lambda finding: 0 if finding["severity"] == "error" else 1)
    return findings


def _road_users(checker):
    """Return the road-user counts with 'total' separated out and coerced to int."""
    counts = getattr(checker, "road_user_counts", None) or {}
    by_type = {}
    total = 0
    for road_user, count in counts.items():
        if road_user is None:
            continue
        try:
            value = int(count)
        except (TypeError, ValueError):
            continue
        if road_user == "total":
            total = value
        else:
            by_type[str(road_user)] = value
    return {"total": total, "by_type": by_type}


def _optional_int(value):
    """Map to_summary_row()'s '-' placeholder to None, keep real counts."""
    return value if isinstance(value, int) else None


def summary_row_json(checker, run_id=None, file_name=None):
    """
    Return one aggregated-table row as JSON-safe values.

    Args:
        checker: FileQualityChecker instance.
        run_id: Identifier used to fetch the detailed result.
        file_name: Display name of the scenario file.
    return: Dict with the columns of the aggregated report.
    """
    _, xml_loadable, xsd_valid, simulation_status, n_file_errors, n_dynamic_errors = (
        checker.to_summary_row()
    )
    findings = collect_findings(checker)
    return {
        "run_id": run_id,
        "file_name": file_name or str(getattr(checker, "file_path", "")),
        "xml_loadable": bool(xml_loadable),
        "xsd_valid": bool(xsd_valid),
        "simulation_status": simulation_status,
        "n_file_errors": _optional_int(n_file_errors),
        "n_dynamic_errors": _optional_int(n_dynamic_errors),
        "n_errors": sum(1 for f in findings if f["severity"] == "error"),
        "n_warnings": sum(1 for f in findings if f["severity"] == "warning"),
    }


def serialize_checker(checker, run_id, file_name, plots=(), map_info=None):
    """
    Return the full structured result for one checked scenario.

    Args:
        checker: FileQualityChecker instance.
        run_id: Identifier the plot and report URLs are built from.
        file_name: Display name of the uploaded scenario file.
        plots: Iterable of (name, label) pairs that were actually rendered.
        map_info: Optional dict describing the companion OpenDRIVE file.
    return: JSON-serializable dict.
    """
    thresholds = getattr(checker, "thresholds", None) or Thresholds.default()
    findings = collect_findings(checker)
    version = getattr(checker, "version", None)

    return {
        "run_id": run_id,
        "file_name": file_name,
        "status": {
            "xml_loadable": bool(getattr(checker, "xml_loadable", False)),
            "xsd_valid": bool(getattr(checker, "xsd_valid", False)),
            "scenario_parsed": getattr(checker, "scenario", None) is not None,
            "simulation_status": getattr(checker, "simulation_status", "not done"),
        },
        "metadata": {
            "version": version.replace("-", ".") if version else None,
            "author": getattr(checker, "author", None),
            "date": getattr(checker, "date", None),
            "road_users": _road_users(checker),
        },
        "thresholds": thresholds.as_dict(),
        "counts": {
            "errors": sum(1 for f in findings if f["severity"] == "error"),
            "warnings": sum(1 for f in findings if f["severity"] == "warning"),
        },
        "findings": findings,
        "map": map_info or {"uploaded": False},
        "plots": [
            {
                "name": name,
                "label": label,
                "url": f"/api/runs/{run_id}/plots/{name}.png",
            }
            for name, label in plots
        ],
        "downloads": {
            "pdf": f"/api/runs/{run_id}/report.pdf",
            "csv": f"/api/runs/{run_id}/report.csv",
        },
    }
