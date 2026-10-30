"""The sun's elevation above the horizon, for the quality gate's night check.

NOAA's solar position equations (https://gml.noaa.gov/grad/solcalc/calcdetails.html),
good to about 0.1 degree for dates near the present. Atmospheric refraction is
left out: it lifts the sun by about half a degree at the horizon, which does
not matter at the -6 degree civil-twilight limit the gate uses.
"""

from __future__ import annotations

import math
from datetime import datetime


def solar_elevation(when: datetime, lat: float, lon: float) -> float:
    """Degrees of the sun's centre above the horizon at `when`, seen from lat/lon (east positive)."""
    if when.tzinfo is None:
        raise ValueError("solar_elevation needs a timezone-aware time")
    t = (when.timestamp() / 86400.0 + 2440587.5 - 2451545.0) / 36525.0  # Julian centuries since J2000.0

    mean_longitude = (280.46646 + t * (36000.76983 + 0.0003032 * t)) % 360
    mean_anomaly = math.radians(357.52911 + t * (35999.05029 - 0.0001537 * t))
    eccentricity = 0.016708634 - t * (0.000042037 + 0.0000001267 * t)
    centre = (math.sin(mean_anomaly) * (1.914602 - t * (0.004817 + 0.000014 * t))
              + math.sin(2 * mean_anomaly) * (0.019993 - 0.000101 * t)
              + math.sin(3 * mean_anomaly) * 0.000289)
    omega = math.radians(125.04 - 1934.136 * t)
    apparent_longitude = math.radians(mean_longitude + centre - 0.00569 - 0.00478 * math.sin(omega))
    obliquity = math.radians(23 + (26 + (21.448 - t * (46.815 + t * (0.00059 - t * 0.001813))) / 60) / 60
                             + 0.00256 * math.cos(omega))
    declination = math.asin(math.sin(obliquity) * math.sin(apparent_longitude))

    y = math.tan(obliquity / 2) ** 2
    l0 = math.radians(mean_longitude)
    equation_of_time = 4 * math.degrees(  # minutes
        y * math.sin(2 * l0) - 2 * eccentricity * math.sin(mean_anomaly)
        + 4 * eccentricity * y * math.sin(mean_anomaly) * math.cos(2 * l0)
        - 0.5 * y * y * math.sin(4 * l0) - 1.25 * eccentricity ** 2 * math.sin(2 * mean_anomaly))

    utc_minutes = (when.timestamp() % 86400) / 60
    hour_angle = math.radians(((utc_minutes + equation_of_time + 4 * lon) % 1440) / 4 - 180)
    latitude = math.radians(lat)
    cos_zenith = (math.sin(latitude) * math.sin(declination)
                  + math.cos(latitude) * math.cos(declination) * math.cos(hour_angle))
    return 90 - math.degrees(math.acos(max(-1.0, min(1.0, cos_zenith))))
