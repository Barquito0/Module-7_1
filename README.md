# EGN 321 — Module 7.1: Unattended Sensor Monitoring

**Flask dashboard · SQLite Module 6 history · persistent alerts · stale detection · automatic restart · recovery evidence**

> GitHub: https://github.com/Barquito0/Module-7_1  
> Previous verified history project: https://github.com/Barquito0/EGN-321-Module-6_1  
> Instructor example used for requirements/reference only: https://github.com/ivansuarez-AU/EGN321_Module7_Assignment7_1

## System architecture

```text
                    Module 6 original CSV / SQLite archive
                                      |
                    Source-preserving replay worker (2 s default)
                                      |
                  Format + sensor status + range validation
                                      |
           SQLite readings + monitor_meta + monitor_events
                                      |
               Persistent alert engine (3 highs / 2 clears)
                                      |
                   Independent freshness watchdog
                                      |
                     Flask HTML / JSON dashboard
                                      |
                   Rotating JSONL event audit log

       systemd (optional) -> supervisor.py -> Flask app.py
                                   |         (SIGKILL -> restart)
                         SQLite survives; replay cursor resumes
```

## Running locally

Python 3.11+ recommended. Open a terminal in the repository root:

```bash
python -m pip install -r requirements.txt
python -m pytest -q
python supervisor.py
```

Visit **http://127.0.0.1:5000**. The process supervisor launches Flask, waits for its exit, logs the exit, and automatically restarts it. No second manual command is needed after a child-process crash.

For a direct one-process classroom run (no restart supervision), use `python app.py` instead. The threaded Flask development server is local classroom software, not a hardened public deployment. It binds to 127.0.0.1 by default. **Do not expose the service to the Internet without a production WSGI server, authentication, TLS, and host controls.**

### Unattended startup at operating-system boot (Linux)

The optional `scripts/monitor7.service.example` launches `supervisor.py`. Edit the username, absolute working-directory path, and Python executable path, copy it to `/etc/systemd/system/egn321-module7.service`, then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now egn321-module7.service
sudo systemctl status egn321-module7.service
```

`Restart=always` in systemd also recovers the supervisor if *the supervisor itself* exits. This service file is a **provided configuration example**, not a claim that systemd was installed on your computer. The verified classroom recovery exercise uses the included Python supervisor under GitHub Actions Linux.

## Sensor and input source

- Original data: `data/module6_sample_sensor_history.csv` from Assignment 6.1 (instructor-provided simulated data); **1,756 timestamped source rows** containing **five sensors**: temperature (°C), humidity (%), light (raw), distance (cm), and potentiometer (%).
- Original database snapshot: `data/module6_sensor_history.db`, with **8,780 individual readings** in the unchanged Module 6 `readings` schema. The file is kept as a read-only seed; it is copied to `state/monitor.db` only on **first** boot.
- A reproducible seed builder is also supplied in `scripts/seed_history.py` if the binary seed is unavailable. Run `python -m scripts.seed_history` in an environment where the seed is absent. The builder refuses to overwrite an existing seed.
- Monitoring sensor: the **temperature** column from that source. The other four sensors remain queryable in the SQLite archive.
- The database preserves all original source timestamps exactly, including the two recording gaps: 25 missing minute slots (Oct 1, 13:09–13:35) and 20 missing slots (Oct 2, 05:59–06:20). No data are inserted into either gap.
- For a live unattended classroom demonstration, original rows are **replayed as arrivals** with a separate current UTC `captured_at_utc` timestamp. The original `source_timestamp` and `source_sample_number` remain attached to every replay row. Source timestamps have **unspecified timezone** and are **not** treated as current.
- `origin=MODULE6_SOURCE_REPLAY` identifies genuine replayed source rows. `origin=TEST_INJECTED` identifies deliberate classroom alert/failure stimuli. Test-injected rows **are not presented as actual sensor measurements**.

## Expected sample interval, freshness and gaps

Two different clocks must be kept separate:

| Layer | Expected interval | Time field | Meaning |
|---|---:|---|---|
| Original Module 6 archive | **60 seconds** | `timestamp` (original) | Historical observation time, timezone unspecified |
| Module 7 replay feed | **2 seconds** by default | `captured_at_utc` | Actual arrival time for monitoring freshness |

The `state/monitor.db` contains both: original archive records have `captured_at_utc = NULL`, while new replay records include both times and an explicit origin. The web client supports separate **Replay** and **Original Archive** plots; it does not connect them into one invented continuous sensor record. The archive chart breaks lines when adjacent source timestamps are separated by >90 seconds, and also breaks lines for rejected samples. In the replay chart the plotted line breaks for rejected/missing values and for time gaps >3x the replay interval, with a minimum threshold of four seconds.

Freshness uses **only replay arrival time**:

- **HEALTHY:** latest replay input is accepted and arrived at most 8 seconds ago, with no active high alert.
- **DEGRADED:** latest input is missing/rejected, a high alert is active, or the most recent arrival is **more than 8 seconds** old.
- **FAILED:** no replay data has arrived for **more than 18 seconds**. The health endpoint returns HTTP 503 in this case.
- **RECOVERING:** the process is starting, and no replay input has arrived yet. Startup and restart are recorded in SQLite and JSONL.

The thresholds are classroom defaults; set `STALE_DEGRADED_SECONDS` and `STALE_FAILED_SECONDS` in the environment to adjust. **The dashboard shows an em dash rather than stale data as a current accepted reading.** The source timestamp remains visible solely for provenance.

## Validation and threshold alert

Each replayed temperature is validated before being accepted:

- Missing or nonnumeric input -> `MISSING` / `INVALID`, `decision=REJECTED`, `accepted_value=NULL`.
- Non-finite input -> `INVALID`, rejected.
- Original source status other than `OK` -> rejected **without changing the raw reading**.
- Temperature outside the documented 0–50 °C classroom acceptance band -> `OUT_OF_RANGE`, rejected.
- Accepted finite 0–50 °C temperature -> `decision=ACCEPTED` and stored separately from raw.

**Alert trigger:** 3 **consecutive accepted** readings **≥ 30.0 °C**. A single spike never triggers the threshold alert. Invalid/missing input resets the candidate streak but does not silently clear an existing alert. **Hysteresis + persistence when clearing:** 2 consecutive accepted readings **≤ 28.5 °C** clear an existing high-temperature alert. The alert's state and streaks are persisted in the SQLite `monitor_meta` table and survive application restart. Transitions emit `ALERT_ACTIVATED` and `ALERT_CLEARED` audit events.

The original Module 6 temperature series generally remains near 19–25 °C and does not naturally trip the classroom high-temperature threshold. For **controlled alert/missing evidence**, the workflow uses `CLASSROOM_DEMO=1`, which inserts clearly labeled `TEST_INJECTED` high-temperature and missing values among actual Module 6 replay rows. These are **test stimuli**, not observations by a real instrument. Default `CLASSROOM_DEMO=0` does **not** inject values.

## Logging, SQLite, and health

### Files

- `data/module6_sensor_history.db`: unchanged Module 6 seed snapshot. **Never overwritten by a process restart.**
- `state/monitor.db`: live working SQLite copy; retains archive + appended replay rows, alert metadata and events; excluded from git to avoid committing ephemeral state.
- `logs/monitor.jsonl`: rotating line-delimited JSON events with UTC time, level, event and PID. Rotation size 3 MB, three backups.
- `monitor_events`: SQLite table that persistently records operational state changes.
- `evidence/`: real screenshots, test-run logs, process-kill details, and event exports generated by a successful recovery exercise.

### Events recorded

`STARTUP`, `READING_ACCEPTED`, `READING_REJECTED`, `ALERT_ACTIVATED`, `ALERT_CLEARED`, `MISSING_INPUT`, `STALE_INPUT`, `INPUT_FAILED`, `HEALTH_RECOVERED`, `RECOVERING`, `PROCESS_EXITED`, `RESTART_SCHEDULED`, `APPLICATION_ERROR`. The watchdog records transitions only once per change rather than spamming the log on every check. An application exception is logged both in the request handler and the worker exception handler.

### HTTP paths

| Endpoint | Purpose |
|---|---|
| `/` | Responsive live HTML dashboard |
| `/api/status` | Current temperature, latest source + arrival timestamps, sensor status, alert and health |
| `/api/history?mode=replay&limit=200` | Replayed accepted/raw sensor values |
| `/api/history?mode=archive&limit=5000` | Original, unmodified Module 6 historical values with gaps |
| `/api/events` | Last 40 operational events |
| `/healthz` | HTTP 200 for operational/recovering states, 503 for failed input |

## Controlled interruption / recovery evidence

Automated Linux/CI test:

```bash
python scripts/recovery_test.py
```

It starts `supervisor.py`, opens the real Flask web server, checks history, captures screenshots in a real headless Chrome browser, exercises **3-sample alert activation**, **missing input**, **2-sample clearing**, pauses the feed to demonstrate stale/failed input, unpauses and verifies normal health, then **sends SIGKILL to Flask's child PID**. It checks that the supervisor launches a **different PID**, that the dashboard returns, that existing SQLite row count never decreases, and that the system returns to HEALTHY. Relevant audit events must exist; otherwise the test fails. Test results and screenshots are stored under `evidence/` and automatically committed by the GitHub workflow **only on success**.

For manual classroom testing (running `python supervisor.py`):

```bash
# Terminal 2: pause replay arrivals; wait >8 seconds for DEGRADED and >18 for FAILED
python -c "from pathlib import Path; Path('state/pause.flag').touch()"
# Then resume input, letting health recover automatically
python -c "from pathlib import Path; Path('state/pause.flag').unlink(missing_ok=True)"
```

`pause.flag` is a test-control mechanism, not a fabricated sensor sample; it stops arrivals so the actual freshness monitor can detect the silence.

**Screenshots from the CI recovery run are authentic browser captures**, not mockups or screenshots of JSON returned by a test client. The `evidence/recovery_test.json` includes actual PID changes and SQLite counts. If the workflow fails, do not claim recovery evidence was verified.

## Known limitations and manual intervention

- The feed is **deterministic classroom replay**, not an independently operating physical temperature sensor. Demo values are explicitly labeled.
- Replaying a finite CSV on a loop is intended to test unattended processing, not to assert that a new physical measurement occurred. Original source timestamps remain historical.
- SQLite does not prove a missing sensor interval had any particular temperature; no interpolation is used.
- The timestamp time zone for the instructor CSV is unknown. Replay arrivals use UTC.
- The thresholds, sample interval, temperature acceptance range, and alert levels are teaching policies, not a calibrated safety device.
- Crash/restart of the **application process** is automatically handled by the Python supervisor; optional systemd handles a supervisor crash/reboot when configured. An entire host power outage is **not** automatically solved without OS-managed restart.
- Severe database corruption, inaccessible files, exhausted disk, endless crashes, a down host, absent feed requiring investigation, and production network hardening require **human intervention**. No alarm emails/SMS are sent; alerts are dashboard/log based.
- A native Flask development server is appropriate for a **local educational demonstration only**, not public-facing deployment.

## Automated tests

```bash
python -m pytest -q
```

Unit tests verify persistence/hysteresis, SQLite copy integrity, accepted-vs-raw traceability, missing data, health timeouts, watchdog state changes and recovery of replay cursor. Additional Flask endpoint tests run when Flask is installed. The GitHub Actions workflow also runs the complete **real process interruption test** with browser screenshots and an evidence commit.

## Student submission checklist

See `EVIDENCE_CHECKLIST.md` and `evidence/` for all deliverables. GitHub link: **https://github.com/Barquito0/Module-7_1**.
