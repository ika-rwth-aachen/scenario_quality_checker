import tempfile
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
from loguru import logger
from matplotlib.lines import Line2D

from . import safe_xml
from .config import Config
from .pdf import *
from .thresholds import Thresholds


def create_report_single(checker, title, out_path):
    """
    Create a PDF report for a single scenario file.
    Args:
        checker: FileQualityChecker instance with analysis results.
        title: Title shown in the PDF header.
        out_path: Output directory for the PDF.
    """
    title_separation = -5
    subtitle_separation = -4

    pdf = PDF(title)
    pdf.add_page()

    Path(out_path).mkdir(parents=True, exist_ok=True)

    scenario_path = Path(checker.file_path)
    pdf.create_textbox(
        "General information",
        relative_position=[0, title_separation],
        font=Config.PDF_FONT_TITLE,
    )
    pdf.create_textbox(
        "     Scenario file: " + scenario_path.name,
        relative_position=[0, subtitle_separation],
        font=Config.PDF_FONT_SUBTITLE,
    )

    # XML must be parsable before any deeper checks are meaningful.
    if checker.xml_loadable:
        # XSD validity gates scenario-specific checks and plots.
        if checker.xsd_valid:
            # Scenario metadata (fallback to "-" when not provided).
            author = "Scenario author: "
            author += checker.author if checker.author else "-"
            pdf.create_textbox(
                "     " + author,
                relative_position=[0, subtitle_separation],
                font=Config.PDF_FONT_SUBTITLE,
            )

            date = "Scenario creation date: "
            date += checker.date if checker.date else "-"
            pdf.create_textbox(
                "     " + date,
                relative_position=[0, subtitle_separation],
                font=Config.PDF_FONT_SUBTITLE,
            )

            simulation_status = "Simulation: "
            simulation_status_value = getattr(checker, "simulation_status", "not done")
            simulation_status += simulation_status_value
            simulation_status_color = (
                Config.ERROR_COLOR if simulation_status_value == "failed" else (0, 0, 0)
            )

            # Scenario object required for counts, issues, and dynamics plots.
            if checker.scenario is not None:
                n_roadusers = "Road users in scenario: "
                road_users = checker.road_user_counts or {}
                n_total = road_users.get("total", 0)
                n_roadusers += str(n_total)
                pdf.create_textbox(
                    "     " + n_roadusers,
                    relative_position=[0, subtitle_separation],
                    font=Config.PDF_FONT_SUBTITLE,
                )

                for RU_type, count in road_users.items():
                    if RU_type != "total" and RU_type is not None:
                        pdf.create_textbox(
                            "     " + "      - " + str(count) + " " + RU_type + "s",
                            relative_position=[0, subtitle_separation],
                            font=Config.PDF_FONT_SUBTITLE,
                        )

                pdf.create_textbox(
                    "     " + simulation_status,
                    relative_position=[0, subtitle_separation],
                    font=Config.PDF_FONT_SUBTITLE,
                    color=simulation_status_color,
                )

                # Ensure a stable tuple shape for downstream unpacking.
                dynamic_errors = checker.dynamic_errors or ([], [], [], [])
                (
                    acceleration_errors,
                    acceleration_warnings,
                    swimangle_errors,
                    swimangle_warnings,
                ) = dynamic_errors
                simulation_based_dynamics = simulation_status_value == "succeeded"
                simulation_not_valid = simulation_status_value != "succeeded"
                dynamic_has_footnote = simulation_based_dynamics or simulation_not_valid
                analyzed_dynamics = {
                    "acceleration_errors": acceleration_errors,
                    "acceleration_warnings": acceleration_warnings,
                    "swimangle_errors": swimangle_errors,
                    "swimangle_warnings": swimangle_warnings,
                }
                # Render plots into a temporary directory before embedding in the PDF.
                temp_dir = tempfile.TemporaryDirectory()
                temp_dir_path = Path(temp_dir.name)
                plot_dynamics(checker, analyzed_dynamics, output_dir=temp_dir_path)

                try:
                    pdf.create_image(
                        temp_dir_path / "vehicle_paths.png",
                        relative_position=[85, -27],
                        size=(int(588 / 6), int(432 / 6)),
                    )
                except Exception:
                    pass

                pdf.create_textbox(
                    "Scenario evaluation",
                    relative_position=[0, title_separation + 5],
                    font=Config.PDF_FONT_TITLE,
                )
                # Grouped file-level issues (empty lists mean no issues).
                file_errors = checker.file_errors or ([], [], [], [])
                position_resolution_warnings = (
                    getattr(checker, "position_resolution_warnings", []) or []
                )
                # File issues section: show green checks when none exist.
                if np.sum([len(file_error) for file_error in file_errors]) == 0:
                    pdf.create_textbox(
                        text="4",
                        relative_position=[0, title_separation + 2],
                        font=Config.PDF_FONT_DING_TITLE,
                    )
                    pdf.create_textbox(
                        "     No file issues: ",
                        relative_position=[0, 2 * title_separation],
                        font=Config.PDF_FONT_TITLE_SMALL,
                    )
                    pdf.create_textbox(
                        text="     4",
                        relative_position=[0, subtitle_separation],
                        font=Config.PDF_FONT_DING_SUB,
                    )
                    pdf.create_textbox(
                        "          No faulty entity definitions",
                        relative_position=[0, 2 * subtitle_separation],
                        font=Config.PDF_FONT_SUBTITLE,
                    )
                    pdf.create_textbox(
                        text="     4",
                        relative_position=[0, subtitle_separation],
                        font=Config.PDF_FONT_DING_SUB,
                    )
                    pdf.create_textbox(
                        "          No identical initial positions",
                        relative_position=[0, 2 * subtitle_separation],
                        font=Config.PDF_FONT_SUBTITLE,
                    )
                    pdf.create_textbox(
                        text="     4",
                        relative_position=[0, subtitle_separation],
                        font=Config.PDF_FONT_DING_SUB,
                    )
                    pdf.create_textbox(
                        "          No intersecting entities",
                        relative_position=[0, 2 * subtitle_separation],
                        font=Config.PDF_FONT_SUBTITLE,
                    )
                    pdf.create_textbox(
                        text="     4",
                        relative_position=[0, subtitle_separation],
                        font=Config.PDF_FONT_DING_SUB,
                    )
                    pdf.create_textbox(
                        "          No missing adds/inits",
                        relative_position=[0, 2 * subtitle_separation],
                        font=Config.PDF_FONT_SUBTITLE,
                    )

                    if len(position_resolution_warnings) > 0:
                        for warning in position_resolution_warnings:
                            pdf.create_textbox(
                                text="     8",
                                relative_position=[0, subtitle_separation],
                                font=Config.PDF_FONT_DING_SUB,
                                color=Config.WARNING_COLOR,
                            )
                            pdf.create_textbox(
                                "          " + warning,
                                relative_position=[0, 2 * subtitle_separation],
                                font=Config.PDF_FONT_SUBTITLE,
                                color=Config.WARNING_COLOR,
                            )
                else:
                    # File issues section: show errors per category.
                    (
                        missing_entity_definitions,
                        identical_initposition_entities,
                        intersecting_entities,
                        missing_in,
                    ) = file_errors
                    pdf.create_textbox(
                        text="8",
                        relative_position=[0, title_separation + 2],
                        font=Config.PDF_FONT_DING_TITLE,
                        color=Config.ERROR_COLOR,
                    )
                    pdf.create_textbox(
                        "     File issues",
                        relative_position=[0, 2 * title_separation],
                        font=Config.PDF_FONT_TITLE_SMALL,
                        color=Config.ERROR_COLOR,
                    )
                    # Faulty entity definitions.
                    if len(missing_entity_definitions) > 0:
                        pdf.create_textbox(
                            text="     8",
                            relative_position=[0, subtitle_separation],
                            font=Config.PDF_FONT_DING_SUB,
                            color=Config.ERROR_COLOR,
                        )
                        pdf.create_textbox(
                            "          Faulty entity definitions: "
                            + str(", ".join(missing_entity_definitions)),
                            relative_position=[0, 2 * subtitle_separation],
                            font=Config.PDF_FONT_SUBTITLE,
                            color=Config.ERROR_COLOR,
                        )
                    else:
                        pdf.create_textbox(
                            text="     4",
                            relative_position=[0, subtitle_separation],
                            font=Config.PDF_FONT_DING_SUB,
                        )
                        pdf.create_textbox(
                            "          No faulty entity definitions",
                            relative_position=[0, 2 * subtitle_separation],
                            font=Config.PDF_FONT_SUBTITLE,
                        )

                    # Identical initial positions.
                    if len(identical_initposition_entities) > 0:
                        pdf.create_textbox(
                            text="     8",
                            relative_position=[0, subtitle_separation],
                            font=Config.PDF_FONT_DING_SUB,
                            color=Config.ERROR_COLOR,
                        )
                        # Single pair vs. multiple pairs formatting.
                        if len(identical_initposition_entities) == 1:
                            identical_initposition_entities = (
                                identical_initposition_entities[0]
                            )

                            pdf.create_textbox(
                                "          Identical initial positions: "
                                + str(", ".join(identical_initposition_entities)),
                                relative_position=[0, 2 * subtitle_separation],
                                font=Config.PDF_FONT_SUBTITLE,
                                color=Config.ERROR_COLOR,
                            )
                        else:
                            identical_initposition_entities = [
                                str(tuple(element)).replace("'", "")
                                for element in identical_initposition_entities
                            ]

                            pdf.create_textbox(
                                "          Identical initial positions: "
                                + str(", ".join(identical_initposition_entities)),
                                relative_position=[0, 2 * subtitle_separation],
                                font=Config.PDF_FONT_SUBTITLE,
                                color=Config.ERROR_COLOR,
                            )
                    else:
                        pdf.create_textbox(
                            text="     4",
                            relative_position=[0, subtitle_separation],
                            font=Config.PDF_FONT_DING_SUB,
                        )
                        pdf.create_textbox(
                            "          No identical initial positions",
                            relative_position=[0, 2 * subtitle_separation],
                            font=Config.PDF_FONT_SUBTITLE,
                        )

                    # Intersecting entities.
                    if len(intersecting_entities) > 0:
                        pdf.create_textbox(
                            text="     8",
                            relative_position=[0, subtitle_separation],
                            font=Config.PDF_FONT_DING_SUB,
                            color=Config.ERROR_COLOR,
                        )
                        # Single pair vs. multiple pairs formatting.
                        if len(intersecting_entities) == 1:
                            intersecting_entities = intersecting_entities[0]
                            pdf.create_textbox(
                                "          Intersecting entities: "
                                + str(", ".join(intersecting_entities)),
                                relative_position=[0, 2 * subtitle_separation],
                                font=Config.PDF_FONT_SUBTITLE,
                                color=Config.ERROR_COLOR,
                            )
                        else:
                            intersecting_entities = [
                                str(tuple(element)).replace("'", "")
                                for element in intersecting_entities
                            ]
                            pdf.create_textbox(
                                "          Intersecting entities: "
                                + str(", ".join(intersecting_entities)),
                                relative_position=[0, 2 * subtitle_separation],
                                font=Config.PDF_FONT_SUBTITLE,
                                color=Config.ERROR_COLOR,
                            )
                    else:
                        pdf.create_textbox(
                            text="     4",
                            relative_position=[0, subtitle_separation],
                            font=Config.PDF_FONT_DING_SUB,
                        )
                        pdf.create_textbox(
                            "          No intersecting entities",
                            relative_position=[0, 2 * subtitle_separation],
                            font=Config.PDF_FONT_SUBTITLE,
                        )

                    # Missing add/init entries.
                    if len(missing_in) > 0:
                        pdf.create_textbox(
                            text="     8",
                            relative_position=[0, subtitle_separation],
                            font=Config.PDF_FONT_DING_SUB,
                            color=Config.ERROR_COLOR,
                        )
                        pdf.create_textbox(
                            "          Missing add/init: " + str(", ".join(missing_in)),
                            relative_position=[0, 2 * subtitle_separation],
                            font=Config.PDF_FONT_SUBTITLE,
                            color=Config.ERROR_COLOR,
                        )
                    else:
                        pdf.create_textbox(
                            text="     4",
                            relative_position=[0, subtitle_separation],
                            font=Config.PDF_FONT_DING_SUB,
                        )
                        pdf.create_textbox(
                            "          No missing adds/inits",
                            relative_position=[0, 2 * subtitle_separation],
                            font=Config.PDF_FONT_SUBTITLE,
                        )

                    if len(position_resolution_warnings) > 0:
                        for warning in position_resolution_warnings:
                            pdf.create_textbox(
                                text="     8",
                                relative_position=[0, subtitle_separation],
                                font=Config.PDF_FONT_DING_SUB,
                                color=Config.WARNING_COLOR,
                            )
                            pdf.create_textbox(
                                "          " + warning,
                                relative_position=[0, 2 * subtitle_separation],
                                font=Config.PDF_FONT_SUBTITLE,
                                color=Config.WARNING_COLOR,
                            )

                # Dynamic issues section: show green checks when none exist.
                if (
                    np.sum([len(dynamic_error) for dynamic_error in dynamic_errors])
                    == 0
                ):
                    dynamic_no_issues_title = (
                        "     No dynamic issues*"
                        if dynamic_has_footnote
                        else "     No dynamic issues"
                    )
                    pdf.create_textbox(
                        text="4",
                        relative_position=[0, title_separation + 4],
                        font=Config.PDF_FONT_DING_TITLE,
                    )
                    pdf.create_textbox(
                        dynamic_no_issues_title,
                        relative_position=[0, 2 * title_separation],
                        font=Config.PDF_FONT_TITLE_SMALL,
                    )
                    pdf.create_textbox(
                        text="     4",
                        relative_position=[0, subtitle_separation],
                        font=Config.PDF_FONT_DING_SUB,
                    )
                    pdf.create_textbox(
                        "          No acceleration errors",
                        relative_position=[0, 2 * subtitle_separation],
                        font=Config.PDF_FONT_SUBTITLE,
                    )
                    pdf.create_textbox(
                        text="     4",
                        relative_position=[0, subtitle_separation],
                        font=Config.PDF_FONT_DING_SUB,
                    )
                    pdf.create_textbox(
                        "          No swim angle errors",
                        relative_position=[0, 2 * subtitle_separation],
                        font=Config.PDF_FONT_SUBTITLE,
                    )
                    pdf.create_textbox(
                        text="     4",
                        relative_position=[0, subtitle_separation],
                        font=Config.PDF_FONT_DING_SUB,
                    )
                    pdf.create_textbox(
                        "          No acceleration warnings",
                        relative_position=[0, 2 * subtitle_separation],
                        font=Config.PDF_FONT_SUBTITLE,
                    )
                    pdf.create_textbox(
                        text="     4",
                        relative_position=[0, subtitle_separation],
                        font=Config.PDF_FONT_DING_SUB,
                    )
                    pdf.create_textbox(
                        "          No swim angle warnings",
                        relative_position=[0, 2 * subtitle_separation],
                        font=Config.PDF_FONT_SUBTITLE,
                    )
                else:
                    # Dynamic issues section: errors/warnings per category.
                    dynamic_issues_title = (
                        "     Dynamic issues*"
                        if dynamic_has_footnote
                        else "     Dynamic issues"
                    )
                    pdf.create_textbox(
                        text="8",
                        relative_position=[0, title_separation + 4],
                        font=Config.PDF_FONT_DING_TITLE,
                        color=Config.ERROR_COLOR,
                    )
                    pdf.create_textbox(
                        dynamic_issues_title,
                        relative_position=[0, 2 * title_separation],
                        font=Config.PDF_FONT_TITLE_SMALL,
                        color=Config.ERROR_COLOR,
                    )
                    # Acceleration errors.
                    if len(acceleration_errors) > 0:
                        pdf.create_textbox(
                            text="     8",
                            relative_position=[0, subtitle_separation],
                            font=Config.PDF_FONT_DING_SUB,
                            color=Config.ERROR_COLOR,
                        )
                        pdf.create_textbox(
                            "          Acceleration errors: "
                            + str(acceleration_errors),
                            relative_position=[0, 2 * subtitle_separation],
                            font=Config.PDF_FONT_SUBTITLE,
                            color=Config.ERROR_COLOR,
                        )
                    else:
                        pdf.create_textbox(
                            text="     4",
                            relative_position=[0, subtitle_separation],
                            font=Config.PDF_FONT_DING_SUB,
                        )
                        pdf.create_textbox(
                            "          No acceleration errors",
                            relative_position=[0, 2 * subtitle_separation],
                            font=Config.PDF_FONT_SUBTITLE,
                        )

                    # Swim angle errors.
                    if len(swimangle_errors) > 0:
                        pdf.create_textbox(
                            text="     8",
                            relative_position=[0, subtitle_separation],
                            font=Config.PDF_FONT_DING_SUB,
                            color=Config.ERROR_COLOR,
                        )
                        pdf.create_textbox(
                            "          Swim angle errors: " + str(swimangle_errors),
                            relative_position=[0, 2 * subtitle_separation],
                            font=Config.PDF_FONT_SUBTITLE,
                            color=Config.ERROR_COLOR,
                        )
                    else:
                        pdf.create_textbox(
                            text="     4",
                            relative_position=[0, subtitle_separation],
                            font=Config.PDF_FONT_DING_SUB,
                        )
                        pdf.create_textbox(
                            "          No swim angle errors",
                            relative_position=[0, 2 * subtitle_separation],
                            font=Config.PDF_FONT_SUBTITLE,
                        )

                    # Acceleration warnings.
                    if len(acceleration_warnings) > 0:
                        pdf.create_textbox(
                            text="     8",
                            relative_position=[0, subtitle_separation],
                            font=Config.PDF_FONT_DING_SUB,
                            color=Config.WARNING_COLOR,
                        )
                        pdf.create_textbox(
                            "          Acceleration warnings: "
                            + str(acceleration_warnings),
                            relative_position=[0, 2 * subtitle_separation],
                            font=Config.PDF_FONT_SUBTITLE,
                            color=Config.WARNING_COLOR,
                        )
                    else:
                        pdf.create_textbox(
                            text="     4",
                            relative_position=[0, subtitle_separation],
                            font=Config.PDF_FONT_DING_SUB,
                        )
                        pdf.create_textbox(
                            "          No acceleration warnings",
                            relative_position=[0, 2 * subtitle_separation],
                            font=Config.PDF_FONT_SUBTITLE,
                        )

                    # Swim angle warnings.
                    if len(swimangle_warnings) > 0:
                        pdf.create_textbox(
                            text="     8",
                            relative_position=[0, subtitle_separation],
                            font=Config.PDF_FONT_DING_SUB,
                            color=Config.WARNING_COLOR,
                        )
                        pdf.create_textbox(
                            "          Swim angle warnings: " + str(swimangle_warnings),
                            relative_position=[0, 2 * subtitle_separation],
                            font=Config.PDF_FONT_SUBTITLE,
                            color=Config.WARNING_COLOR,
                        )
                    else:
                        pdf.create_textbox(
                            text="     4",
                            relative_position=[0, subtitle_separation],
                            font=Config.PDF_FONT_DING_SUB,
                        )
                        pdf.create_textbox(
                            "          No swim angle warnings",
                            relative_position=[0, 2 * subtitle_separation],
                            font=Config.PDF_FONT_SUBTITLE,
                        )

                # Optional diagnostics plots (can fail if no usable data is present).
                try:
                    pdf.create_image(
                        temp_dir_path / "speed_plot.png",
                        relative_position=[85, -12],
                        size=(int(588 / 6), int(432 / 6)),
                    )
                    pdf.create_image(
                        temp_dir_path / "acceleration_plot.png",
                        relative_position=[-10, 60],
                        size=(int(588 / 6), int(432 / 6)),
                    )
                    pdf.create_image(
                        temp_dir_path / "swimangle_plot.png",
                        relative_position=[85, 60],
                        size=(int(588 / 6), int(432 / 6)),
                    )
                    if (
                        len(acceleration_warnings)
                        + len(acceleration_errors)
                        + len(swimangle_warnings)
                        + len(swimangle_errors)
                        > 0
                    ):
                        pdf.create_textbox(
                            "Note: Paths for all road users are plotted, but speed, acceleration, and swim angle are shown only for entities facing dynamic issues.",
                            relative_position=[0, 135],
                            font=Config.PDF_FONT_SUBTITLE_REGULAR,
                        )
                    else:
                        pdf.create_textbox(
                            "Note: Paths for all road users are plotted, but speed, acceleration, and swim angle are shown only for ego and up to other 4 entities.",
                            relative_position=[0, 135],
                            font=Config.PDF_FONT_SUBTITLE_REGULAR,
                        )
                except Exception:
                    pdf.create_textbox(
                        "Note: Graphs could not be generated because envelope does not contain any stories.",
                        relative_position=[0, 135],
                        font=Config.PDF_FONT_SUBTITLE_REGULAR,
                    )

                if simulation_based_dynamics:
                    pdf.create_textbox(
                        "* Dynamic evaluation is influenced by simulator interpretion.",
                        relative_position=[0, 2],
                        font=Config.PDF_FONT_SUBTITLE_REGULAR,
                    )
                elif simulation_not_valid:
                    pdf.create_textbox(
                        "* Assessment only based on TrajectoryActions.",
                        relative_position=[0, 2],
                        font=Config.PDF_FONT_SUBTITLE_REGULAR,
                    )

                temp_dir.cleanup()

                report_file = Path(scenario_path.stem + ".pdf")
                out = out_path / report_file
                pdf.output(out)
            else:
                # Scenario failed to load even though XML/XSD checks passed.
                pdf.create_textbox(
                    "Scenario could not be loaded",
                    relative_position=[0, title_separation],
                    font=Config.PDF_FONT_TITLE,
                )
                out = out_path / Path(scenario_path.stem + ".pdf")
                pdf.output(out)
        else:
            # XML is parseable but does not validate against the XSD.
            pdf.create_textbox(
                "File is not in XSD format",
                relative_position=[0, title_separation],
                font=Config.PDF_FONT_TITLE,
            )

            # If available, include concrete XSD validation messages in the PDF.
            xsd_errors = getattr(checker, "xsd_errors", []) or []
            if len(xsd_errors) > 0:
                # Start the XSD error block a bit further below the heading.
                pdf.create_textbox(
                    "XSD validation errors:",
                    relative_position=[0, 0],
                    font=Config.PDF_FONT_TITLE_SMALL,
                    color=Config.ERROR_COLOR,
                )

                # Show each error fully, but wrapped into multiple lines so that
                # it fits into the page width.
                max_len = 120
                for err in xsd_errors:
                    full_text = " - " + str(err)
                    text = full_text
                    while len(text) > max_len:
                        line = text[:max_len]
                        pdf.create_textbox(
                            line,
                            relative_position=[0, subtitle_separation],
                            font=Config.PDF_FONT_SUBTITLE,
                            color=Config.ERROR_COLOR,
                        )
                        # Indent continuation lines slightly.
                        text = "   " + text[max_len:]
                    # Remainder (or whole text if shorter than max_len).
                    pdf.create_textbox(
                        text,
                        relative_position=[0, subtitle_separation],
                        font=Config.PDF_FONT_SUBTITLE,
                        color=Config.ERROR_COLOR,
                    )

            out = out_path / Path(scenario_path.stem + ".pdf")
            pdf.output(out)
    else:
        # File is not parseable as XML.
        pdf.create_textbox(
            "File is not in XML format",
            relative_position=[0, title_separation],
            font=Config.PDF_FONT_TITLE,
        )
        out = out_path / Path(scenario_path.stem + ".pdf")
        pdf.output(out)


def add_error_warning_lines(ax, variable, thresholds=None):
    """
    Add horizontal lines for error and warning thresholds with
    collision-aware label placement.
    Args:
        ax: Axes to draw on.
        variable: 'acceleration' or 'swimangle'.
        thresholds: Optional Thresholds instance, defaults to the Config values.
    """
    thresholds = thresholds or Thresholds.default()
    if variable == "acceleration":
        error_threshold = thresholds.acceleration_error
        warning_threshold = thresholds.acceleration_warning
    elif variable == "swimangle":
        error_threshold = thresholds.sideslip_error
        warning_threshold = thresholds.sideslip_warning
    else:
        raise ValueError(f"Unsupported variable for thresholds: {variable!r}")

    err_col = tuple(np.array(Config.ERROR_COLOR) / 255)
    warn_col = tuple(np.array(Config.WARNING_COLOR) / 255)

    # Calculate current axis height to determine if text will overlap
    ymin, ymax = ax.get_ylim()
    y_range = ymax - ymin

    # If the threshold is less than 5% of the total view height,
    # the labels will likely overlap.
    padding = y_range * 0.03  # 3% of the view height for spacing

    threshold_lines = [
        (error_threshold, "Error", err_col, padding),
        (warning_threshold, "Warning", warn_col, 0),  # Base line
        (-warning_threshold, "Warning", warn_col, 0),  # Base line
        (-error_threshold, "Error", err_col, -padding),
    ]

    trans = ax.get_yaxis_transform()

    for val, label, col, offset_val in threshold_lines:
        # Draw the line at the exact threshold
        ax.axhline(val, linestyle=(0, (5, 10)), color=col)

        # Place text with an offset to prevent overlap
        # Using 'va' to push Error labels further away from Warning labels
        v_align = "bottom" if val >= 0 else "top"

        ax.text(
            0.05,
            val + offset_val,
            label,
            transform=trans,
            fontsize=9,
            color=col,
            va=v_align,
            ha="left",
            bbox=dict(facecolor="white", alpha=0.5, edgecolor="none", pad=1),
        )  # Added a small white buffer

    ax.legend()


def plot_dynamics(checker, analyzed_dynamics, n_plot_entities=5, output_dir=None):
    """
    Generate and save speed/acceleration/swim angle plots for a scenario.
    Args:
        checker: FileQualityChecker instance with scenario data.
        analyzed_dynamics: Dict with error/warning lists per variable.
        n_plot_entities: Max number of entities to show per plot.
        output_dir: Directory to write PNG plots to.
    """
    ylabel_speed = "Speed [m/s]"
    ylabel_acceleration = "Acceleration [m/s2]"
    ylabel_swimangle = "Swim angle [rad]"
    xlabel = "Time [s]"
    # Output directory for generated PNG files (defaults to current directory)
    output_dir = Path(output_dir) if output_dir else Path(".")
    thresholds = getattr(checker, "thresholds", None) or Thresholds.default()

    # Position and time data for all entities
    dynamic_data = checker._get_dynamic_data()
    if len(dynamic_data) == 0:
        return
    plot_vehicle_paths(dynamic_data, checker, save=True, output_dir=output_dir)

    speed_plot = plt.figure()
    speed_ax = speed_plot.add_subplot(111)
    acceleration_plot = plt.figure()
    acceleration_ax = acceleration_plot.add_subplot(111)
    swimangle_plot = plt.figure()
    swimangle_ax = swimangle_plot.add_subplot(111)

    max_value_speed, max_value_acceleration, max_value_swimangle = 0, 0, 0

    # Build time series for each entity and plot the most relevant ones.
    for entity_name in dynamic_data.keys():
        positions, times = dynamic_data[entity_name]
        df = checker._build_dynamic_data_df(positions, times)
        df = checker._calculate_acceleration_swimangle(df)

        if "ego" in entity_name:
            max_value_speed = plot_variable(
                speed_ax,
                df,
                "speed",
                entity_name,
                xlabel,
                ylabel_speed,
                max_value_speed,
                save=False,
            )
            max_value_acceleration = plot_variable(
                acceleration_ax,
                df,
                "acceleration",
                entity_name,
                xlabel,
                ylabel_acceleration,
                max_value_acceleration,
                save=False,
            )
            max_value_swimangle = plot_variable(
                swimangle_ax,
                df,
                "swimangle",
                entity_name,
                xlabel,
                ylabel_swimangle,
                max_value_swimangle,
                save=False,
            )
        else:
            # Only plot non-ego entities when thresholds are exceeded
            if np.any(np.abs(df.acceleration) > thresholds.acceleration_warning):
                max_value_speed = plot_variable(
                    speed_ax,
                    df,
                    "speed",
                    entity_name,
                    xlabel,
                    ylabel_speed,
                    max_value_speed,
                    save=False,
                )
                max_value_acceleration = plot_variable(
                    acceleration_ax,
                    df,
                    "acceleration",
                    entity_name,
                    xlabel,
                    ylabel_acceleration,
                    max_value_acceleration,
                    save=False,
                )

            if np.any(np.abs(df.swimangle) > thresholds.sideslip_warning):
                max_value_swimangle = plot_variable(
                    swimangle_ax,
                    df,
                    "swimangle",
                    entity_name,
                    xlabel,
                    ylabel_swimangle,
                    max_value_swimangle,
                    save=False,
                )

    speed_ax.set_title("Speed over time")
    select_and_plot_extra_entities(
        dynamic_data,
        "speed",
        speed_ax,
        analyzed_dynamics["acceleration_errors"],
        analyzed_dynamics["acceleration_warnings"],
        n_plot_entities,
        checker,
        xlabel=xlabel,
        ylabel=ylabel_speed,
        max_value=max_value_speed,
        save=False,
    )
    speed_plot.savefig(output_dir / "speed_plot.png")

    # Acceleration
    select_and_plot_extra_entities(
        dynamic_data,
        "acceleration",
        acceleration_ax,
        analyzed_dynamics["acceleration_errors"],
        analyzed_dynamics["acceleration_warnings"],
        n_plot_entities,
        checker,
        xlabel=xlabel,
        ylabel=ylabel_acceleration,
        max_value=max_value_acceleration,
        save=False,
    )
    acceleration_ax.set_title("Acceleration over time")
    add_error_warning_lines(acceleration_ax, "acceleration", thresholds)
    acceleration_plot.savefig(output_dir / "acceleration_plot.png")

    # Swim angle
    select_and_plot_extra_entities(
        dynamic_data,
        "swimangle",
        swimangle_ax,
        analyzed_dynamics["swimangle_errors"],
        analyzed_dynamics["swimangle_warnings"],
        n_plot_entities,
        checker,
        xlabel=xlabel,
        ylabel=ylabel_swimangle,
        max_value=max_value_swimangle,
        save=False,
    )
    swimangle_ax.set_title("Swim angle over time")
    add_error_warning_lines(swimangle_ax, "swimangle", thresholds)
    swimangle_plot.savefig(output_dir / "swimangle_plot.png")

    # Close the figures explicitly; a long-running server would otherwise
    # accumulate them in pyplot's global registry.
    for figure in (speed_plot, acceleration_plot, swimangle_plot):
        plt.close(figure)


def create_report_multiple(title, file_information, out_path, print_log=False):
    """
    Create an aggregated PDF report for multiple scenario files.

    Each row summarizes XML/XSD status and counts of file and
    dynamic issues for one scenario file.
    Args:
        title: Title for the aggregated report.
        file_information: List of summary rows for scenarios.
        out_path: Output directory for the PDF.
        print_log: Whether to log the output path.
    """
    title_separation = -5
    subtitle_separation = -4

    pdf = PDF(title)
    pdf.add_page()

    Path(out_path).mkdir(parents=True, exist_ok=True)

    pdf.create_textbox(
        "Tests", relative_position=[0, title_separation], font=Config.PDF_FONT_TITLE
    )
    # Header row uses manual spacing to align columns in a monospaced layout.
    pdf.create_textbox(
        " " * 10
        + "Scenario files"
        + " " * 55
        + "XML loadable"
        + " " * 12
        + "XSD valid"
        + " " * 10
        + "Simulation"
        + " " * 10
        + "File issues"
        + " " * 8
        + "Dynamic issues",
        relative_position=[0, title_separation],
        font=Config.PDF_FONT_SUBTITLE,
    )

    # file = (path, xml_loadable, xsd_valid, simulation_status, n_file_issues, n_dynamic_issues)
    for file in file_information:
        if (
            file[1]
            and file[2]
            and file[4] == 0
            and file[5] == 0
            and file[3] != "failed"
        ):
            pdf.create_textbox(
                text="     4",
                relative_position=[0, subtitle_separation],
                font=Config.PDF_FONT_DING_SUB,
            )
            pdf.create_textbox(
                "          " + Path(file[0]).name,
                relative_position=[0, 2 * subtitle_separation],
                font=Config.PDF_FONT_SUBTITLE_REGULAR,
            )
            pdf.create_textbox(
                (" " * 100) + "4" * int(file[1]),
                relative_position=[0, 2 * subtitle_separation],
                font=Config.PDF_FONT_DING_SUB,
            )
            pdf.create_textbox(
                (" " * 130) + "4" * int(file[2]),
                relative_position=[0, 2 * subtitle_separation],
                font=Config.PDF_FONT_DING_SUB,
            )
            pdf.create_textbox(
                (" " * 148) + str(file[3]),
                relative_position=[0, 2 * subtitle_separation],
                font=Config.PDF_FONT_SUBTITLE_REGULAR,
            )
            pdf.create_textbox(
                (" " * 178) + "0",
                relative_position=[0, 2 * subtitle_separation],
                font=Config.PDF_FONT_SUBTITLE_REGULAR,
            )
            pdf.create_textbox(
                (" " * 205) + "0",
                relative_position=[0, 2 * subtitle_separation],
                font=Config.PDF_FONT_SUBTITLE_REGULAR,
            )
        else:
            # At least one check failed or issues are present.
            pdf.create_textbox(
                text="     8",
                relative_position=[0, subtitle_separation],
                font=Config.PDF_FONT_DING_SUB,
                color=Config.ERROR_COLOR,
            )
            pdf.create_textbox(
                " " * 10 + Path(file[0]).name,
                relative_position=[0, 2 * subtitle_separation],
                font=Config.PDF_FONT_SUBTITLE_REGULAR,
            )
            pdf.create_textbox(
                (" " * 100) + ("4" * int(file[1])) + ("8" * (1 - int(file[1]))),
                relative_position=[0, 2 * subtitle_separation],
                font=Config.PDF_FONT_DING_SUB,
            )
            pdf.create_textbox(
                (" " * 130) + ("4" * int(file[2])) + ("8" * (1 - int(file[2]))),
                relative_position=[0, 2 * subtitle_separation],
                font=Config.PDF_FONT_DING_SUB,
            )
            sim_color = Config.ERROR_COLOR if file[3] == "failed" else None
            pdf.create_textbox(
                (" " * 148) + str(file[3]),
                relative_position=[0, 2 * subtitle_separation],
                font=Config.PDF_FONT_SUBTITLE_REGULAR,
                color=sim_color,
            )
            pdf.create_textbox(
                (" " * 178) + str(file[4]),
                relative_position=[0, 2 * subtitle_separation],
                font=Config.PDF_FONT_SUBTITLE_REGULAR,
            )
            pdf.create_textbox(
                (" " * 205) + str(file[5]),
                relative_position=[0, 2 * subtitle_separation],
                font=Config.PDF_FONT_SUBTITLE_REGULAR,
            )
        pdf.create_line(color=(0, 0, 0), relative_position=[0, -2])

    out = out_path / Path("aggregate_report.pdf")
    pdf.output(out)
    if print_log:
        logger.info(f"Report created: {out}")


def plot_variable(
    ax, df, variable, entity_name, xlabel, ylabel, max_value=0, save=False
):
    """
    Plot a single variable over time for one entity.
    Args:
        ax: Matplotlib Axes to draw on.
        df: DataFrame containing time series data.
        variable: Column name to plot.
        entity_name: Entity identifier used in the legend.
        xlabel: Label for the x-axis.
        ylabel: Label for the y-axis.
        max_value: Current maximum value for y-axis scaling.
        save: Whether to save an individual plot image.
    """
    """
    dedicated plotting style for dynamic variables
    """
    # Use distinct colors and z-order so ego stands out visually.
    if "ego" in entity_name:
        ax.plot(
            df.time,
            df.loc[:, variable],
            label=entity_name,
            color=Config.EGO_COLORMAP(255),
            zorder=999,
        )
    else:
        ax.plot(
            df.time,
            df.loc[:, variable],
            label=entity_name,
            color=Config.OTHER_COLORMAP(255),
            zorder=-1,
        )

    max_value_local = df.loc[:, variable].abs().max()
    max_value = max(max_value, max_value_local)
    ax.set_ylim(-max_value * 1.2, max_value * 1.2)

    # plt.title(str(variable) + ' over time for entity ' + entity_name)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    if save:
        plt.savefig(str(variable) + "_" + entity_name + ".png")
    # No close here: this function draws onto a caller-owned Axes, so closing
    # the current pyplot figure would detach the figure still being built.

    return max_value


def plot_fading_line(
    ax,
    df,
    label,
    zorder,
    segment_size=10,
    arrow_size=2,
    colormap=mpl.colormaps["Blues"],
):
    """
    Plot a line that fades from light to dark along its path.
    Args:
        ax: Matplotlib Axes to draw on.
        df: DataFrame containing trajectory points.
        label: Legend label for the line.
        zorder: Z-order for drawing.
        segment_size: Number of points per color segment.
        arrow_size: Number of segments for arrow placement.
        colormap: Matplotlib colormap to sample from.
    """
    # Split trajectory into segments that get progressively darker
    n_segments = int(df.shape[0] / segment_size)

    for segment in range(n_segments - arrow_size + 1):
        ax.plot(
            df[segment * segment_size : (segment + 1) * segment_size + 1].x,
            df[segment * segment_size : (segment + 1) * segment_size + 1].y,
            label=label,
            c=colormap(int(255 / n_segments) * segment),
            zorder=zorder,
        )
    # No close here: the Axes belongs to the caller's figure.


def plot_vehicle_paths(
    dynamic_data, checker, segment_size=10, arrow_size=1, save=True, output_dir=None
):
    """
    Plot 2D trajectories of all vehicles in the XY plane.
    Args:
        dynamic_data: Dict of entity -> (positions, times).
        checker: FileQualityChecker instance for data helpers.
        segment_size: Number of points per faded segment.
        arrow_size: Number of segments used for arrow placement.
        save: Whether to save the plot to disk.
        output_dir: Directory to save the plot.
    """
    output_dir = Path(output_dir) if output_dir else Path(".")
    paths_plot = plt.figure()
    paths_ax = paths_plot.add_subplot(111)

    # draw background map if xodr is available
    try:
        xodr_path = checker.get_xodr_path()
    except AttributeError:
        xodr_path = None

    if xodr_path is not None:
        try:
            tree = safe_xml.parse(xodr_path)
            root = tree.getroot()

            def _sample_geometry_points(geom, points_per_meter=10.0):
                """Sample one OpenDRIVE geometry segment into XY polyline points."""
                try:
                    x0 = float(geom.get("x", 0.0))
                    y0 = float(geom.get("y", 0.0))
                    hdg = float(geom.get("hdg", 0.0))
                    length = float(geom.get("length", 0.0))
                except (TypeError, ValueError):
                    return [], []

                if length <= 0.0:
                    return [], []

                n_samples = max(int(np.ceil(length * points_per_meter)), 2)
                s_vals = np.linspace(0.0, length, n_samples)

                # Identify geometry type by first child element.
                geom_type = None
                geom_child = None
                for child in geom:
                    if child.tag.endswith("line"):
                        geom_type = "line"
                        geom_child = child
                        break
                    if child.tag.endswith("arc"):
                        geom_type = "arc"
                        geom_child = child
                        break

                # Fallback to straight segment when geometry type is unknown.
                if geom_type == "arc" and geom_child is not None:
                    try:
                        curvature = float(geom_child.get("curvature", 0.0))
                    except (TypeError, ValueError):
                        curvature = 0.0

                    if abs(curvature) < 1e-10:
                        xs = x0 + s_vals * np.cos(hdg)
                        ys = y0 + s_vals * np.sin(hdg)
                    else:
                        # Circular arc integration in inertial XY coordinates.
                        xs = (
                            x0
                            + (np.sin(hdg + curvature * s_vals) - np.sin(hdg))
                            / curvature
                        )
                        ys = (
                            y0
                            - (np.cos(hdg + curvature * s_vals) - np.cos(hdg))
                            / curvature
                        )
                else:
                    xs = x0 + s_vals * np.cos(hdg)
                    ys = y0 + s_vals * np.sin(hdg)

                return xs.tolist(), ys.tolist()

            # Handle possible XML namespaces by checking tag endings.
            for road in root.iter():
                if not road.tag.endswith("road"):
                    continue

                plan_view = None
                for child in road:
                    if child.tag.endswith("planView"):
                        plan_view = child
                        break
                if plan_view is None:
                    continue

                geometries = []
                for geom in plan_view:
                    if not geom.tag.endswith("geometry"):
                        continue
                    try:
                        s = float(geom.get("s", 0.0))
                    except (TypeError, ValueError):
                        continue
                    geometries.append((s, geom))

                if len(geometries) == 0:
                    continue

                geometries.sort(key=lambda p: p[0])
                road_xs = []
                road_ys = []

                # Build one continuous polyline per road from all geometry segments.
                for _, geom in geometries:
                    seg_xs, seg_ys = _sample_geometry_points(geom)
                    if len(seg_xs) == 0:
                        continue

                    # Avoid duplicating points at segment boundaries.
                    if (
                        len(road_xs) > 0
                        and np.isclose(road_xs[-1], seg_xs[0])
                        and np.isclose(road_ys[-1], seg_ys[0])
                    ):
                        seg_xs = seg_xs[1:]
                        seg_ys = seg_ys[1:]

                    road_xs.extend(seg_xs)
                    road_ys.extend(seg_ys)

                if len(road_xs) >= 2:
                    paths_ax.plot(
                        road_xs, road_ys, color="lightgrey", linewidth=0.9, zorder=-20
                    )
        except Exception:
            pass

    # plot vehicle data
    for entity_name in dynamic_data.keys():
        positions, times = dynamic_data[entity_name]
        df = checker._build_dynamic_data_df(positions, times)
        df = checker._calculate_acceleration_swimangle(df)

        # Skip very short trajectories that cannot render the arrow segment.
        if df.shape[0] < arrow_size * segment_size:
            continue

        if "ego" in entity_name:
            plot_fading_line(
                paths_ax,
                df,
                label="ego vehicle",
                segment_size=segment_size,
                arrow_size=arrow_size,
                colormap=Config.EGO_COLORMAP,
                zorder=999,
            )
            paths_ax.arrow(
                df.iloc[-arrow_size * segment_size].x,
                df.iloc[-arrow_size * segment_size].y,
                df.iloc[-1].x - df.iloc[-arrow_size * segment_size].x,
                df.iloc[-1].y - df.iloc[-arrow_size * segment_size].y,
                head_width=0.8,
                head_length=2,
                length_includes_head=True,
                color=Config.EGO_COLORMAP(255),
                zorder=999,
            )
        else:
            plot_fading_line(
                paths_ax,
                df,
                label="other",
                segment_size=segment_size,
                arrow_size=arrow_size,
                colormap=Config.OTHER_COLORMAP,
                zorder=-1,
            )
            paths_ax.arrow(
                df.iloc[-arrow_size * segment_size].x,
                df.iloc[-arrow_size * segment_size].y,
                df.iloc[-1].x - df.iloc[-arrow_size * segment_size].x,
                df.iloc[-1].y - df.iloc[-arrow_size * segment_size].y,
                head_width=0.8,
                head_length=2,
                length_includes_head=True,
                color=Config.OTHER_COLORMAP(255),
                zorder=-1,
            )

    # Manual legend entries to match the two color categories.
    legend_elements = [
        Line2D([0], [0], color=Config.EGO_COLORMAP(255), label="ego vehicle"),
        Line2D([0], [0], color=Config.OTHER_COLORMAP(255), label="other vehicles"),
    ]
    paths_ax.legend(handles=legend_elements)
    paths_ax.set_xlabel("X [m]")
    paths_ax.set_ylabel("Y [m]")
    paths_ax.set_aspect("equal", adjustable="box")
    paths_ax.set_title("Vehicle paths")

    if save:
        paths_plot.savefig(output_dir / "vehicle_paths.png")
    plt.close(paths_plot)


def select_and_plot_extra_entities(
    dynamic_data,
    variable,
    ax,
    entities_errors,
    entities_warnings,
    n_plot_entities,
    checker,
    xlabel,
    ylabel,
    max_value=0,
    save=False,
):
    """
    Select additional entities to plot when too few have issues.

    Ensures the plot contains up to n_plot_entities curves while
    preferencing ego entities and those with errors or warnings.
    Args:
        dynamic_data: Dict of entity -> (positions, times).
        variable: Variable name to plot.
        ax: Matplotlib Axes to draw on.
        entities_errors: Entities with error-level violations.
        entities_warnings: Entities with warning-level violations.
        n_plot_entities: Max number of entities to plot.
        checker: FileQualityChecker instance for data helpers.
        xlabel: Label for the x-axis.
        ylabel: Label for the y-axis.
        save: Whether to save an individual plot image.
    """
    # Initial set: ego entities plus those with errors or warnings.
    plot_entities = (
        [
            entity_name
            for entity_name in list(dynamic_data.keys())
            if "ego_" in entity_name
        ]
        + entities_errors
        + entities_warnings
    )
    plot_entities = list(set(plot_entities))
    extra_plot_entities = []
    # Fill up with additional entities if we have fewer than requested.
    if len(plot_entities) < n_plot_entities:
        extra_plot_entities = list(
            set(list(dynamic_data.keys())).difference(set(plot_entities))
        )
        extra_plot_entities = extra_plot_entities[
            : n_plot_entities - len(plot_entities)
        ]

    for entity_name in extra_plot_entities:
        positions, times = dynamic_data[entity_name]
        df = checker._build_dynamic_data_df(positions, times)
        df = checker._calculate_acceleration_swimangle(df)
        max_value = plot_variable(
            ax,
            df,
            variable,
            entity_name,
            xlabel,
            ylabel,
            max_value=max_value,
            save=save,
        )

    ax.legend()
