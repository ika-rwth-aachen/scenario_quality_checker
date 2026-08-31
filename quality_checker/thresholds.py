"""
Per-run threshold values for the dynamics checks.

The defaults live in :class:`quality_checker.config.Config` and stay the single
source of truth. This module wraps them in an immutable value object so a caller
(for example the web app, which serves several requests from one process) can
override thresholds for a single run without mutating global state.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .config import Config


@dataclass(frozen=True)
class Thresholds:
    """Warning and error limits for the acceleration and sideslip checks."""

    acceleration_warning: float
    acceleration_error: float
    sideslip_warning: float
    sideslip_error: float

    #: Mapping of field name -> (label, unit) used for messages and forms.
    FIELDS = (
        "acceleration_warning",
        "acceleration_error",
        "sideslip_warning",
        "sideslip_error",
    )

    @classmethod
    def default(cls):
        """
        Return the thresholds configured in Config.

        The values are rounded because Config expresses them as products such as
        ``9.8 * 3``, whose binary representation would otherwise show up as
        29.400000000000002 in reports and input fields.
        """
        return cls(
            acceleration_warning=round(float(Config.ACCELERATION_WARNING_THRESHOLD), 6),
            acceleration_error=round(float(Config.ACCELERATION_ERROR_THRESHOLD), 6),
            sideslip_warning=round(float(Config.SWIMANGLE_WARNING_THRESHOLD), 6),
            sideslip_error=round(float(Config.SWIMANGLE_ERROR_THRESHOLD), 6),
        )

    @classmethod
    def from_mapping(cls, values):
        """
        Build thresholds from a partial mapping, filling gaps with the defaults.

        Args:
            values: Mapping of field name -> value. ``None`` values are ignored.
        return: Thresholds instance.
        raises ValueError: If a value is not a positive, finite number, or if a
            warning limit exceeds the matching error limit.
        """
        defaults = cls.default()
        if not values:
            return defaults

        resolved = {}
        for field in cls.FIELDS:
            raw = values.get(field) if hasattr(values, "get") else None
            if raw is None or raw == "":
                resolved[field] = getattr(defaults, field)
                continue
            try:
                number = float(raw)
            except (TypeError, ValueError):
                raise ValueError(f"{field} must be a number, got {raw!r}")
            if not math.isfinite(number) or number <= 0:
                raise ValueError(
                    f"{field} must be a positive, finite number, got {number!r}"
                )
            resolved[field] = number

        thresholds = cls(**resolved)
        thresholds.validate()
        return thresholds

    def validate(self):
        """Raise ValueError when a warning limit exceeds its error limit."""
        if self.acceleration_warning > self.acceleration_error:
            raise ValueError(
                "acceleration_warning must not exceed acceleration_error "
                f"({self.acceleration_warning} > {self.acceleration_error})"
            )
        if self.sideslip_warning > self.sideslip_error:
            raise ValueError(
                "sideslip_warning must not exceed sideslip_error "
                f"({self.sideslip_warning} > {self.sideslip_error})"
            )

    def as_dict(self):
        """Return the thresholds as a plain dict of floats."""
        return {field: getattr(self, field) for field in self.FIELDS}

    def limit(self, metric_name, severity):
        """
        Return the limit for a metric and severity.

        Args:
            metric_name: 'acceleration' or 'swimangle'/'sideslip'.
            severity: 'warning' or 'error'.
        return: Threshold value as float, or None for unknown combinations.
        """
        family = "acceleration" if metric_name == "acceleration" else "sideslip"
        return getattr(self, f"{family}_{severity}", None)
