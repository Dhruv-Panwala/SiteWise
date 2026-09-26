from __future__ import annotations

import numpy as np


def haversine_m(lat, lon, target_lat: float, target_lon: float) -> np.ndarray:
    """Vectorised great-circle distance in metres."""
    lat = np.asarray(lat, dtype=float)
    lon = np.asarray(lon, dtype=float)
    rlat = np.radians(lat)
    rlon = np.radians(lon)
    tlat = np.radians(float(target_lat))
    tlon = np.radians(float(target_lon))
    dlat = rlat - tlat
    dlon = rlon - tlon
    a = np.sin(dlat / 2) ** 2 + np.cos(rlat) * np.cos(tlat) * np.sin(dlon / 2) ** 2
    return 6_371_000.0 * 2 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def scalar_haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    return float(haversine_m([lat1], [lon1], lat2, lon2)[0])

