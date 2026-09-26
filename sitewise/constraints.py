from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlencode

import requests
from shapely import wkt
from shapely.geometry import Point, shape

from .config import Settings
from .planning import UK_BOUNDS, validate_coordinates


DEFAULT_DATASETS = (
    "conservation-area",
    "tree-preservation-zone",
    "flood-risk-zone",
    "green-belt",
    "listed-building",
    "article-4-direction-area",
    "ancient-woodland",
    "site-of-special-scientific-interest",
)

LABELS = {
    "conservation-area": "Conservation area",
    "tree-preservation-zone": "Tree Preservation Order/protected-tree zone",
    "flood-risk-zone": "Flood-risk zone",
    "green-belt": "Green Belt",
    "listed-building": "Listed building",
    "article-4-direction-area": "Article 4 direction area",
    "ancient-woodland": "Ancient woodland",
    "site-of-special-scientific-interest": "Site of Special Scientific Interest",
}


def _severity(dataset: str) -> str:
    if dataset in {"tree-preservation-zone", "listed-building", "site-of-special-scientific-interest", "ancient-woodland"}:
        return "high"
    if dataset in {"conservation-area", "flood-risk-zone", "green-belt", "article-4-direction-area"}:
        return "medium"
    return "unknown"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cache_key(url: str, params: list[tuple[str, Any]]) -> str:
    raw = url + "?" + urlencode(params, doseq=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _cache_read(path: Path, ttl: int) -> tuple[dict | None, bool]:
    if not path.exists():
        return None, False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        age = time.time() - float(payload.get("cached_at_epoch", 0))
        return payload, age <= ttl
    except (OSError, ValueError, TypeError):
        return None, False


def _cache_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".partial")
    temp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temp.replace(path)


def _entity_list(payload: dict) -> list[dict]:
    entities = payload.get("entities")
    if isinstance(entities, list):
        return [e for e in entities if isinstance(e, dict)]
    features = payload.get("features")
    if isinstance(features, list):
        return [e for e in features if isinstance(e, dict)]
    return []


def _entity_name(entity: dict, dataset: str) -> str:
    props = entity.get("properties") if isinstance(entity.get("properties"), dict) else entity
    for key in ("name", "NAME", "title", "reference", "reference-number", "entity"):
        if props.get(key):
            return str(props[key])
    return LABELS.get(dataset, dataset)


@dataclass
class ConstraintApiClient:
    settings: Settings
    session: requests.Session | None = None

    def __post_init__(self) -> None:
        self.session = self.session or requests.Session()
        self.session.headers.update({"User-Agent": "sitewise-uk-hackathon/0.1"})

    def _unknown(self, dataset: str, url: str, message: str, status: str = "unknown") -> dict:
        return {
            "constraint_id": f"query:{dataset}",
            "dataset": dataset,
            "name": LABELS.get(dataset, dataset),
            "severity": "unknown",
            "status": status,
            "current": None,
            "source_url": url,
            "source_name": "Planning Data API",
            "source_date": None,
            "retrieved_at": _now(),
            "raw_reference": None,
            "coverage_warning": message,
        }

    def query(self, lat: float, lon: float, datasets: Iterable[str] = DEFAULT_DATASETS) -> list[dict]:
        quality = validate_coordinates(lat, lon)
        if quality != "valid":
            return [self._unknown(d, self.settings.planning_data_api, f"Coordinates are {quality}; constraint lookup was not attempted.") for d in datasets]

        findings: list[dict] = []
        for dataset in datasets:
            params = [("latitude", str(float(lat))), ("longitude", str(float(lon))), ("dataset", dataset), ("limit", "100")]
            url = self.settings.planning_data_api + "?" + urlencode(params)
            cache_path = self.settings.cache_dir / "planning_data_api" / f"{_cache_key(self.settings.planning_data_api, params)}.json"
            cached, fresh = _cache_read(cache_path, self.settings.cache_ttl_seconds)
            payload = cached.get("payload") if cached and fresh else None
            source_status = "cache" if payload is not None else "live"
            if payload is None:
                try:
                    response = self.session.get(self.settings.planning_data_api, params=params, timeout=self.settings.request_timeout_seconds)
                    response.raise_for_status()
                    payload = response.json()
                    _cache_write(cache_path, {"cached_at_epoch": time.time(), "request_url": response.url, "status_code": response.status_code, "payload": payload})
                except (requests.RequestException, ValueError) as exc:
                    if cached and isinstance(cached.get("payload"), dict):
                        payload = cached["payload"]
                        source_status = "stale_cache"
                    else:
                        findings.append(self._unknown(dataset, url, f"Planning Data API unavailable: {exc.__class__.__name__}."))
                        continue

            entities = _entity_list(payload if isinstance(payload, dict) else {})
            if not entities:
                findings.append(self._unknown(dataset, url, "No entity returned at this point from this source; this is not proof that the constraint is absent.", status="not_found"))
                findings[-1]["source_status"] = source_status
                continue
            for entity in entities:
                props = entity.get("properties") if isinstance(entity.get("properties"), dict) else entity
                entity_id = entity.get("id") or props.get("id") or props.get("entity") or props.get("reference")
                raw_geometry = entity.get("geometry") or props.get("geometry")
                spatial_relation = "api_point_match"
                if raw_geometry:
                    try:
                        geometry = wkt.loads(raw_geometry) if isinstance(raw_geometry, str) else shape(raw_geometry)
                        if not geometry.is_valid:
                            raise ValueError("Invalid source geometry")
                        if not geometry.intersects(Point(float(lon), float(lat))):
                            continue
                        spatial_relation = "point_intersects_geometry"
                    except Exception:
                        spatial_relation = "geometry_unparsed"
                entity_url = f"https://www.planning.data.gov.uk/entity/{entity_id}" if entity_id else url
                ended = False
                try:
                    ended = datetime.fromisoformat(str(props.get("end-date"))).date() <= datetime.now(timezone.utc).date()
                except (TypeError, ValueError):
                    pass
                verified = spatial_relation == "point_intersects_geometry"
                findings.append({
                    "constraint_id": str(entity_id or f"{dataset}:{len(findings)}"),
                    "dataset": dataset,
                    "name": _entity_name(entity, dataset),
                    "severity": _severity(dataset),
                    "status": ("historical" if ended else "confirmed") if verified else "unknown",
                    "current": False if ended else None,
                    "temporal_status": "source_marked_ended" if ended else "legal_currency_unverified",
                    "source_url": entity_url,
                    "source_name": "Planning Data API",
                    "source_date": props.get("start-date") or props.get("entry-date") or props.get("last-updated"),
                    "retrieved_at": _now(),
                    "raw_reference": props.get("reference") or props.get("reference-number") or entity_id,
                    "coverage_warning": "Point intersects source geometry; verify legal currency and the full site boundary."
                                        if verified else "The returned record lacks usable geometry; no site constraint is confirmed.",
                    "spatial_relation": spatial_relation,
                    "source_status": source_status,
                })
        return findings


class GeoJSONConstraintIndex:
    """Small local point-in-polygon index for optional cached constraint layers."""

    def __init__(self, features: list[dict]):
        self.features = features

    @classmethod
    def from_directory(cls, directory: str | Path) -> "GeoJSONConstraintIndex":
        directory = Path(directory)
        features: list[dict] = []
        if not directory.exists():
            return cls(features)
        for path in sorted(directory.glob("*.geojson")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            stem = path.stem.lower().replace("_", "-").replace(" ", "-")
            if "tree" in stem or "tpo" in stem:
                dataset = "tree-preservation-zone"
            elif "conservation" in stem:
                dataset = "conservation-area"
            elif "flood" in stem:
                dataset = "flood-risk-zone"
            else:
                dataset = stem
            for feature in payload.get("features", []):
                geometry = feature.get("geometry")
                if not geometry:
                    continue
                try:
                    geom = shape(geometry)
                    if not geom.is_valid:
                        continue
                except Exception:
                    continue
                features.append({"dataset": dataset, "geometry": geom, "properties": feature.get("properties") or {}, "source_url": str(path)})
        return cls(features)

    def query(self, lat: float, lon: float) -> list[dict]:
        if validate_coordinates(lat, lon) != "valid":
            return []
        point = Point(float(lon), float(lat))
        findings = []
        for item in self.features:
            if not item["geometry"].intersects(point):
                continue
            props = item["properties"]
            dataset = item["dataset"]
            name = next((props.get(k) for k in ("name", "NAME", "title", "reference") if props.get(k)), LABELS.get(dataset, dataset))
            findings.append({
                "constraint_id": str(props.get("id") or props.get("reference") or f"local:{dataset}:{len(findings)}"),
                "dataset": dataset,
                "name": str(name),
                "severity": _severity(dataset),
                "status": "confirmed",
                "current": None,
                "source_url": props.get("source_url") or item["source_url"],
                "source_name": "Local GeoJSON constraint layer",
                "source_date": props.get("source_date") or props.get("last_updated"),
                "retrieved_at": _now(),
                "raw_reference": props.get("reference") or props.get("id"),
                "coverage_warning": "Local layer intersection; verify layer date and boundary precision.",
                "source_status": "local",
            })
        return findings


class ConstraintEngine:
    def __init__(self, settings: Settings | None = None, api_client: ConstraintApiClient | None = None, local_index: GeoJSONConstraintIndex | None = None):
        self.settings = settings or Settings.from_env()
        self.api_client = api_client or ConstraintApiClient(self.settings)
        self.local_index = local_index or GeoJSONConstraintIndex.from_directory(self.settings.constraint_geojson_dir)

    def analyze(self, lat: float, lon: float, datasets: Iterable[str] = DEFAULT_DATASETS) -> list[dict]:
        local = self.local_index.query(lat, lon)
        if self.settings.enable_live_constraints:
            live = self.api_client.query(lat, lon, datasets)
        else:
            live = []
            for d in datasets:
                params = [("latitude", str(float(lat))), ("longitude", str(float(lon))), ("dataset", d), ("limit", "100")]
                url = self.settings.planning_data_api + "?" + urlencode(params)
                live.append(self.api_client._unknown(
                    d,
                    url,
                    "Live Planning Data API lookup is disabled by default. Set ENABLE_LIVE_CONSTRAINTS=true to query it.",
                ))
        combined = local + live
        seen: set[tuple[str, str, str]] = set()
        result = []
        for item in combined:
            key = (str(item.get("dataset")), str(item.get("raw_reference") or ""), str(item.get("name") or ""))
            if key in seen:
                continue
            seen.add(key)
            result.append(item)
        return result

    @staticmethod
    def sources(findings: Iterable[dict]) -> list[dict]:
        unique = {}
        for finding in findings:
            url = finding.get("source_url")
            if not url:
                continue
            unique[url] = {
                "source_name": finding.get("source_name"),
                "source_url": url,
                "retrieved_at": finding.get("retrieved_at"),
                "source_date": finding.get("source_date"),
            }
        return list(unique.values())
