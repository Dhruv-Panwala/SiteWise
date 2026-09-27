# SiteWise UK

SiteWise UK helps property buyers, homeowners and developers investigate planning considerations before committing to a site or design. Select a map location or search for an address, describe a proposal, and review council guidance alongside spatial constraints and historical applications.

Built for House London #2 Data Hackathon. The idea grew from a real property search where a protected tree complicated the proposed building layout.

## What it does

- Finds nearby planning applications and ranks comparable descriptions using TF-IDF and cosine similarity.
- Checks available planning layers using geometric intersections.
- Retrieves relevant passages from official council webpages and PDFs, with source links.
- Presents design checks, evidence and missing information in a map dashboard.
- Optionally generates a cited explanation through Hugging Face after evidence retrieval.

Council-text coverage currently includes **Wandsworth, Westminster and Lambeth**, plus selected London-wide policies. The interface accepts UK locations, but data and policy coverage are not UK-wide.

## Quick start

Requires Python 3.11+ and the supplied planning CSV. From the project folder in PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Place `foundations_london_housing_2022_2025_20260810T013626Z.csv` in `Data/raw/`. The dataset is not included in Git. The server prepares the searchable dataset on the first screen if needed.

Start the website with live national constraint queries:

```powershell
.\.venv\Scripts\python.exe scripts\run_demo.py --live-constraints
```

Open **http://127.0.0.1:8000**. Click **Try central London example**, review the proposal and choose **Screen this site**. The GLA checkbox separately controls local-plan layer queries. Initial retrieval can take longer while data and caches are prepared.

### Optional AI explanation

```powershell
.\.venv\Scripts\python.exe scripts\run_demo.py --live-constraints --prompt-hf-token
```

Enter a Hugging Face token at the hidden prompt. It is kept in the server process, not saved to a file. The default model/provider are `microsoft/Phi-4-mini-instruct` and `featherless-ai`; inference requires supported provider access and any applicable credits. Council guidance remains usable if AI is unavailable.

**The web server and terminal demo do not read `.env`.** Configure them with startup flags or environment variables in the same terminal. [`.env.example`](.env.example) documents the available settings.

For example, if the CSV is elsewhere:

```powershell
$env:PLANNING_CSV = 'C:\path\to\planning.csv'
```

To change inference settings, set `HF_MODEL` and `HF_PROVIDER` before starting the server. Restart after code or configuration changes.

### Verify the running server

Visit **http://127.0.0.1:8000/api/health**. With `--live-constraints`, `live_constraints_enabled` should be `true`.

If another server already uses port 8000, add `--port 8001` and open the matching URL. Rerun the site screen after restarting; existing results do not refresh automatically.

## Terminal demo

```powershell
$env:ENABLE_LIVE_CONSTRAINTS = 'true'
.\.venv\Scripts\python.exe scripts\demo_terminal.py --gla --prompt-hf-token
```

This prints the central London example, council passages, source links and historical evidence before requesting an AI explanation. Omit `--prompt-hf-token` if you do not want to enter a token.

## Data sources

| Source | Role |
| --- | --- |
| Supplied London planning CSV, 2022–2025 | Historical descriptions, decisions and coordinates |
| [GLA Planning Local Plan Data](https://data.london.gov.uk/dataset/planning-local-plan-data-2zjmn) | Public ArcGIS spatial layers |
| [Planning Data](https://www.planning.data.gov.uk/) | Administrative boundaries and optional constraint queries |
| Official council webpages/PDFs and selected London Plan chapters | Proposal-relevant policy passages |
| [Postcodes.io](https://postcodes.io/) and [OpenStreetMap](https://www.openstreetmap.org/copyright) | Postcode lookup, address search and basemap |

The implementation queries public spatial services without downloading all GeoPackages. Exact council sources are listed in [sitewise/policy_sources.py](sitewise/policy_sources.py).

## Previous project credits

- **[0-the-spike](https://github.com/house-london/0-the-spike):** adapted the comparable-application retrieval approach to the supplied CSV.
- **[ConfidentPlanner](https://github.com/athuler/ConfidentPlanner):** implementation reference for spatial checks and nearby applications.
- **[0-RIBS](https://github.com/house-london/0-RIBS):** implementation reference for validation and caching.

Reference-only concepts are independently implemented where licensing prevents copying. The MVP does not import legacy approval models, restricted datasets or hard-coded credentials. See [LEGACY_REUSE.md](LEGACY_REUSE.md).

## Development

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
```

- `sitewise/`: retrieval, spatial checks, policy extraction, explanations and Flask API.
- `web/`: map dashboard.
- `scripts/`: launchers and data/source diagnostics.
- `tests/`: automated tests.

Council sources and spatial integration live in `sitewise/policy_sources.py`, `sitewise/policies.py` and `sitewise/arcgis.py`. Local datasets, caches, cloned references and generated presentation outputs stay outside version control.

## Limitations

Source coverage and currency vary. No result does not establish that a constraint is absent. A point intersection is not a full plot or tree-root assessment, and an administrative boundary does not resolve every special planning authority.

Historical outcomes and similarity scores do not predict permission. AI citation checks verify reference IDs, not the correctness of every claim. Confirm current council requirements and seek professional advice before making planning or investment decisions.

This is a local, unauthenticated hackathon demo, not a production service or a substitute for a planning decision.
