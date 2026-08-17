import matplotlib as mpl


class Config:
    """General configurations for the quality checker."""

    # colors and colormaps
    EGO_COLORMAP = mpl.colormaps["Blues"]
    OTHER_COLORMAP = mpl.colormaps["Greens"]

    ERROR_COLOR = (255, 0, 0)
    WARNING_COLOR = (250, 95, 31)

    # thresholds for errors and warnings
    ACCELERATION_ERROR_THRESHOLD = (
        9.8 * 3
    )  # m/s^2  -  reference: Commission Implementing Regulation (EU) 2022/1426 of 5 August 2022 Annex III, 1.3.2
    ACCELERATION_WARNING_THRESHOLD = 9.8  # m/s^2  -  often used as physical limit
    SWIMANGLE_ERROR_THRESHOLD = 0.2  # radians  -  reference: https://ietresearch.onlinelibrary.wiley.com/doi/10.1049/iet-its.2020.0385
    SWIMANGLE_WARNING_THRESHOLD = (
        0.1  # radians  -  reference: https://www.mdpi.com/2032-6653/12/1/42
    )

    # PDF report font settings
    PDF_FONT_NAME = "Arial"
    PDF_DINGBATS_FONT_NAME = "zapfdingbats"
    PDF_TITLE_SIZE = 12
    PDF_SUBTITLE_SIZE = 8

    PDF_FONT_TITLE = {"name": PDF_FONT_NAME, "type": "B", "size": PDF_TITLE_SIZE}
    PDF_FONT_TITLE_SMALL = {
        "name": PDF_FONT_NAME,
        "type": "B",
        "size": PDF_TITLE_SIZE - 2,
    }
    PDF_FONT_SUBTITLE = {"name": PDF_FONT_NAME, "type": "B", "size": PDF_SUBTITLE_SIZE}
    PDF_FONT_SUBTITLE_REGULAR = {
        "name": PDF_FONT_NAME,
        "type": "",
        "size": PDF_SUBTITLE_SIZE,
    }
    PDF_FONT_DING_TITLE = {
        "name": PDF_DINGBATS_FONT_NAME,
        "type": "",
        "size": PDF_TITLE_SIZE - 2,
    }
    PDF_FONT_DING_SUB = {
        "name": PDF_DINGBATS_FONT_NAME,
        "type": "",
        "size": PDF_SUBTITLE_SIZE,
    }
