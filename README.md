# CityPulse — Civic Command Center

CityPulse is a civic intelligence dashboard: it ingests civic data (weather, air quality, transit,
incidents), normalizes and stores it, visualizes it on an interactive map with KPIs and charts,
detects statistical anomalies, computes metric correlations, and produces plain-language summaries.

**Current status: Phases 1–4 complete (integration-hardened).** Live ingestion is verified for Open-Meteo (keyless);
OpenAQ/GTFS-RT/Socrata providers are implemented and activate as soon as their credentials/URLs
are set in `.env` — until then each falls back to clearly-labeled synthetic data. Nothing
synthetic is ever presented as an official measurement.

---

## Tech Stack

| Layer      | Technology                                              |
| ---------- | ------------------------------------------------------- |
| Frontend   | React 19 + TypeScript + Vite, Tailwind CSS, Framer Motion |
| Map        | React-Leaflet + OpenStreetMap tiles                     |
| Charts     | Recharts                                                |
| Backend    | Python Flask (application factory) + flask-cors          |
| Database   | Supabase PostgreSQL (via psycopg 3)                     |
| Ingestion  | requests (Open-Meteo, OpenAQ v3, GTFS-RT protobuf, Socrata) |
| Analytics  | Explainable robust z-score anomalies · Pearson/Spearman correlations |
| AI summary | OpenAI-compatible endpoint (optional) + deterministic grounded fallback |
| Config     | python-dotenv (`.env`, backend-only secrets)            |
| Tests      | pytest (backend) · vitest (frontend)                    |

---

## Project Structure

```
CityPulse/
├── app.py                    # Flask entrypoint (python app.py)
├── requirements.txt          # Python dependencies
├── .env                      # Local secrets (git-ignored — never commit)
├── .env.example              # Placeholder template (safe to commit)
├── backend/
│   ├── app_factory.py        # App factory: blueprint, CORS, JSON 404s
│   ├── config.py             # Settings loaded from environment
│   ├── database.py           # psycopg helpers, schema, parameterized queries
│   ├── demo_data.py          # Clearly-labeled synthetic cities/records
│   ├── routes.py             # /api/* endpoints (Phases 1-4)
│   ├── ingest.py             # Provider orchestration, dedup/upsert, health, cooldown
│   ├── analytics.py          # Robust z-score anomaly detection (baseline + evidence)
│   ├── correlations.py       # Aligned-window Pearson/Spearman with limitations
│   ├── ai_summary.py         # Grounded AI summaries + deterministic fallback
│   ├── companion.py          # Grounded Q&A over stored evidence (Phase 3)
│   ├── events.py             # Civic event lifecycle (Phase 3)
│   ├── realtime.py           # SSE + notification bus (Phase 3)
│   ├── simulation.py         # Clearly-labeled drill scenarios (Phase 3)
│   ├── alerts.py             # Deduplicated evidence-backed alert center (Phase 4)
│   └── providers/            # weather · air_quality · transit · incidents · demo_generators
├── frontend/                 # React + TS + Vite app
│   └── src/
│       ├── App.tsx           # Dashboard shell
│       ├── api.ts            # Typed REST client (calls /api/* only)
│       ├── types.ts          # API response types
│       └── components/       # Header, CityMap, SeverityChart, RecordsFeed, ...
├── scripts/setup_db.py       # Creates civic_data + seeds sample rows
├── scripts/apply_migrations.py  # Applies scripts/migrations/*.sql in order
├── scripts/migrations/       # 001 baseline · 002 phase2 · 003 phase3 · 004 events · 005 phase4
├── tests/                    # Backend smoke + Phase 2/3 suite (mocked HTTP)
├── frontend/src/__tests__/   # vitest frontend smoke tests
└── docs/PRE_HACKATHON_CHECKLIST.md
```

---

## Quick Start (Windows PowerShell + VS Code)

### 1. Prerequisites

- Python 3.11+ (`python --version`)
- Node.js 20+ (`node --version`)
- A free Supabase project (optional — demo mode works without it)

### 2. Backend

```powershell
# from the project root, in the VS Code terminal
python -m venv .venv
.\.venv\Scripts\Activate.ps1        # if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
pip install -r requirements.txt

copy .env.example .env              # then edit .env with your own values
python scripts\setup_db.py          # creates civic_data + seeds samples (needs DATABASE_URL)
python scripts\apply_migrations.py  # adds provider/metadata columns + analytics tables
python app.py                       # → http://127.0.0.1:5000
```

### 3. Frontend (new VS Code terminal)

```powershell
cd frontend
npm install
npm run dev                         # → http://localhost:5173
```

Open http://localhost:5173 — the Vite dev server proxies `/api/*` to Flask on port 5000,
so the browser never touches the database or secrets directly.

### 4. Tests

```powershell
# backend (from project root, venv active)
pytest

# frontend
cd frontend
npm test        # vitest
npm run build   # type-checks and produces a production build
```

---

## Environment Variables

Copy `.env.example` → `.env` and fill in your own values. `.env` is git-ignored.

| Variable                    | Used by  | Purpose                                             |
| --------------------------- | -------- | --------------------------------------------------- |
| `FLASK_DEBUG`               | backend  | `1` enables debug/reload                            |
| `PORT`                      | backend  | Flask port (default 5000)                           |
| `CORS_ORIGINS`              | backend  | Allowed browser origins (comma-separated)           |
| `DATABASE_URL`              | backend  | Postgres connection string (secrets stay server-side) |
| `SUPABASE_URL`              | backend  | Project URL (kept server-side)                      |
| `SUPABASE_PUBLISHABLE_KEY`  | backend  | Publishable key (kept server-side)                  |
| `OPENAQ_API_KEY`            | backend  | OpenAQ v3 key (explore.openaq.org) — air quality when set |
| `WEATHER_ENABLED`           | backend  | `0` forces synthetic weather; Open-Meteo is keyless/on by default |
| `TRANSIT_GTFS_RT_URL`       | backend  | GTFS-Realtime VehiclePositions URL (else synthetic transit) |
| `INCIDENTS_SOCRATA_URL`     | backend  | Socrata open-data incidents URL (else synthetic incidents) |
| `INCIDENTS_FIELD_MAP`       | backend  | JSON mapping CityPulse fields → dataset columns |
| `INGEST_COOLDOWN_SECONDS`   | backend  | Minimum seconds between `/api/refresh` runs (default 120) |
| `REFRESH_TOKEN`             | backend  | Optional; when set, refresh requires `X-Refresh-Token` header |
| `AI_PROVIDER` / `AI_BASE_URL` / `AI_MODEL` / `AI_API_KEY` | backend | Optional OpenAI-compatible summary provider (fallback used when unset) |
| `ANOMALY_Z_THRESHOLD` / `ANOMALY_SEVERE_Z_THRESHOLD` | backend | Robust z-score flags (default 3.5 / 6.0) |

**Database connection notes**

- Prefer the **Session pooler** string (Supabase → Connect): works on IPv4-only networks
  (campus/office Wi-Fi). Format:
  `postgresql://postgres.<project-ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres?sslmode=require`
- The direct `db.<ref>.supabase.co:5432` host is **IPv6-only**; it fails on IPv4-only networks.
- URL-encode special characters in passwords (`@` → `%40`).

---

## Database Setup

1. Create a free project at https://supabase.com (no payment method needed).
2. Copy the session-pooler connection string into `DATABASE_URL` in `.env`.
3. Run `python scripts\setup_db.py` — it creates:

```sql
civic_data (
  id BIGSERIAL PK, source_type TEXT, source_id TEXT, city TEXT, location_name TEXT,
  latitude DOUBLE PRECISION, longitude DOUBLE PRECISION, value DOUBLE PRECISION,
  unit TEXT, description TEXT, severity CHECK IN (low|moderate|high|critical),
  recorded_at TIMESTAMPTZ, created_at TIMESTAMPTZ
)
-- indexes on source_type, recorded_at, (lat, lon), severity, city, unique (source_type, source_id)
```

4. The script seeds a few clearly-labeled "Demo:" rows for Bengaluru / Mumbai / Delhi.
5. `python scripts\apply_migrations.py` applies the incremental migrations in
   `scripts/migrations/` (provider columns, JSONB provenance, dedup keys,
   `provider_status`/`ingest_log`/`anomaly_events` tables). It is idempotent and preserves data.

If `DATABASE_URL` is missing or unreachable, the API automatically serves demo data
(`"mode": "demo"`) and the UI shows a DEMO badge — nothing crashes.

### Ingesting real data

With Flask running, trigger a refresh (rate-limited by `INGEST_COOLDOWN_SECONDS`):

```powershell
curl -X POST http://127.0.0.1:5000/api/refresh
```

- **Weather** works immediately (Open-Meteo is keyless) — verified live.
- **Air quality / transit / incidents** ingest real observations once their env vars
  above are set; otherwise deterministic synthetic rows are stored and the map marks
  them as simulated (hollow markers), while live rows are solid.
- The demo backfill stores 72h of hourly synthetic history so anomaly detection and
  correlations have enough data on first run.

Verified live row example: weather observations stored with `mode: live` and the
`source_url` provenance pointing at api.open-meteo.com.

---

## API Endpoints

| Endpoint                              | Description                              |
| ------------------------------------- | ---------------------------------------- |
| `GET /api/health`                     | Status + data mode (`database` / `demo`) |
| `GET /api/cities`                     | City list for the selector               |
| `GET /api/records?city=&source_type=&hours=` | Normalized observations (filterable) |
| `GET /api/summary?city=&hours=`       | KPIs + data-quality label (live/mixed/demo) |
| `GET /api/chart/severity?city=...`    | Severity distribution for the chart      |
| `GET /api/map?city=&layer=&hours=`    | GeoJSON-ready records for the map        |
| `GET /api/sources`                    | Per-provider health: last fetch, error, mode |
| `POST /api/refresh`                   | Rate-limited ingestion run (cooldown; optional token) |
| `GET /api/analytics/anomalies?city=&hours=` | Robust z-score anomalies with evidence |
| `GET /api/analytics/correlations?city=&hours=` | Metric-pair associations + limitations |
| `GET /api/ai/summary?city=&hours=`    | Grounded plain-language summary (or fallback) |
| `POST /api/ai/ask`                    | Civic companion Q&A, answers grounded in stored evidence |
| `GET /api/events?city=&status=`       | Civic event lifecycle (also `/events/stream` SSE, `/events/poll`) |
| `GET /api/simulation/scenarios` / `POST /api/simulation/run` | Labeled drill scenarios and runs |
| `GET /api/alerts?city=&status=`       | Deduplicated, evidence-backed alert instances |
| `POST /api/alerts/<dedup_key>/acknowledge` / `.../dismiss` | Operator state changes (404 on unknown key) |
| `GET /api/alerts/rules`               | Configured threshold rules (`ALERT_RULES_JSON` seed) |
| `GET /api/history?city=&hours=&metrics=` | Hourly replay from stored records only; gaps never filled |
| `GET /api/analytics/locations?city=&hours=` | Per-location averages with coverage + sample-size disclosure |
| `GET /api/settings`                   | Non-secret runtime settings              |
| `GET /api/analytics/impact?city=&metric=` | Impact Engine brief: related anomalies, documented estimates, advisory interventions, baseline-vs-simulated |
| `GET /api/analytics/cross-domain?city=&window_hours=` | Cross-domain association graph (co-occurrence / correlation / co-location / hypothesis) + per-edge evidence |
| `GET /api/analytics/resilience?city=&hours=` + `/trend` | Explainable resilience indicator (stress, anomaly burden, recovery, data coverage) |
| `GET /api/twin?city=&hours=`          | Urban digital twin: zone state, deltas, nearby anomalies/events, advisory hooks |
| `GET /api/scenario-lab/models` / `POST /api/scenario-lab/run` | Transparent labeled simulation models with validated params |
| `POST /api/copilot/ask`               | Operations Copilot: validated read-only tools + grounded answers (no SQL to the model) |

All responses are JSON with consistent schemas; secrets are never included in any response.
Refresh rejects unauthenticated calls when `REFRESH_TOKEN` is configured and answers `429`
inside the cooldown window.

---

## Troubleshooting

| Symptom                                        | Fix                                                                          |
| ---------------------------------------------- | ---------------------------------------------------------------------------- |
| Browser shows "API OFFLINE" banner              | Start Flask first: `python app.py` (port 5000), then refresh                  |
| `Failed to resolve host` on DB connect          | Campus DNS flakiness or IPv6-only direct host — use the session pooler URL    |
| `tenant/user ... not found` on pooler connect   | Wrong region in the pooler host — copy the exact string from Supabase → Connect |
| `password authentication failed`                | Re-check DB password; URL-encode special characters (`@` → `%40`)             |
| PowerShell blocks `Activate.ps1`                | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, then retry             |
| Map tiles missing                               | OSM tiles need internet; check firewall/proxy                                 |
| Port 5000 already in use                        | Another process owns it — stop it or set `PORT` in `.env` and update the Vite proxy |
| Global `PORT` env var overrides `.env`          | Fixed in code (`.env` wins); restart terminals after changing `.env`          |

---

## Phase 9 — Urban Intelligence (implemented)

Phase 9 turns the dashboard into an evidence-driven decision-support platform. Priority order was
impact engine → cross-domain intelligence → evidence layer, then the secondary capabilities.

| Capability | What it does | Trust guarantees |
| --- | --- | --- |
| Urban Digital Twin (`/twin`) | Zone map from real observed locations; per-zone metric deltas (recent vs previous window), nearby anomaly flags and events, advisory hooks | Zones exist only where data exists; gaps disclosed, never zero-filled |
| Impact Engine (`/analytics/impact`) | Anomaly → related anomalies (same-hour co-flags + geo proximity) → documented impact estimates → advisory interventions → baseline vs simulated compare | Every formula and coefficient is printed in the response; advisory only, nothing dispatched |
| Cross-domain intelligence (`/analytics/cross-domain`) | Graph of co-occurrence (≤2h), correlation (reuses the Phase 3 engine), co-location (haversine), and hypothesis edges with per-edge evidence panels | Edges labeled `statistical_association` or `hypothesis`; causation explicitly never claimed |
| Evidence layer | Every cross-domain edge and impact estimate carries provenance, sample sizes, assumptions, limitations | Deterministic outputs; reproducible from printed formulas |
| Scenario Lab (`/scenario-lab/*`) | Traffic diversion, rainfall disruption, air-quality stress, resource allocation models over real baselines with validated, clamped parameters | Always labeled SIMULATED; identical inputs reproduce identical outputs; unknown params rejected (400) |
| Resilience indicator (`/analytics/resilience`) | Weighted, explainable components: stress (health score), anomaly burden, recovery (event resolution times), data coverage | Component formulas shown in UI; weights renormalize over available data; disclaimer states it is not a validated index |
| Operations Copilot (`/copilot/ask`) | Six read-only tools (metric, anomalies, zones, events, scenario, resilience) with validated inputs and grounded answers | Tools are allowlisted functions; the LLM never sees SQL or credentials; deterministic fallback needs no keys |

**Phase 9 tests:** 17 new (offline logic + endpoint contracts) — backend suite 144 passing;
frontend `tsc`/`vitest`/`oxlint`/build green; all Phase 9 endpoints verified live through the Vite
proxy, including a seeded two-anomaly probe proving graph edge formation and the evidence panel
(probe rows deleted after verification).

### Known limitations (Phase 9)

- Impact/scenario coefficients are planning heuristics, not calibrated models; they are printed
  everywhere they are used.
- Anomaly footprints come from geolocated `civic_data` rows; without them, geo features degrade
  honestly to "insufficient geo data" rather than guessing locations.
- Recovery scoring needs resolved events with `reported_at` + `resolved_at`; with none, the
  component reports `no_data` and is excluded from the weighted score.
- Cross-domain hypothesis edges require both co-occurrence and spatial overlap; sparse single-site
  deployments will not produce them.

---

## Current Limitations (Phases 1–4)

- Live ingestion is **verified for Open-Meteo weather only**. Air quality, transit, and
  incidents use clearly-labeled synthetic data until `OPENAQ_API_KEY`,
  `TRANSIT_GTFS_RT_URL`, and `INCIDENTS_SOCRATA_URL` are configured (setup steps in
  `docs/PRE_HACKATHON_CHECKLIST.md`).
- Anomaly detection is an explainable robust z-score over a rolling baseline — it flags
  "unusual vs recent history", it does not explain causes. It stays silent until enough
  observations exist.
- Correlations are associations over aligned hourly aggregates with sample-size floors;
  they never imply causation (stated in the UI and API responses).
- AI summaries and companion answers are grounded strictly in supplied observations and
  analytics; numbers seen in an answer always come from the evidence, and without an AI
  provider key a deterministic template/retriever is used.
- Alert-center entries are informational observations derived from verified anomalies or
  configured thresholds (`ALERT_RULES_JSON`); they are deduplicated by construction and
  are never official emergency warnings.
- Historical replay and location comparison use only stored observations: missing hours
  render as gaps (never interpolated or zero), and each location discloses its coverage
  hours, sample sizes, and whether synthetic rows are included. No ranking is implied.
- No authentication beyond the optional refresh token; intended for local hackathon use.
- Analytics queries run against Supabase over the session pooler; large windows are slower.

## Roadmap (not implemented — extension points only)

- Predictive forecasting / ML models beyond the explainable baseline.
- Notification delivery (email/SMS) for alert-center events.
- PostGIS geographic indexing (schema leaves room for it; not required for the demo).
- Per-neighborhood analytics and multi-city comparisons.

## Deployment (free-tier guidance)

The stack deploys as two services (verified locally; platform specifics should be re-checked
against current provider docs before relying on them):

- **Backend (Flask)**: any Python host — Render / Railway / Fly.io free tiers typically work.
  Start command: `pip install -r requirements.txt && python app.py` (set `PORT`; the app reads
  it). Health check path: `/health`. Requires env vars from `.env.example` (at minimum
  `DATABASE_URL`; set `CORS_ORIGINS` to your frontend URL).
- **Frontend (React)**: static hosting — Vercel / Netlify / Cloudflare Pages. Build command
  `npm run build`, publish `dist/`. Add a rewrite/proxy so `/api/*` reaches the backend URL.
- **Database**: Supabase free tier; apply migrations with
  `python scripts/apply_migrations.py` against the pooled `DATABASE_URL`.

Manual steps we did **not** perform (no credentials/authorization): creating platform
accounts, setting production env vars, provisioning DNS, or running a production deploy.

## Security Notes

- All credentials (DB password, provider keys, AI keys) live only in the backend `.env`,
  which is git-ignored; `.env.example` contains placeholders only.
- Every database query is parameterized (psycopg `%s` placeholders); no string interpolation.
- CORS is restricted to the origins listed in `CORS_ORIGINS`; `/api/refresh` is cooldown- and
  token-limited; request bodies are capped (64 KiB → 413); error responses are JSON and never
  include stack traces.
- Verified: production bundle, frontend source, and backend logs contain no secret material
  (automated check in `tests/test_phase4_hardening.py::test_frontend_bundle_has_no_secrets`).

## Five-Minute Demo Sequence

Full scripted walkthrough with talking points: [`docs/DEMO_WALKTHROUGH.md`](docs/DEMO_WALKTHROUGH.md).

Short version (all steps verified working):
1. **0:00** — Open the dashboard (Flask :5000 + Vite :5173). Point out the map, KPIs,
   and the LIVE DB / SIM badges distinguishing provenance.
2. **1:00** — Click a map marker → record feed focuses; severity chart updates from stored data.
3. **2:00** — Run **Run detection** in Anomaly Watch; explain the robust z-score evidence card
   (baseline, deviation, sample size, limitations).
4. **3:00** — Alert Center: acknowledge/dismiss a deduplicated alert (persisted in Supabase);
   stress that alerts are informational, not emergency warnings.
5. **3:30** — Civic Companion: ask "What is the PM2.5 right now?" — answer cites evidence,
   shows `answered_by`, and refuses to invent numbers.
6. **4:00** — Historical Replay: switch 1d↔7d; gaps stay gaps (never interpolated).
   Location Comparison: filter by PM2.5; coverage + sample sizes are disclosed.
7. **4:40** — Data Sources panel: show live (Open-Meteo) vs simulated providers and the
   honest `/health` status, including any provider currently failing.

## Feature Checklist (post-Phase 4)

| Feature | Status |
| --- | --- |
| Map, KPIs, charts, city selector, records feed | ✅ implemented, verified live |
| Provider ingestion + source health + cooldown refresh | ✅ implemented (Open-Meteo live-verified) |
| Anomaly detection (robust z-score, evidence, configurable) | ✅ implemented, deterministic tests |
| Correlations (Pearson/Spearman, sample floors, limitations) | ✅ implemented, tested |
| AI summaries + companion with grounded fallback | ✅ implemented (deterministic mode live-verified; LLM path needs a key) |
| Civic events lifecycle + SSE + simulation drills | ✅ implemented, tested (UI panel: backend-ready) |
| Alert center (dedup, evidence, ack/dismiss) | ✅ implemented, verified end-to-end vs Supabase |
| Historical replay (stored-only, gaps preserved) | ✅ implemented, verified live |
| Location comparison (coverage disclosure, no ranking) | ✅ implemented, verified live |
| Error handling (timeouts, retries, JSON errors, size caps, boundary) | ✅ implemented, tested |
| Real LLM provider call | ⚠️ unverified — needs `AI_*` credentials (copilot + summary fall back deterministically) |
| Urban intelligence (twin, impact, cross-domain, scenario lab, resilience, copilot) | ✅ implemented, tested + live-verified (Phase 9) |
| Real OpenAQ / GTFS-RT / Socrata ingestion | ⚠️ unverified — needs credentials/URLs |
| Production deployment | ⚠️ not performed (guidance above) |

## License / Attribution

- Map tiles © [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors (ODbL).
- Weather © [Open-Meteo](https://open-meteo.com/) (CC BY 4.0, keyless API).
- Air quality via [OpenAQ](https://openaq.org/) (per-source licenses; key required).
- GTFS-Realtime feeds are licensed per agency — check before configuring a URL.
- Synthetic data is always labeled and must never be presented as live civic measurements.
