
import matplotlib as mpl


class Config:
    """ General configurations for the quality checker. """
    
    # colors and colormaps
    EGO_COLORMAP = mpl.colormaps['Blues']
    OTHER_COLORMAP = mpl.colormaps['Greens']
    
    ERROR_COLOR = (255, 0, 0)
    WARNING_COLOR = (250, 95, 31)

    # thresholds for errors and warnings
    ACCELERATION_ERROR_THRESHOLD = 9.8*2  # m/s^2
    ACCELERATION_WARNING_THRESHOLD = 9.8  # m/s^2
    SWIMANGLE_ERROR_THRESHOLD = 0.2  # radians
    SWIMANGLE_WARNING_THRESHOLD = 0.1  # radians

    # PDF report font settings
    PDF_FONT_NAME = "Arial"
    PDF_DINGBATS_FONT_NAME = "zapfdingbats"
    PDF_TITLE_SIZE = 12
    PDF_SUBTITLE_SIZE = 8
    
    PDF_FONT_TITLE = {"name": PDF_FONT_NAME, "type": "B", "size": PDF_TITLE_SIZE}
    PDF_FONT_TITLE_SMALL = {"name": PDF_FONT_NAME, "type": "B", "size": PDF_TITLE_SIZE - 2}
    PDF_FONT_SUBTITLE = {"name": PDF_FONT_NAME, "type": "B", "size": PDF_SUBTITLE_SIZE}
    PDF_FONT_SUBTITLE_REGULAR = {"name": PDF_FONT_NAME, "type": "", "size": PDF_SUBTITLE_SIZE}
    PDF_FONT_DING_TITLE = {"name": PDF_DINGBATS_FONT_NAME, "type": "", "size": PDF_TITLE_SIZE - 2}
    PDF_FONT_DING_SUB = {"name": PDF_DINGBATS_FONT_NAME, "type": "", "size": PDF_SUBTITLE_SIZE}
