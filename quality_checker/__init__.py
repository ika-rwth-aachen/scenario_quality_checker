"""
Scenario Quality Checker package.

matplotlib is imported at module scope by ``config.py`` (it reads
``mpl.colormaps`` in a class body), so the backend has to be selected here,
before any submodule is imported. ``Agg`` keeps the tool usable headless, which
both the CLI on a build server and the web app depend on.
"""

import os

os.environ.setdefault("MPLBACKEND", "Agg")

from .thresholds import Thresholds  # noqa: E402  - must follow the backend setup.

__all__ = ["Thresholds"]
