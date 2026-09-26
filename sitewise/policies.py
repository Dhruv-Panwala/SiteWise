"""Official policy retrieval with geographic verification and bounded extracts."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import re
import time
from urllib.parse import urlencode, urlparse

from bs4 import BeautifulSoup
import pdfplumber
import requests
from shapely import wkt
from shapely.geometry import Point

from .planning import validate_coordinates
from .policy_sources import COUNCIL_SOURCES, LONDON_SOURCES

BOUNDARY_URL = "https://www.planning.data.gov.uk/entity.json"
MAX_DOWNLOAD = 16 * 1024 * 1024
ALLOWED_HOSTS = {"www.planning.data.gov.uk", "www.wandsworth.gov.uk", "www.westminster.gov.uk", "www.lambeth.gov.uk", "www.london.gov.uk"}


def proposal_topics(query):
    patterns = {
        "extension": r"\bextend|\bextension",
        "new_homes": r"\bnew\b.{0,30}\b(home|house|dwelling|flat|unit)|\brebuild|\breconstruct|\bredevelopment|\breplace",
        "conversion": r"\bconvert|\bconversion|\bsubdivi",
        "demolition": r"\bdemoli|\bknock down",
        "trees": r"\btree|\broot|\bwoodland",
        "roof": r"\broof|\bdormer|\bloft",
    }
    return [key for key, pattern in patterns.items() if re.search(pattern, query, re.I)]


def html_text(content):
    soup = BeautifulSoup(content, "html.parser")
    for node in soup.select("script, style, nav, footer, header, form, noscript"):
        node.decompose()
    main = soup.find("main") or soup.find("article") or soup
    return " ".join(main.get_text(" ", strip=True).split())


def extract_passage(text, start, end=None, limit=1400):
    """Choose the last heading occurrence (avoids table-of-contents hits)."""
    matches = list(re.finditer(start, text, re.I))
    if not matches:
        return None
    fragment = text[matches[-1].start():]
    stop = re.search(end, fragment[matches[-1].end() - matches[-1].start():], re.I) if end else None
    if stop:
        fragment = fragment[:matches[-1].end() - matches[-1].start() + stop.start()]
    if len(fragment.strip()) < 65:
        return None
    return fragment[:limit].strip() + (" [extract shortened; read full source]" if len(fragment) > limit else "")


class CouncilPolicyClient:
    def __init__(self, settings):
        self.settings = settings
        self.cache_dir = settings.cache_dir / "council_policy"

    def _download(self, url):
        # Only server-maintained official sources. Never fetch a URL supplied by a user/LLM.
        for _ in range(4):
            parsed = urlparse(url)
            if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS or parsed.port not in (None, 443):
                raise ValueError("Source is outside the official-source allowlist")
            with requests.get(url, timeout=self.settings.request_timeout_seconds, stream=True,
                              allow_redirects=False, headers={"User-Agent": "SiteWiseUK-policy-screen/0.1"}) as response:
                if response.is_redirect:
                    from urllib.parse import urljoin
                    url = urljoin(url, response.headers["Location"])
                    continue
                response.raise_for_status()
                data = bytearray()
                for part in response.iter_content(65536):
                    data.extend(part)
                    if len(data) > MAX_DOWNLOAD:
                        raise ValueError("Policy source exceeds download limit")
                return bytes(data)
        raise ValueError("Too many source redirects")

    def _cached(self, key, producer):
        path = self.cache_dir / (sha256(key.encode()).hexdigest() + ".json")
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
            if 0 <= time.time() - cached["cached_at"] < self.settings.cache_ttl_seconds:
                return cached["value"], cached["retrieved_at"], "cache"
        except (OSError, ValueError, KeyError, TypeError):
            pass
        value = producer()
        retrieved = datetime.now(timezone.utc).isoformat()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        # A truncated cache is safely ignored on the next read; no stale fallback.
        path.write_text(json.dumps({"cached_at": time.time(), "retrieved_at": retrieved, "value": value}), encoding="utf-8")
        return value, retrieved, "live"

    def resolve_authority(self, lat, lon):
        if validate_coordinates(lat, lon) != "valid":
            return {"status": "unknown", "name": None, "message": "Invalid or missing UK coordinates."}
        url = BOUNDARY_URL + "?" + urlencode(dict(dataset="local-authority-district", latitude=lat, longitude=lon, limit=100))
        try:
            data, retrieved, mode = self._cached(url, lambda: json.loads(self._download(url)))
            matches = []
            for entity in data.get("entities", []):
                if entity.get("end-date") or not entity.get("geometry"):
                    continue
                geom = wkt.loads(entity["geometry"])
                if geom.geom_type in {"Polygon", "MultiPolygon"} and geom.is_valid and geom.intersects(Point(lon, lat)):
                    matches.append(entity)
            if len(matches) != 1:
                raise ValueError("No unique valid boundary match")
            entity = matches[0]
            return {"status": "boundary_verified", "name": entity["name"], "code": entity["reference"],
                    "source_url": url, "source_date": entity.get("entry-date"), "retrieved_at": retrieved,
                    "source_status": mode, "message": "Administrative district verified by point-in-polygon; special planning authorities and neighbourhood plans still need checking."}
        except Exception as exc:
            return {"status": "unknown", "name": None, "source_url": url,
                    "message": f"Council boundary could not be verified ({type(exc).__name__}). No borough rules have been assigned."}

    def _document(self, url, specs):
        pages = sorted({p for spec in specs for p in (spec.get("pages") or [])})
        def read():
            content = self._download(url)
            if content.startswith(b"%PDF"):
                with pdfplumber.open(BytesIO(content)) as reader:
                    return [{"page": p, "text": " ".join((reader.pages[p-1].extract_text(x_tolerance=1) or "").split())}
                            for p in pages if 0 < p <= len(reader.pages)]
            return [{"page": None, "text": html_text(content)}]
        return self._cached("words-v3:" + url + json.dumps(pages), read)

    def retrieve(self, lat, lon, query):
        authority = self.resolve_authority(lat, lon)
        name = authority.get("name")
        topics = proposal_topics(query)
        specs = list(COUNCIL_SOURCES.get(name, []))
        if str(authority.get("code", "")).startswith("E09"):
            specs += LONDON_SOURCES
        specs = [s for s in specs if "any" in s["topics"] or set(topics).intersection(s["topics"])]
        grouped = {}
        for spec in specs:
            grouped.setdefault(spec["url"], []).append(spec)
        def retrieve_document(pair):
            url, rules = pair
            try:
                pages, retrieved, mode = self._document(url, rules)
                return url, (pages, retrieved, mode), None
            except Exception as exc:
                return url, None, {"source_url": url, "status": "unavailable", "message": f"Official text retrieval failed ({type(exc).__name__}); no rule inferred."}
        documents, errors = {}, []
        with ThreadPoolExecutor(max_workers=3) as pool:
            for url, doc, error in pool.map(retrieve_document, grouped.items()):
                if error:
                    errors.append(error)
                else:
                    documents[url] = doc
        items = []
        for spec in specs:
            if spec["url"] not in documents:
                continue
            pages, retrieved, mode = documents[spec["url"]]
            selected = [p for p in pages if not spec.get("pages") or p["page"] in spec["pages"]]
            text = " ".join(p["text"] for p in selected)
            excerpt = extract_passage(text, spec["start"], spec["end"])
            if not excerpt:
                errors.append({"source_url": spec["url"], "status": "no_relevant_text", "message": f"Could not locate section: {spec['title']}. No rule inferred."})
                continue
            start_page = next((p["page"] for p in selected if re.search(spec["start"], p["text"], re.I)), None)
            url = spec["url"] + (f"#page={start_page}" if start_page else "")
            items.append({"id": f"P{len(items)+1}", "title": spec["title"],
                          "authority": "London-wide" if spec in LONDON_SOURCES else name,
                          "topics": [t for t in topics if t in spec["topics"]],
                          "excerpt": excerpt, "suggested_action": spec["action"],
                          "status": "text_retrieved", "document_status": spec["document_status"],
                          "source_url": url, "retrieved_at": retrieved, "source_status": mode,
                          "page": start_page})
        gaps = []
        if name not in COUNCIL_SOURCES:
            gaps.append("Council-specific text coverage is currently limited to Wandsworth, Westminster and Lambeth. Other areas are not covered by this pilot.")
        gaps.append("Selected policy passages only, not a complete development-plan assessment. Check current amendments, site allocations, neighbourhood plans and the actual planning authority.")
        return {"status": "partial" if items else "unavailable", "authority": authority,
                "proposal_topics": topics, "items": items, "errors": errors, "limitations": gaps}
