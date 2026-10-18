# Assignment 7.1 — Evidence / Deliverables Checklist

| Requirement | Source/evidence |
|---|---|
| Flask app, current value, history, timestamp, status, health | `app.py`, `templates/dashboard.html`, `static/dashboard.css`, `evidence/dashboard_running.png`, `evidence/historical_view.png` |
| SQLite Module 6 history and preserved raw/accepted/status/timestamps | `data/module6_sensor_history.db`, `data/module6_sample_sensor_history.csv`, `src/storage.py`, `scripts/seed_history.py` |
| Automatic app restart, OS startup option | `supervisor.py`, `scripts/monitor7.service.example`, GitHub Actions recovery test |
| Threshold alert and noise control | `src/alerting.py`, `evidence/alert_active.png`, `evidence/alert_cleared.png` |
| Stale/missing input | `src/health.py`, `src/watchdog.py`, `evidence/missing_input.png`, `evidence/stale_input.png`, `evidence/failed_input.png` |
| Structured logging and application errors | `src/eventlog.py`, `evidence/application_logs.jsonl`, `evidence/application_events.csv` |
| HEALTHY / DEGRADED / FAILED / RECOVERING | `src/health.py`, status API, dashboard screenshots |
| Controlled SIGKILL restart; dashboard recovery; DB persistence | `scripts/recovery_test.py`, `evidence/recovery_test.json`, `evidence/final_healthy.png` |
| Unit, SQLite, endpoint and recovery tests | `tests/`, `.github/workflows/tests.yml` |
| README and AI disclosure | `README.md`, `AI_LOG.md` |
| Public GitHub repository | https://github.com/Barquito0/Module-7_1 |

**Evidence policy:** All screenshots must come from a running Flask web server. Evidence files should be committed only after real GitHub Actions recovery succeeds. The demo-specific threshold and missing-value stimuli must retain the `TEST_INJECTED` provenance label.
