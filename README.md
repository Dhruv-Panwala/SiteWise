# SiteWise UK

SiteWise UK is a map-first planning and property screening tool. A user selects a site and receives a source-linked view of planning history, local-plan constraints, environmental flags, similar applications and recommended next checks.

The first prototype uses direct public APIs for local-plan and national constraint data. It does **not** require downloading all London Local Plan GeoPackages.

## Current data sources

- Supplied London planning application CSV: `foundations_london_housing_2022_2025_20260810T013626Z.csv`
- GLA Local Plan ArcGIS FeatureServer services: https://data.london.gov.uk/dataset/planning-local-plan-data-2zjmn
- Planning Data API: https://www.planning.data.gov.uk/docs
- Planning London Datahub: https://planninglondondatahub.london.gov.uk/
- Hugging Face Inference Providers for the optional cited report: https://huggingface.co/docs/inference-providers
- Optional later Forest MCP area-context indicators

Read [data_setup.md](data_setup.md) for data contracts, API query patterns, caching, provenance and validation rules.

## Environment setup (Windows PowerShell)

### 1. Prerequisites

Install:

- Python 3.11 or newer
- Git
- A modern browser

### 2. Create and activate a virtual environment

From the project directory:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation for the current user, run this once in a PowerShell window with appropriate permissions:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Then activate the environment again.

### 3. Install dependencies

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Create local configuration

```powershell
Copy-Item .env.example .env
```

Open `.env` and set `HF_TOKEN` plus `HF_MODEL` when enabling report generation. Hugging Face is the planned hackathon LLM provider. The GLA ArcGIS and Planning Data APIs are public read-only sources and do not need keys for the prototype.

### 5. Check the supplied CSV

The default `.env` expects the CSV under `Data/raw`. Confirm it exists:

```powershell
Test-Path .\Data\raw\foundations_london_housing_2022_2025_20260810T013626Z.csv
```

If the file is stored elsewhere, change `PLANNING_CSV` in `.env` to its path.

## Run the first MVP

## Run the map demo

Start the local SiteWise demo:

```powershell
.\.venv\Scripts\python.exe scripts\run_demo.py
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). The interface supports UK
postcode/address search, map-point selection, a development description and a
source-linked dashboard for comparable permissions/refusals, site constraints,
local-plan evidence and checks to verify. It calls deterministic SiteWise evidence
only; it does not call the LLM or load `.env`.

### Check GLA Local Plan retrieval first

This standalone command calls the public ArcGIS services, cleans matching records,
and reports layer coverage without loading `.env`, the planning CSV or an LLM:

```powershell
.\.venv\Scripts\python.exe scripts/check_gla.py --lat 51.5074 --lon -0.1278 --authority Westminster
```

Omit `--authority` to check the extents of all 35 published borough/development
corporation services and query candidate layers. An extent is a search filter,
not a borough boundary. The first run takes longer; responses are cached for a
day. Use `--refresh` to refresh them. No API key or GeoPackage download is needed.

The JSON has `findings` (cleaned spatial matches), `layers` (query audit),
`services` (routing audit), and `coverage_gaps` (unknown/missing categories).
Duplicate features are combined with their contributing IDs. Geometry and GIS
bookkeeping fields remain in the response cache rather than the cleaned findings.
`confirmed` means the point intersects a published polygon; legal currency is
explicitly unverified. A complete query does not mean complete constraint coverage.

To include this connector in the full deterministic pipeline without reading `.env`:

```powershell
.\.venv\Scripts\python.exe scripts/run_mvp.py --lat 51.5074 --lon -0.1278 --description "Rear extension" --gla --no-llm --no-env-file
```

For normal application runs, `ENABLE_GLA_ARCGIS=true` enables the connector. This
setting is independent of the national `ENABLE_LIVE_CONSTRAINTS` setting. Copy
individual settings from `.env.example` yourself; do not overwrite an existing `.env`.

See [GLA integration details](Docs/GLA_ARCGIS.md) for data contracts and limitations.

Prepare the cleaned application table and TF-IDF comparable-case index:

```powershell
python scripts/prepare_data.py
```

Run deterministic retrieval for a site. The command returns constraints, nearby applications, similar applications, historical outcome summaries, data-quality warnings and sources as JSON:

```powershell
python scripts/run_mvp.py `
  --lat 51.5074 `
  --lon -0.1278 `
  --description "Redevelopment of an existing house with a rear extension and two new homes" `
  --top-n 5
```

Live Planning Data API constraint queries are disabled by default so the MVP remains fast and deterministic. To enable them for a run:

```powershell
$env:ENABLE_LIVE_CONSTRAINTS = 'true'
python scripts/run_mvp.py --lat 51.5074 --lon -0.1278 --description "Rear extension"
```

Without `HF_TOKEN`, the evidence package is still produced and the LLM field reports `not_configured`.

Run the tests:

```powershell
python -m pytest tests -q
```

### 6. Verify Python imports

```powershell
python -c "import pandas, pyarrow, duckdb, shapely, requests, dotenv; print('Python data environment OK')"
```

### 7. Verify the GLA ArcGIS service

This checks that the public service is reachable. The layer IDs will be discovered by the application rather than hard-coded.

```powershell
$service = 'https://services.arcgis.com/drifeOPKLpgnJ8Qa/arcgis/rest/services/planning_local_plan_data_07/FeatureServer?f=pjson'
Invoke-RestMethod $service | Select-Object currentVersion, serviceDescription, layers, tables
```

### 8. Verify the Planning Data API

```powershell
$url = 'https://www.planning.data.gov.uk/entity.json?latitude=51.5074&longitude=-0.1278&dataset=conservation-area&limit=5'
Invoke-RestMethod $url | Select-Object -ExpandProperty entities
```

### 9. Create local working directories

```powershell
New-Item -ItemType Directory -Force .\data\cache\arcgis_local_plan | Out-Null
New-Item -ItemType Directory -Force .\data\cache\planning_data_api | Out-Null
New-Item -ItemType Directory -Force .\data\cache\geocoding | Out-Null
New-Item -ItemType Directory -Force .\data\processed | Out-Null
```

## How the application will query data

```text
User selects site
    ↓
Resolve postcode/address and borough
    ↓
Call borough ArcGIS FeatureServer for intersecting local-plan layers
    ↓
Call Planning Data API for national constraints
    ↓
Search the cleaned planning CSV for nearby comparable cases
    ↓
Retrieve official policy evidence
    ↓
Generate a cited LLM report
```

The backend should cache responses, use timeouts and preserve each source URL and retrieval timestamp. The frontend should receive one combined site-analysis response rather than calling external APIs directly.

## Important limitations

- Public API access is suitable for the hackathon but is not an unlimited production guarantee.
- GLA local-plan coverage and synchronisation vary by borough.
- Empty API results must be reported as “no result found in this source,” not proof that no constraint exists.
- The tool is a screening aid, not planning, legal, ecological or investment advice.
