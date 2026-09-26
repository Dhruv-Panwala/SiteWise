# GLA Local Plan retrieval

Source: [GLA dataset and named service registry](https://data.london.gov.uk/dataset/planning-local-plan-data-2zjmn).
Spatial query contract: [Esri Feature Layer Query](https://developers.arcgis.com/rest/services-reference/enterprise/query-feature-service-layer/).
Dataset licence: Open Government Licence v3.0; attribution: Greater London Authority / GLA GIS and source boroughs.

## Run

Install project requirements (the new dependency is `pyproj>=3.6`). Then:

```powershell
.\.venv\Scripts\python.exe scripts/check_gla.py --lat 51.5074 --lon -0.1278 --authority Westminster
```

This diagnostic uses defaults and command arguments only. It never loads `.env`.
Omit `--authority` for automatic candidate-service selection across all 35 services,
including LLDC and OPDC. Specifying a borough intentionally limits coverage to that
one service. `--refresh` bypasses cached responses. Output is JSON with no LLM calls.

The full MVP supports `--gla --no-llm --no-env-file` to enable the connector while
skipping both report generation and environment-file loading.

## Retrieval and cleaning

1. Reject missing/non-finite/out-of-UK coordinates before network calls.
2. Fetch service inventories. For automatic routing, transform WGS84 coordinates
   to each service extent's CRS using pyproj; unknown extents remain candidates.
   Extents select services but do not establish borough membership.
3. Fetch bulk layer schemas and extents using `/FeatureServer/layers`; fall back
   to individual metadata if unavailable. Skip feature queries outside each layer's
   published extent. Discover polygon layers and object ID fields. Non-polygon layers are explicitly
   unsupported for this point-screening operation; proximity retrieval is future work.
4. Query intersecting object IDs using `esriSpatialRelIntersects`, `inSR=4326`.
5. Fetch those IDs in batches within the service limit, requesting GeoJSON with
   `outSR=4326`. Detect incomplete batches and ArcGIS errors even under HTTP 200.
6. Verify every geometry locally with Shapely, including polygon holes and edges.
   Missing/invalid geometry creates a coverage warning, never a confirmed constraint.
7. Normalize blanks/nulls, whitespace and HTML. Retain names, references, designation,
   authority, classification, source notes, policy links, dates and record status.
   Remove empty GIS fields, redundant coordinate/area values and geometry from findings.
8. Combine identical attributes and geometry in the same layer, retaining all object
   IDs and duplicate counts. Differing attributes or polygons remain separate records.
9. Preserve exact record/layer/query URLs, source retrieval time and cache status.
   Cache metadata and raw spatial responses for one day under `data/cache/arcgis_local_plan`.
   Expired cache is not used as current evidence after a failed refresh.

## Output semantics

- `findings`: verified point intersections. `confirmed` refers to geometry only;
  `current=null` means legal currency is unverified. Records marked removed/revoked
  are labelled `historical` with `current=false`.
- `layers`: one query/availability result per discovered layer, with warnings and counts.
- `services`: routing results and metadata retrieval provenance.
- `coverage_gaps`: missing/failed/no-match conservation, tree, flood and other checks.
- `complete`: all selected layers queried successfully; it does not guarantee all
  real-world constraints have been published. `partial`: at least one source/layer
  failed, was unsupported or could not be fully checked.

Layer edit time is not a designation date. Missing source dates remain null. Fetching
today does not establish that the published local plan is current. Local-plan themes
such as opportunity areas are planning context, not automatically legal prohibitions.

`EvidenceService` adds matches to `planning_constraints`, includes a `local_plan`
audit object, and adds GLA provenance and coverage warnings to `sources`/`data_quality`.
The national Planning Data source remains separately attributed, so its disabled or
unknown state does not erase a GLA match.

## Boundaries of this integration

This is London-only point screening. It does not yet screen an entire site polygon,
buffer nearby trees/buildings/roads, retrieve planning policy documents, resolve land
ownership, or guarantee borough TPO coverage. Those require further connectors/checks.

## Live verification examples

During implementation, `(51.5074, -0.1278)` queried against Westminster returned
Trafalgar Square Conservation Area and four local-plan designations across 18 layers.
Two identical conservation records were combined, preserving both object IDs.
`(51.4900, -0.1200)` in the Lambeth service returned Albert Embankment Conservation
Area, Flood Risk Zone 3 and local-plan designations. The returned Flood Zone 2
geometry failed validity checks and is explicitly reported as a partial check.
Neither of these service inventories included a tree-preservation layer.
These examples verify published-layer retrieval, not legal status or site suitability.
