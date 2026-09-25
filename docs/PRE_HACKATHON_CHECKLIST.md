# CityPulse — Pre-Hackathon Checklist (Free-Tier Workflow)

Everything below uses free tiers. Check items off as you complete them.
Items marked *(verified)* were already confirmed on this machine.

## 1. Local toolchain

- [x] Python 3.11+ installed — *verified: 3.14.6*
- [x] Node.js 20+ installed — *verified: 24.21.0*
- [x] Git installed — *verified: 2.54.0 (Windows)*
- [x] VS Code with Python extension; open the project root folder
- [ ] VS Code workspace settings: select `.venv\Scripts\python.exe` as interpreter

## 2. Python environment (verified commands)

```powershell
python -m venv .venv                       # [x] done (verified)
.\.venv\Scripts\Activate.ps1               # [x] works
pip install -r requirements.txt            # [x] done (verified)
python app.py                              # [x] Flask boots on 127.0.0.1:5000
```

- [x] `pytest` — 12/12 passing (verified)

## 3. Frontend environment (verified commands)

```powershell
cd frontend
npm install                                # [x] done
npm run dev                                # [x] dashboard on http://localhost:5173
npm test                                   # [x] vitest 4/4 passing
npm run build                              # [x] production build green
```

## 4. Git & GitHub

- [x] `.gitignore` excludes `.env`, `.venv/`, `node_modules/`, `dist/`, `__pycache__/`
- [x] `git init` run in project root
- [ ] `git remote add origin https://github.com/yashvardhan2797-eng/CityPluse.git`
- [ ] First commit + `git push -u origin main` (run yourself; never auto-pushed)
- [ ] Before pushing: `git status` must NOT list `.env`

## 5. Supabase (free tier)

- [x] Project exists: `kuxkfgndowdymmggydbw` (owner-created)
- [x] `civic_data` table + indexes created via `python scripts\setup_db.py` (verified)
- [x] Sample rows seeded (verified: 20 rows across 3 cities)
- [ ] Optional hardening in Supabase dashboard:
  - [ ] Database → Backups awareness (free tier has no PITR)
  - [ ] Note the project **region** (this project: ap-northeast-2 / Seoul)
- [ ] If the project shows as paused (free tier auto-pauses after ~1 week idle):
      restore it in the dashboard, then re-run `scripts/setup_db.py`

**Connection facts (verified on this machine):**
- Direct `db.<ref>.supabase.co:5432` = IPv6-only → fails on this campus network
- Session pooler `aws-0-<region>.pooler.supabase.com:5432` = IPv4 → works; use this
- Password special characters must be URL-encoded (`@` → `%40`)

## 6. API keys for later phases (obtain now, integrate later)

| Service    | Free tier                        | How to get it                        | Quotas to note                        |
| ---------- | -------------------------------- | ------------------------------------ | ------------------------------------- |
| OpenAQ     | Free API key required            | https://openaq.org/developers → sign up → dashboard → API key | Rate-limited per key; check headers |
| Open-Meteo | Free, **no key needed**          | Nothing to do — just call the documented URL | ~10k req/day non-commercial (check docs) |
| GTFS-RT    | Varies by transit agency         | Identify agency feed URL + license   | Many agencies poll every 10–30s; be polite |
| 311 / city open data | Varies (Socrata etc.)  | City open-data portal → dataset → API docs | Often 1k–10k req/day unauthenticated |

- [ ] OpenAQ key obtained → put in `.env` as `OPENAQ_API_KEY` (backend-only)
- [ ] Open-Meteo tested (no key):
      `curl "https://api.open-meteo.com/v1/forecast?latitude=12.97&longitude=77.59&current=temperature_2m"`
- [ ] Candidate GTFS-RT feed identified for your demo city (URL + license noted)
- [ ] Candidate city incidents dataset identified (URL + license noted)

> Do not put any of these keys in frontend code or commit them. Backend `.env` only.

## 7. Security sweep (before every push)

- [ ] `git status` shows no `.env`
- [ ] `.env.example` contains placeholders only (no real passwords/keys)
- [ ] No keys in `frontend/` (search: `grep -ri "sb_publishable\|apikey\|password" frontend/src`)
- [ ] DB password not pasted into README, issues, or chat screenshots

## 8. Demo-day runbook (5 minutes before presenting)

1. Terminal 1: `.\.venv\Scripts\Activate.ps1 && python app.py`
2. Terminal 2: `cd frontend && npm run dev`
3. Open http://localhost:5173 — verify: map tiles load, markers render, "LIVE DB (SAMPLE)" chip shows
4. If Supabase is unreachable: dashboard auto-falls back to DEMO mode (amber chip) — presentation still works
5. Keep a second browser tab open on `/api/health` to show the API live

## Known limitations (documented, by design)

- All Phase 1 metrics are synthetic; the UI labels this everywhere.
- Demo mode timestamps are generated per request (look fresh, are synthetic).
- Free-tier Supabase projects pause when idle; first request after restore may be slow.
- Campus DNS intermittently fails lookups (observed during development); retry or use the pooler host.
