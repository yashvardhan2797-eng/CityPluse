# CityPulse — Five-Minute Hackathon Demo

A repeatable, rehearsed walkthrough. Every step is verified working in this build.
Runs entirely in demo/sandbox mode if no API keys are configured — no external
dependencies beyond OpenStreetMap tiles (and Open-Meteo when internet is available).

## Before you present (2 minutes)

```powershell
# terminal 1 — backend
.\.venv\Scripts\Activate.ps1
python app.py                      # → http://127.0.0.1:5000  (health: /health)

# terminal 2 — frontend
cd frontend
npm run dev                        # → http://127.0.0.1:5173
```

Pre-flight checks (30 s):

```powershell
curl http://127.0.0.1:5000/health          # expect "status": "ok" or "degraded"
curl http://127.0.0.1:5173 -o NUL -w "%{http_code}"   # expect 200
```

If `/health` shows `"status": "degraded"` the dashboard still works — say so; it is honest
source-health reporting, not a broken app. Open `http://127.0.0.1:5173` in the browser.

## The sequence (5 minutes)

### 0:00 — Frame the problem (talking, no clicking)
"CityPulse turns scattered civic data streams into one honest command center. Everything you
will see is grounded in stored observations — the app never invents a number, never presents a
correlation as a cause, and never dresses synthetic data up as live city measurements."

Point at the provenance labels: the header badge (**LIVE DB (SAMPLE)**), the **SIM** chips on
KPI cards, and the map legend separating **live** vs **simulated** markers.

### 0:45 — Map + records integration
Click any record row in **Latest Records** — the map pans/zooms and the marker is focused.
Click a different marker — the row highlights. One dataset drives both views.

### 1:30 — Data layers + time window
Switch the layer filter to **Air Quality**, then the window to **72h**. KPIs, records, and the
severity chart all re-query with the same filters — one consistent source of truth.

### 2:15 — Explainable anomaly detection
In **Anomaly Watch**, press **Run detection**. Explain: robust z-score
(0.6745·(x−median)/MAD) against a rolling baseline; each card shows observed vs baseline,
deviation, sample size, and an explicit limitations note. "It flags *unusual*, it does not
claim *dangerous*."

### 3:00 — Alert center (evidence + dedup)
In **Alert Center**, acknowledge an alert, then dismiss another. Point out deduplication
("the same event never appears twice"), the evidence block, and the caption: *informational
civic observations — not official emergency warnings*. These persist in Supabase.

### 3:40 — Grounded AI companion
In **Civic Companion**, click the suggested question **What is the PM2.5 right now?**
The answer quotes a stored observation with timestamp, shows `answered_by`
(deterministic evidence retriever when no LLM key is set), and carries the disclaimer.
"Try to get it to invent a number — it won't; output is validated against evidence."

### 4:15 — Historical replay + location comparison
In **Historical Replay**, switch **1d → 7d**. Gaps stay gaps — "we never interpolate or
zero-fill missing hours." In **Location Comparison**, filter by **PM2.5** and point at the
coverage bars and `n=` sample sizes: "locations differ in coverage; no ranking is implied."

### 4:45 — Source health + honest status
**Data Sources & Refresh** shows per-provider mode (LIVE for Open-Meteo, SIMULATED for the
rest until keys are configured) and the cooldown-limited manual refresh. If any provider is
failing right now, the `/health` probe says so — "the dashboard cannot show a fake all-green."

### 5:00 — Phase 9: the differentiators (if time allows)

**Digital Twin tab.** Zones are real observed locations, not invented polygons — green markers
have no flags nearby. Click a flagged zone: the inspector shows recent-vs-previous deltas
("delay ▲ 2.4% vs the prior 24h — computed from stored rows only, gaps disclosed") and its
anomaly flags. Click a flag: the **Impact Engine** brief appears — same-hour co-flags, nearby
zones by haversine distance, then baseline vs simulated with the formula printed under every
number ("headway increase: +6.0 min wait, −0.18 crowding index — advisory only, nothing dispatched").

**Scenario Lab.** Run **Traffic diversion** at 30%. Every number shows its formula
(`length/base_speed*60*(1+share*0.6)`), the SIMULATED banner is unmissable, trade-offs are
explicit, and identical inputs reproduce identical outputs.

**Intelligence tab.** The association graph connects metrics flagged within 2h of each other
(amber), correlated pairs (cyan), co-located observations (violet), and hypothesis edges
(pink dashed = co-occurrence + spatial overlap, "review lead, not a cause"). Click any edge:
the evidence panel shows the measurements, sample sizes, provenance, and limitations.
"Correlation, association, hypothesis — labeled separately; causation is never claimed."

**Resilience indicator.** Four components — stress (reuses the health model), anomaly burden,
recovery (real resolution times), data coverage — each with its formula printed in the UI.
Missing data drops the component and renormalizes the weights; the disclaimer says it is a
prototype, not a validated index.

**Operations Copilot.** Ask "How resilient is the city right now?" — tool chips show which
validated read-only tools ran (resilience score), and the answer quotes only their output.
"There is no SQL path to the model and no way to write to the database through this panel."

Close: "This is the architecture judges can verify: provenance labels, parameterized SQL,
bounded queries, tested analytics, and a deterministic AI fallback — plus a Phase 9
intelligence layer where every simulated number is labeled and every association is
distinguished from causation. Deployable as two free-tier services."

## If something fails live in Phase 9

- **No anomalies stored** → impact engine honestly reports `no_anomaly`; run detection first.
- **Single-site data** → no co-location/hypothesis edges; graph shows co-occurrence only.
- **Scenario 400** → unknown/invalid params are rejected with the reason in the message —
  that is the validation working, demo it deliberately.
- **Copilot out-of-scope question** → it names what it can answer instead of inventing.


## If something fails live

- **Backend down** → the header shows an API OFFLINE banner; restart `python app.py`.
- **DB unreachable** → app degrades to clearly-labeled demo mode (`mode: demo`).
- **Provider fails** → its source card flips to SIMULATED/failed; the rest keep working.
- **Companion LLM quota exceeded** → deterministic fallback answers; `answered_by` shows it.
- **Refresh 429** → cooldown active; wait ~2 min or demo the analytics panels instead.
