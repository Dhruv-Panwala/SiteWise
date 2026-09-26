# Council-policy retrieval and explanations

## Contract

1. Validate UK coordinates. Query the public Planning Data `local-authority-district`
   dataset and verify the returned polygon locally with Shapely. No nearest-postcode
   guess or neighbouring planning application establishes the council.
2. Match proposal topics (extension, new homes, conversion, demolition, roof, trees)
   to reviewed official sources in `sitewise/policy_sources.py`. This is a small
   maintained registry, not general web search or a UK-wide legal database.
3. Fetch matching council HTML/PDF and selected London Plan chapters. Keep only relevant
   passages. PDFs use physical page numbers and geometry-aware word extraction.
   Missing selectors fail closed. No source text means no policy claim/action.
4. Return `council_policy`: authority resolution, topics, items, errors and coverage
   limitations. Each item has a stable-within-screen ID, extract, suggestion, document
   status, official URL, PDF page if applicable, retrieval timestamp and live/cache flag.
5. Attach deterministic policy suggestions before any LLM call. Keep full evidence in
   the dashboard; do not send the entire dataset or layer inventory to the provider.
6. `/api/analyze` returns an opaque `evidence_id`. `/api/explain` accepts that ID only;
   the server uses its own saved evidence. The browser cannot submit invented context.

## Coverage and interpretation

- Wandsworth: Housing SPD rear-extension guidance; council Local Plan explanation of
  LP27 and LP55/56; current application-page contribution and submission information.
  The 2016 SPD references superseded policies: show that warning and consult the 2023
  Local Plan plus 2026 partial review. Do not derive current numerical rules from it.
- Westminster: householder validation guidance on daylight and sustainable design.
  This is not a replacement for the full-application checklist for new dwellings.
- Lambeth: adopted 2023 Design Guide Part 4 rear/wrap-around extension guidance.
- London: selected D6 housing standards and G7 tree-retention text, only where a
  verified administrative district has a London borough ONS code (E09).
- No borough-specific rules are borrowed for an unsupported council. No special LPA,
  neighbourhood-plan, site allocation or amendment completeness claim is made.
- General policies do not establish site constraints. Historic decisions do not
  establish refusal reasons, successful redesigns or present-day permission prospects.

## Fetching and cache

No API keys are needed for policy text or boundary lookup. Requests are limited to
the explicit official-host allowlist, HTTPS and port 443; redirects are rechecked.
Downloads are capped at 16 MiB, three workers, with the existing request timeout.
Only selected PDF pages are extracted. Cached text lives in `data/cache/council_policy`,
uses `CACHE_TTL_SECONDS`, retains the original retrieval date and is not served stale
after a failed refresh. A changed page can require a registry-selector update.

No document is executed and external pages cannot provide instructions to the system.
Extracted text and proposals are delimited as untrusted data in the prompt.

## Explanation prompting

- Role/task, evidence boundary, explicit prohibited claims and one output-form example.
- Proposal -> evidence -> practical design option, not a generic inventory.
- Distinguish borough/London guidance, older SPDs, current-unverified and historical
  constraints. No made-up measurements, tree species or approval probabilities.
- Compact field selection and a hard character budget including system instructions.
  Budget is characters, not a provider token count; provider context support may vary.
- Preserve guardrails on the smaller retry. Only one retry for a provider BadRequest;
  do not pretend a retry diagnoses the provider error or guarantees model availability.
- Validate cited IDs against the actual compact context and require a policy citation
  when policy text was sent. This is NOT a factual/legal correctness validator.
- Render output as text, with trusted evidence source links separately. No model HTML.

## Configuration and running

`.env` is neither read nor written by the web demo or public-source diagnostic.
Update `.env.example` as documentation; configure the demo using process environment.
The web demo enables council lookup and asks for AI after retrieval by default.
`ENABLE_LLM_REPORTS=false` disables report calls. `ENABLE_COUNCIL_POLICIES=true` enables
the connector for CLI evidence generation; the web demo always enables it.
`ENABLE_LIVE_CONSTRAINTS=true` independently enables national spatial queries. A policy
lookup does not turn that switch on. The GLA checkbox remains independent as well.

Use `python scripts/run_demo.py --prompt-hf-token` for a hidden, process-only token
prompt. Do not paste the token into the frontend. No token was accessed during development.
AI-provider success needs a token with inference permissions, model/provider support
and any required provider credits. Deterministic policy evidence works without a token.
