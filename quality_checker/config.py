
import matplotlib as mpl


class Config:
    # colors and colormaps
    EGO_COLORMAP = mpl.colormaps['Blues']
    OTHER_COLORMAP = mpl.colormaps['Greens']
    
    ERROR_COLOR = (255, 0, 0)
    WARNING_COLOR = (250, 95, 31)

    # thresholds for errors and warnings
    ACCELERATION_ERROR_THRESHOLD = 9.8*2
    ACCELERATION_WARNING_THRESHOLD = 9.8
    SWIMANGLE_ERROR_THRESHOLD = 0.2
    SWIMANGLE_WARNING_THRESHOLD = 0.1