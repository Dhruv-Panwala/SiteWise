"""GLA local-plan retrieval. No credentials, LLM calls or GeoPackage downloads.

Service identifiers are transcribed from the publisher's dataset resource list;
layer IDs, schemas and extents are discovered from the services at runtime.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from html import unescape
import hashlib
import json
import math
import re
from pathlib import Path
from urllib.parse import urlencode

from pyproj import Transformer
from pyproj.exceptions import ProjError
import requests
from shapely.geometry import Point, shape
from shapely.errors import ShapelyError

from .constraints import DEFAULT_DATASETS, _cache_key, _cache_read, _cache_write
from .planning import validate_coordinates


DATASET_URL = "https://data.london.gov.uk/dataset/planning-local-plan-data-2zjmn"
BASE_URL = "https://services.arcgis.com/drifeOPKLpgnJ8Qa/arcgis/rest/services"
# Order is the published _01 .. _35 resource mapping, not alphabetical inference.
AUTHORITIES = (
    "City of London", "Barking and Dagenham", "Barnet", "Bexley", "Brent",
    "Bromley", "Camden", "Croydon", "Ealing", "Enfield", "Greenwich",
    "Hackney", "Hammersmith and Fulham", "Haringey", "Harrow", "Havering",
    "Hillingdon", "Hounslow", "Islington", "Kensington and Chelsea",
    "Kingston upon Thames", "Lambeth", "Lewisham", "Merton", "Newham",
    "Redbridge", "Richmond upon Thames", "Southwark", "Sutton", "Tower Hamlets",
    "Waltham Forest", "Wandsworth", "Westminster", "LLDC", "OPDC",
)


class ArcGISError(ValueError):
    pass


def clean_text(value):
    if value is None:
        return None
    text = " ".join(unescape(re.sub(r"<[^>]*>", " ", str(value))).split())
    return None if text.lower() in {"", "null", "none", "n/a", "nan", "<null>"} else text


def layer_dataset(name: str) -> str:
    """Classify layer labels only; the polygon intersection determines presence."""
    label = name.casefold()
    if any(term in label for term in ("locally listed", "local list", "nature conservation")):
        return "local-plan:" + re.sub(r"[^a-z0-9]+", "-", label).strip("-")
    for needle, dataset in (
        ("conservation area", "conservation-area"),
        ("tree preservation", "tree-preservation-zone"),
        ("protected tree", "tree-preservation-zone"),
        ("flood", "flood-risk-zone"),
        ("green belt", "green-belt"),
        ("listed building", "listed-building"),
        ("article 4", "article-4-direction-area"),
        ("article four", "article-4-direction-area"),
        ("ancient woodland", "ancient-woodland"),
        ("special scientific interest", "site-of-special-scientific-interest"),
    ):
        if needle in label:
            return dataset
    return "local-plan:" + re.sub(r"[^a-z0-9]+", "-", label).strip("-")


def in_service_extent(metadata: dict, lat: float, lon: float) -> bool | None:
    """Extents select candidate services, never establish borough membership."""
    extent = metadata.get("fullExtent") or {}
    sr = extent.get("spatialReference") or {}
    wkid = sr.get("latestWkid") or sr.get("wkid")
    try:
        if not wkid:
            return None
        x, y = Transformer.from_crs(4326, wkid, always_xy=True).transform(lon, lat)
        return extent["xmin"] <= x <= extent["xmax"] and extent["ymin"] <= y <= extent["ymax"]
    except (ValueError, KeyError, TypeError, ProjError):
        return None


class GLALocalPlanClient:
    def __init__(self, cache_dir: Path, *, base_url: str = BASE_URL,
                 timeout: int = 20, cache_ttl: int = 86400, workers: int = 4):
        self.cache_dir = Path(cache_dir) / "arcgis_local_plan"
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.cache_ttl = cache_ttl
        self.workers = max(1, min(workers, 4))

    def _get(self, url: str, params: dict) -> tuple[dict, dict]:
        params = dict(sorted(params.items()))
        path = self.cache_dir / f"{_cache_key(url, list(params.items()))}.json"
        cached, fresh = _cache_read(path, self.cache_ttl)
        if cached and fresh and isinstance(cached.get("payload"), dict):
            return cached["payload"], {**cached["provenance"], "source_status": "cache"}
        # Expired responses are not silently re-used as current evidence.
        response = requests.get(url, params=params, timeout=self.timeout,
                                headers={"User-Agent": "sitewise-uk-hackathon/0.1"})
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ArcGISError("ArcGIS returned a non-object response")
        if payload.get("error"):
            error = payload["error"]
            raise ArcGISError(f"ArcGIS {error.get('code')}: {error.get('message')}")
        now = datetime.now(timezone.utc)
        provenance = {"query_url": url + "?" + urlencode(params),
                      "retrieved_at": now.isoformat(), "source_status": "live"}
        _cache_write(path, {"cached_at_epoch": now.timestamp(), "payload": payload,
                            "provenance": provenance})
        return payload, provenance

    def _service(self, entry: tuple[int, str]) -> dict:
        number, authority = entry
        url = f"{self.base_url}/planning_local_plan_data_{number:02d}/FeatureServer"
        try:
            metadata, provenance = self._get(url, {"f": "json"})
            if not isinstance(metadata.get("layers"), list):
                raise ArcGISError("Service metadata has no layer inventory")
            return {"authority": authority, "source_url": url, "status": "available",
                    "metadata": metadata, **provenance}
        except (requests.RequestException, ValueError, OSError) as exc:
            return {"authority": authority, "source_url": url, "status": "unknown",
                    "message": str(exc)[:300]}

    def _layer(self, task: tuple[dict, dict, float, float]) -> dict:
        service, layer, lat, lon = task
        url = f"{service['source_url']}/{layer['id']}"
        dataset = layer_dataset(layer["name"])
        result = {"authority": service["authority"], "layer_id": layer["id"],
                  "name": layer["name"], "dataset": dataset, "source_url": url,
                  "status": "unknown", "findings": [], "warnings": []}
        if layer.get("geometryType") != "esriGeometryPolygon":
            result.update(status="not_available", message="Non-polygon layer requires a separate proximity check.")
            return result
        try:
            if "fields" in layer and "objectIdField" in layer:
                metadata = layer
            else:
                metadata, _ = self._get(url, {"f": "json"})
            if in_service_extent({"fullExtent": metadata.get("extent")}, lat, lon) is False:
                result.update(status="not_found", spatial_relation="outside_layer_extent",
                              matched_record_count=0,
                              message="Point is outside this layer's published extent; feature query skipped.",
                              retrieved_at=service.get("layer_inventory_retrieved_at"))
                return result
            fields = metadata.get("fields") or []
            oid = metadata.get("objectIdField") or next(
                (f["name"] for f in fields if f.get("type") == "esriFieldTypeOID"), None)
            if not oid:
                raise ArcGISError("Layer has no object ID field")
            params = {"f": "json", "where": "1=1", "geometry": f"{lon},{lat}",
                      "geometryType": "esriGeometryPoint", "inSR": 4326,
                      "spatialRel": "esriSpatialRelIntersects", "returnIdsOnly": "true"}
            ids_payload, provenance = self._get(url + "/query", params)
            if "objectIds" not in ids_payload:
                raise ArcGISError("Query omitted objectIds; coverage cannot be determined")
            ids = sorted(set(ids_payload["objectIds"] or []))
            if ids_payload.get("exceededTransferLimit"):
                raise ArcGISError("Object ID query exceeded transfer limit")
            result.update(provenance)
            result["matched_record_count"] = len(ids)
            seen = {}
            size = min(int(metadata.get("maxRecordCount") or 100), 100)
            for start in range(0, len(ids), size):
                batch_ids = ids[start:start + size]
                payload, feature_provenance = self._get(url + "/query", {
                    "f": "geojson", "objectIds": ",".join(map(str, batch_ids)),
                    "outFields": "*", "returnGeometry": "true", "outSR": 4326,
                })
                features = payload.get("features")
                if not isinstance(features, list) or payload.get("type") != "FeatureCollection":
                    raise ArcGISError("Expected a GeoJSON FeatureCollection")
                returned_ids = {str((f.get("properties") or {}).get(oid)) for f in features}
                if payload.get("exceededTransferLimit") or returned_ids != set(map(str, batch_ids)):
                    result["warnings"].append("Incomplete feature batch; some matched records are unavailable.")
                for feature in features:
                    try:
                        if not isinstance(feature.get("geometry"), dict):
                            raise ValueError("missing geometry")
                        geometry = shape(feature["geometry"])
                        if geometry.geom_type not in {"Polygon", "MultiPolygon"} or not geometry.is_valid:
                            raise ValueError("invalid polygon")
                        if not geometry.intersects(Point(lon, lat)):
                            result["warnings"].append("Server match failed local point-in-polygon verification.")
                            continue
                    except (ValueError, TypeError, KeyError, AttributeError, ShapelyError):
                        result["warnings"].append("Matched feature has missing or invalid polygon geometry.")
                        continue
                    props = {k.lower(): clean_text(v) for k, v in (feature.get("properties") or {}).items()}
                    feature_id = str((feature.get("properties") or {}).get(oid))
                    # Merge only identical attributes AND geometry; keep all contributing IDs.
                    dedup_props = {k: v for k, v in props.items() if k != oid.lower() and v is not None}
                    digest = hashlib.sha256((json.dumps(dedup_props, sort_keys=True) + geometry.normalize().wkb_hex).encode()).hexdigest()
                    if digest in seen:
                        seen[digest]["object_ids"].append(feature_id)
                        seen[digest]["duplicate_count"] += 1
                        continue
                    record_url = url + "/query?" + urlencode({"f": "pjson", "objectIds": feature_id, "outFields": "*", "returnGeometry": "false"})
                    retired = bool(props.get("removeddate")) or (props.get("status") or "").lower() in {"removed", "revoked", "superseded", "deleted", "expired"}
                    finding = {
                        "constraint_id": f"gla:{service['authority']}:{layer['id']}:{feature_id}",
                        "dataset": dataset, "name": props.get("sitename") or layer["name"],
                        "designation": props.get("designation") or layer["name"],
                        "status": "historical" if retired else "confirmed",
                        "current": False if retired else None,
                        "temporal_status": "source_marked_removed" if retired else "published_layer_legal_currency_unverified",
                        "spatial_relation": "point_intersects_geometry", "severity": "unknown",
                        "authority": props.get("planningauthority") or service["authority"],
                        "borough": props.get("borough"), "address": props.get("address"),
                        "raw_reference": props.get("sitereference") or props.get("layerreference"),
                        "classification": props.get("classification"), "notes": props.get("notes"),
                        "source_record_status": props.get("status"),
                        "policy_links": list(dict.fromkeys(re.findall(r"https?://[^\s<>\"']+", unescape(" ".join(str((feature.get("properties") or {}).get(k) or "") for k in ("source", "extrainfo1", "extrainfo2", "extrainfo3")))))),
                        "source_details": {k: props[k] for k in ("source", "extrainfo1", "extrainfo2", "extrainfo3") if props.get(k)},
                        "source_date": props.get("lastupdateddate"),
                        "layer_last_edited_at": self._edit_date(metadata),
                        "removed_date": props.get("removeddate"),
                        "source_url": record_url, "source_name": "GLA Local Plan ArcGIS",
                        "layer_url": url, "layer_name": layer["name"],
                        "object_ids": [feature_id], "duplicate_count": 1,
                        "retrieved_at": feature_provenance["retrieved_at"],
                        "source_status": feature_provenance["source_status"],
                        "coverage_warning": "Verified point intersection in this published layer. Site boundary, legal currency and source completeness require verification.",
                    }
                    seen[digest] = finding
                    result["findings"].append(finding)
            result["warnings"] = list(dict.fromkeys(result["warnings"]))
            result["status"] = "partial" if result["warnings"] else ("matched" if result["findings"] else "not_found")
            if not ids:
                result["message"] = "No intersection returned in this layer; this does not prove absence of a constraint."
        except (requests.RequestException, ValueError, OSError) as exc:
            result.update(status="partial" if result["findings"] else "unknown", message=str(exc)[:300])
        return result

    def _layer_inventory(self, service: dict) -> dict:
        # ArcGIS exposes all layer schemas/extents in one request. Retain the
        # original inventory and fall back to individual metadata on failure.
        try:
            payload, provenance = self._get(service["source_url"] + "/layers", {"f": "json"})
            detailed = {layer["id"]: layer for layer in payload.get("layers", [])}
            service["metadata"]["layers"] = [
                detailed.get(layer["id"], layer) for layer in service["metadata"]["layers"]]
            service["layer_inventory_retrieved_at"] = provenance["retrieved_at"]
        except (requests.RequestException, ValueError, OSError, KeyError, TypeError):
            pass
        return service

    @staticmethod
    def _edit_date(metadata: dict) -> str | None:
        millis = (metadata.get("editingInfo") or {}).get("lastEditDate")
        try:
            return datetime.fromtimestamp(float(millis) / 1000, timezone.utc).isoformat() if millis is not None else None
        except (ValueError, TypeError, OverflowError, OSError):
            return None

    def analyze(self, lat, lon, *, authority: str | None = None) -> dict:
        quality = validate_coordinates(lat, lon)
        def coordinate(value):
            try:
                return float(value) if math.isfinite(float(value)) else None
            except (ValueError, TypeError):
                return None
        output = {"status": "unknown", "property": {"latitude": coordinate(lat), "longitude": coordinate(lon)},
                  "findings": [], "layers": [], "services": [], "coverage_gaps": [],
                  "dataset_url": DATASET_URL, "licence": "Open Government Licence v3.0",
                  "scope": "GLA published local-plan layers; point screening only, London coverage."}
        if quality != "valid":
            output.update(status="invalid_location", message=f"Coordinates are {quality}; no queries attempted.")
            return output
        lat, lon = float(lat), float(lon)
        entries = list(enumerate(AUTHORITIES, 1))
        if authority:
            name = authority.strip().casefold().replace("&", "and")
            name = re.sub(r"^(london borough of |royal borough of )", "", name)
            entries = [(n, a) for n, a in entries if a.casefold() == name]
            if not entries:
                output.update(status="not_available", message="Authority is not in the GLA registry. Use a London borough name, LLDC or OPDC.")
                return output
        # Bounding box is only a cheap exclusion, not a claim of London membership.
        if not (51.2 <= lat <= 51.8 and -0.65 <= lon <= 0.4):
            output.update(status="outside_coverage", message="Location is outside the London screening bounds.")
            return output
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            services = list(pool.map(self._service, entries))
            candidates = []
            for service in services:
                if service["status"] == "available":
                    intersects = in_service_extent(service["metadata"], lat, lon)
                    service["extent_match"] = intersects
                    if intersects is not False:
                        candidates.append(service)
                output["services"].append({k: v for k, v in service.items() if k != "metadata"})
            candidates = list(pool.map(self._layer_inventory, candidates))
            tasks = [(s, layer, lat, lon) for s in candidates for layer in s["metadata"]["layers"]]
            output["layers"] = list(pool.map(self._layer, tasks))
        output["findings"] = [f for layer in output["layers"] for f in layer["findings"]]
        for layer in output["layers"]:
            layer["finding_count"] = len(layer.pop("findings"))
        for dataset in DEFAULT_DATASETS:
            relevant = [l for l in output["layers"] if l["dataset"] == dataset]
            if not relevant:
                status, message = "not_available", "No matching layer was discoverable in the selected candidate services."
            elif any(l["status"] in {"unknown", "partial", "not_available"} for l in relevant):
                status, message = "unknown", "One or more relevant layers could not be fully checked."
            elif any(l["status"] == "matched" for l in relevant):
                continue
            else:
                status, message = "not_found", "No intersection returned in the queried layers; constraint absence is not established."
            output["coverage_gaps"].append({"dataset": dataset, "status": status, "message": message})
        failed = any(s["status"] == "unknown" for s in output["services"]) or any(
            l["status"] in {"unknown", "partial", "not_available"} for l in output["layers"])
        output["status"] = "partial" if failed else ("complete" if candidates else "no_candidate_service")
        output["selection"] = "User-selected authority only; other boroughs and development corporations were not checked." if authority else "All 35 service extents checked; intersecting or unknown extents queried. Extents do not establish borough membership."
        return output
