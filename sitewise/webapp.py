"""Small demo server for the SiteWise map interface.

Evidence is returned first; optional explanations use only server-stored evidence.
"""
from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import re
import time
from uuid import uuid4
from threading import Lock
from urllib.parse import quote

import requests
from flask import Flask, jsonify, request, send_from_directory

from .config import ROOT, Settings
from .evidence import EvidenceService
from .planning import ensure_prepared, validate_coordinates
from .similarity import ComparableCaseIndex
from .llm import generate_report


POSTCODE_PATTERN = re.compile(r"^[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}$", re.IGNORECASE)
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"


class SiteWiseDemo:
    def __init__(self, root: Path = ROOT):
        self.root = Path(root)
        # Never load the user's .env from the demo web process.
        self.settings = Settings.from_env(root=self.root, load_env_file=False)
        self._applications = None
        self._index = None
        self._lock = Lock()
        self._screens = {}
        self._report_lock = Lock()

    def _load(self) -> tuple:
        with self._lock:
            if self._applications is None:
                prepared_path = self.settings.processed_dir / "planning_applications.parquet"
                self._applications = ensure_prepared(self.settings.planning_csv, prepared_path)
                index_dir = self.settings.processed_dir / "comparable_index"
                expected = ["comparable_cases.parquet", "comparable_tfidf.npz", "comparable_vectorizer.joblib"]
                if not all((index_dir / name).exists() for name in expected):
                    ComparableCaseIndex.build(self._applications, index_dir)
                self._index = ComparableCaseIndex.load(index_dir)
        return self._applications, self._index

    def geocode(self, query: str) -> list[dict]:
        query = " ".join((query or "").split())[:180]
        if len(query) < 3:
            return []
        timeout = self.settings.request_timeout_seconds
        if POSTCODE_PATTERN.fullmatch(query):
            response = requests.get(
                f"https://api.postcodes.io/postcodes/{quote(query)}", timeout=timeout,
                headers={"User-Agent": "sitewise-uk-hackathon/0.1"},
            )
            if response.status_code == 404:
                return []
            response.raise_for_status()
            result = response.json().get("result") or {}
            if result.get("latitude") is None or result.get("longitude") is None:
                return []
            return [{
                "label": f"{result.get('postcode')} — {result.get('admin_district') or 'UK'}",
                "latitude": result["latitude"], "longitude": result["longitude"],
                "source": "postcodes.io",
            }]

        response = requests.get(
            NOMINATIM_URL,
            params={"q": f"{query}, United Kingdom", "format": "jsonv2", "addressdetails": 1, "limit": 5, "countrycodes": "gb"},
            timeout=timeout,
            headers={"User-Agent": "sitewise-uk-hackathon/0.1 (hackathon demo)"},
        )
        response.raise_for_status()
        locations = []
        for item in response.json():
            try:
                lat, lon = float(item["lat"]), float(item["lon"])
            except (KeyError, TypeError, ValueError):
                continue
            if validate_coordinates(lat, lon) != "valid":
                continue
            locations.append({"label": item.get("display_name", "UK address"), "latitude": lat, "longitude": lon, "source": "OpenStreetMap Nominatim"})
        return locations

    def analyze(self, payload: dict) -> dict:
        try:
            lat, lon = float(payload.get("latitude")), float(payload.get("longitude"))
        except (TypeError, ValueError):
            raise ValueError("Select a valid location on the map or from search results.")
        if validate_coordinates(lat, lon) != "valid":
            raise ValueError("The selected location is missing or outside the UK.")
        description = " ".join(str(payload.get("description") or "").split())[:1200]
        if not description:
            raise ValueError("Add a short proposed-development description to find comparable applications.")
        include_gla = bool(payload.get("include_gla", True))
        radius_m = min(max(float(payload.get("radius_m", 1000)), 100), 5000)
        apps, index = self._load()
        settings = replace(self.settings, enable_gla_arcgis=include_gla, enable_council_policies=True)
        evidence = EvidenceService(apps, index, settings=settings).analyze(
            lat, lon, description=description, radius_m=radius_m, top_n=5,
        )
        # Ensure NumPy/Pandas values cannot leak into the browser response.
        evidence = json.loads(json.dumps(evidence, ensure_ascii=False, default=str))
        identity = uuid4().hex
        with self._lock:
            self._screens = {k: v for k, v in self._screens.items() if time.monotonic() - v[0] < 1800}
            while len(self._screens) >= 16:
                self._screens.pop(next(iter(self._screens)))
            self._screens[identity] = (time.monotonic(), evidence)
        return {**evidence, "evidence_id": identity}

    def explain(self, identity):
        # No browser-supplied context or URLs reach the LLM or retrieval layer.
        with self._report_lock:
            with self._lock:
                record = self._screens.get(identity)
            if not record or time.monotonic() - record[0] >= 1800:
                raise ValueError("This screen expired. Screen the site again to explain its evidence.")
            evidence = record[1]
            if "llm_report" not in evidence:
                evidence["llm_report"] = generate_report(evidence, self.settings) if self.settings.enable_llm_reports else {
                    "status": "disabled", "text": None, "message": "AI explanation is disabled; the sourced council guidance below is still available."}
            return evidence["llm_report"]


def create_app(root: Path = ROOT, demo: SiteWiseDemo | None = None) -> Flask:
    static_dir = Path(root) / "web"
    app = Flask(__name__, static_folder=str(static_dir), static_url_path="")
    demo = demo or SiteWiseDemo(root)

    @app.get("/")
    def home():
        return send_from_directory(static_dir, "index.html")

    @app.get("/api/health")
    def health():
        settings = getattr(demo, "settings", None)
        return jsonify({"status": "ok", "service": "SiteWise UK demo", "llm_enabled": bool(settings and settings.enable_llm_reports and settings.hf_token)})

    @app.post("/api/explain")
    def explain():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or not isinstance(payload.get("evidence_id"), str):
            return jsonify({"error": "Provide the evidence_id from a completed site screen."}), 400
        try:
            return jsonify(demo.explain(payload["evidence_id"]))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    @app.get("/api/geocode")
    def geocode():
        try:
            return jsonify({"results": demo.geocode(request.args.get("q", ""))})
        except requests.RequestException:
            return jsonify({"error": "Address search is temporarily unavailable. You can still click the map to select a site."}), 503

    @app.post("/api/analyze")
    def analyze():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"error": "Send a JSON request body."}), 400
        try:
            lat, lon = float(payload.get("latitude")), float(payload.get("longitude"))
        except (TypeError, ValueError):
            return jsonify({"error": "Select a valid location on the map or from search results."}), 400
        if validate_coordinates(lat, lon) != "valid":
            return jsonify({"error": "The selected location is missing or outside the UK."}), 400
        try:
            return jsonify(demo.analyze(payload))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except (OSError, requests.RequestException) as exc:
            return jsonify({"error": f"Analysis source unavailable: {exc.__class__.__name__}. Try again or turn off the GLA layer check."}), 503

    return app
