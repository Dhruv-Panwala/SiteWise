import copy
import json

import pytest
import requests
from pyproj import Transformer

from sitewise.arcgis import GLALocalPlanClient, in_service_extent, layer_dataset


POLYGON = {"type": "Polygon", "coordinates": [[
    [-0.14, 51.49], [-0.11, 51.49], [-0.11, 51.52], [-0.14, 51.52], [-0.14, 51.49],
]]}


def feature(oid, **props):
    return {"type": "Feature", "geometry": copy.deepcopy(POLYGON), "properties": {
        "objectid": oid, "sitename": "  Trafalgar  Square ", "designation": "Conservation Areas",
        "layerreference": "test-ca-1", "notes": "<p>Check &amp; verify</p>",
        "lastupdateddate": None, "source": "https://example.gov/policy", **props,
    }}


class FakeArcGIS:
    def __init__(self, features=None, *, error=False, omit_id=False, line=False):
        self.features = features if features is not None else [feature(1), feature(2)]
        self.error = error
        self.omit_id = omit_id
        self.line = line
        self.calls = []

    def __call__(self, url, params, **kwargs):
        self.calls.append((url, params))
        if self.error:
            payload = {"error": {"code": 503, "message": "Unavailable"}}
        elif url.endswith("FeatureServer"):
            payload = {"fullExtent": {"xmin": -0.2, "ymin": 51.4, "xmax": 0, "ymax": 51.6,
                                      "spatialReference": {"wkid": 4326}},
                       "layers": [{"id": 4, "name": "Conservation Areas", "geometryType": "esriGeometryPolygon"}]}
            if self.line:
                payload["layers"].append({"id": 5, "name": "Road Network", "geometryType": "esriGeometryPolyline"})
        elif url.endswith("/layers"):
            payload = {"layers": []}  # Exercise fallback to individual metadata.
        elif url.endswith("/4"):
            payload = {"objectIdField": "objectid", "maxRecordCount": 1,
                       "editingInfo": {"lastEditDate": 1700571553296}}
        elif params.get("returnIdsOnly") == "true":
            assert params["inSR"] == 4326
            assert params["geometry"] == "-0.1278,51.5074"
            assert params["spatialRel"] == "esriSpatialRelIntersects"
            payload = {} if self.omit_id else {"objectIds": [f["properties"]["objectid"] for f in self.features]}
        else:
            assert params["outSR"] == 4326
            wanted = params["objectIds"].split(",")
            payload = {"type": "FeatureCollection", "features": [
                f for f in self.features if str(f["properties"]["objectid"]) in wanted]}
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps(payload).encode()
        return response


def run_client(tmp_path, monkeypatch, api):
    monkeypatch.setattr("sitewise.arcgis.requests.get", api)
    return GLALocalPlanClient(tmp_path, workers=1).analyze(51.5074, -0.1278, authority="Westminster")


def test_batches_deduplicate_clean_and_cache_without_losing_provenance(tmp_path, monkeypatch):
    api = FakeArcGIS()
    result = run_client(tmp_path, monkeypatch, api)
    assert result["status"] == "complete"
    assert len(result["findings"]) == 1
    finding = result["findings"][0]
    assert finding["name"] == "Trafalgar Square"
    assert finding["notes"] == "Check & verify"
    assert finding["object_ids"] == ["1", "2"]
    assert finding["duplicate_count"] == 2
    assert finding["current"] is None
    assert finding["source_date"] is None
    assert finding["layer_last_edited_at"].startswith("2023-")
    assert finding["policy_links"] == ["https://example.gov/policy"]
    assert "geometry" not in finding
    assert "objectIds=1" in finding["source_url"]
    calls = len(api.calls)
    again = run_client(tmp_path, monkeypatch, api)
    assert len(api.calls) == calls
    assert again["findings"][0]["retrieved_at"] == finding["retrieved_at"]
    assert again["findings"][0]["source_status"] == "cache"
    assert any(g["dataset"] == "tree-preservation-zone" and g["status"] == "not_available" for g in result["coverage_gaps"])


def test_missing_geometry_and_polygon_hole_never_confirm(tmp_path, monkeypatch):
    missing = feature(1)
    missing["geometry"] = None
    hole = feature(2)
    hole["geometry"]["coordinates"].append([
        [-0.13, 51.50], [-0.13, 51.51], [-0.12, 51.51], [-0.12, 51.50], [-0.13, 51.50]])
    result = run_client(tmp_path, monkeypatch, FakeArcGIS([missing, hole]))
    assert not result["findings"]
    assert result["layers"][0]["status"] == "partial"
    assert result["layers"][0]["warnings"]


def test_empty_is_not_absence_and_http_200_error_is_unknown(tmp_path, monkeypatch):
    empty = run_client(tmp_path / "empty", monkeypatch, FakeArcGIS([]))
    assert empty["layers"][0]["status"] == "not_found"
    assert any(g["dataset"] == "conservation-area" and g["status"] == "not_found" for g in empty["coverage_gaps"])
    failed = run_client(tmp_path / "failed", monkeypatch, FakeArcGIS(error=True))
    assert failed["status"] == "partial"
    assert failed["services"][0]["status"] == "unknown"
    malformed = run_client(tmp_path / "bad", monkeypatch, FakeArcGIS(omit_id=True))
    assert malformed["layers"][0]["status"] == "unknown"


def test_removed_designation_and_unsupported_line_are_explicit(tmp_path, monkeypatch):
    result = run_client(tmp_path, monkeypatch, FakeArcGIS([feature(1, removeddate="2024-01-01")], line=True))
    assert result["findings"][0]["status"] == "historical"
    assert result["findings"][0]["current"] is False
    assert result["status"] == "partial"
    assert result["layers"][1]["status"] == "not_available"


@pytest.mark.parametrize("lat,lon", [(None, -0.1), (float("nan"), -0.1), (51.5, None), (0, 0), (91, -0.1)])
def test_invalid_coordinates_never_query(tmp_path, monkeypatch, lat, lon):
    def forbidden(*args, **kwargs):
        pytest.fail("Invalid coordinates must not make a network request")
    monkeypatch.setattr("sitewise.arcgis.requests.get", forbidden)
    assert GLALocalPlanClient(tmp_path).analyze(lat, lon)["status"] == "invalid_location"


def test_crs_transformation_and_unknown_extent():
    x, y = Transformer.from_crs(4326, 27700, always_xy=True).transform(-0.1278, 51.5074)
    metadata = {"fullExtent": {"xmin": x-10, "xmax": x+10, "ymin": y-10, "ymax": y+10,
                               "spatialReference": {"wkid": 27700}}}
    assert in_service_extent(metadata, 51.5074, -0.1278) is True
    assert in_service_extent(metadata, 51.60, -0.1278) is False
    assert in_service_extent({}, 51.5, -0.1) is None


def test_partial_batch_retains_warning(tmp_path, monkeypatch):
    api = FakeArcGIS()
    def missing_feature(url, params, **kwargs):
        response = api(url, params, **kwargs)
        if params.get("objectIds") == "2":
            response._content = b'{"type":"FeatureCollection","features":[]}'
        return response
    result = run_client(tmp_path, monkeypatch, missing_feature)
    assert len(result["findings"]) == 1
    assert result["status"] == "partial"


def test_expired_cache_not_reused_after_error(tmp_path, monkeypatch):
    api = FakeArcGIS()
    run_client(tmp_path, monkeypatch, api)
    monkeypatch.setattr("sitewise.arcgis.requests.get", FakeArcGIS(error=True))
    result = GLALocalPlanClient(tmp_path, cache_ttl=0).analyze(51.5074, -0.1278, authority="Westminster")
    assert result["status"] == "partial"
    assert not result["findings"]


def test_point_on_polygon_edge_is_included(tmp_path, monkeypatch):
    boundary = feature(1)
    boundary["geometry"]["coordinates"] = [[
        [-0.1278, 51.49], [-0.11, 51.49], [-0.11, 51.52], [-0.1278, 51.52], [-0.1278, 51.49]]]
    result = run_client(tmp_path, monkeypatch, FakeArcGIS([boundary]))
    assert result["findings"][0]["status"] == "confirmed"


def test_service_extent_routing_queries_unknown_extent_but_skips_outside(tmp_path, monkeypatch):
    client = GLALocalPlanClient(tmp_path, workers=1)
    checked = []
    def service(entry):
        number, authority = entry
        extent = {} if number == 35 else {"fullExtent": {
            "xmin": 0, "ymin": 52, "xmax": 1, "ymax": 53, "spatialReference": {"wkid": 4326}}}
        return {"authority": authority, "source_url": f"https://example/{number}", "status": "available",
                "metadata": {**extent, "layers": [{"id": 0, "name": "Conservation Areas"}]}}
    def layer(task):
        checked.append(task[0]["authority"])
        return {"dataset": "conservation-area", "status": "not_found", "findings": []}
    monkeypatch.setattr(client, "_service", service)
    monkeypatch.setattr(client, "_layer_inventory", lambda s: s)
    monkeypatch.setattr(client, "_layer", layer)
    result = client.analyze(51.5074, -0.1278)
    assert len(result["services"]) == 35
    assert checked == ["OPDC"]


def test_bulk_inventory_skips_unrelated_layer_queries(tmp_path, monkeypatch):
    api = FakeArcGIS()
    def bulk_api(url, params, **kwargs):
        response = api(url, params, **kwargs)
        if url.endswith("/layers"):
            response._content = json.dumps({"layers": [{"id": 4, "name": "Conservation Areas",
                "geometryType": "esriGeometryPolygon", "fields": [], "objectIdField": "objectid",
                "extent": {"xmin": 0, "ymin": 52, "xmax": 1, "ymax": 53,
                           "spatialReference": {"wkid": 4326}}}]}).encode()
        return response
    result = run_client(tmp_path, monkeypatch, bulk_api)
    assert result["layers"][0]["spatial_relation"] == "outside_layer_extent"
    assert not any(url.endswith("/query") for url, _ in api.calls)


def test_local_heritage_and_nature_are_not_statutory_designation_categories():
    assert layer_dataset("Locally Listed Buildings").startswith("local-plan:")
    assert layer_dataset("Nature Conservation Areas").startswith("local-plan:")
    assert layer_dataset("Conservation Areas") == "conservation-area"
    assert layer_dataset("Listed Buildings") == "listed-building"
