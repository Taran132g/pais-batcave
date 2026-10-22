# PAIS // Batcave — getpais.company

Taran's private dashboard, live at **https://getpais.company** (replaced the B2B product site 2026-09-28;
the old pages are in `~/agentic_os/pais-site/_b2b_archive`, rollback notes in `ROLLBACK.txt` there).
Four tabs: **Agents · ROI · Job · Gym**. Read-only: no agent ever runs from the site.

```
Mac (data lives here)                 Oracle 129.159.182.210 (quant-os)          Vercel
publisher/publish.py  --scp every 15m--> ~/pais-cave/data/snapshot.json
  server/sources/* (agents, yubit,       pais-cave.service :8155  <--nginx /cave/--  getpais.company/api/cave/*
  fitbit, internships) + goals.json      TOTP = ~/Automated-Trading-Bot/.env           (vercel.json rewrite)
                                         (same secret as the QUANT_OS dashboard)      pais-site/index.html + cave/
```

- **Goals:** edit `goals.json` (ROI %, job target/deadline/counts, gym weekly targets); next publish picks it up.
- **Publisher:** LaunchAgent `com.taran.pais-publish` (every 15 min), log `publish.log`. Manual: `.venv/bin/python -m publisher.publish [--dry-run]`.
- **Oracle API:** `oracle/deploy.sh` (copies `server/auth.py` into `oracle/cave/`). `systemctl status pais-cave`; nginx backup `sites-available/pais-api.bak-2026-09-28`.
- **Frontend:** `~/agentic_os/pais-site/index.html` + `cave/` → `cd ~/agentic_os/pais-site && vercel --prod --yes`. `/app` trader desk untouched.
- **Tests:** `.venv/bin/python -m pytest -q`
- **Audio:** synthesized (Web Audio). An `aura.mp3` in `pais-site/cave/audio/` would be PUBLIC (static assets aren't behind the login).

## Daily goals + texts (added 2026-09-29)

- **RETIRED 2026-10-14 (Taran finds his own applications now; saved Claude usage):** `pais-cave-scout.timer` and
  `pais-cave-brief-evening.timer` disabled on Oracle, JOB tab mission card removed, morning text no longer mentions jobs.
  Old notes kept below for reference.
- ~~**Daily 6 applications (3 finance + 3 software):**~~ Mac `scout/daily_jobs.py` (LaunchAgent `com.taran.pais-dailyjobs`,
  7:00 + hourly retry, log `daily_jobs.log`) runs `claude -p` + WebSearch, HTTP-verifies links, writes
  `data/daily_jobs/<date>.json` (incl. the Claude-in-Chrome prompt, PII, so only served behind login) and scps it to
  Oracle `~/pais-cave/data/daily_jobs/`. Runs on the Mac because Oracle's claude CLI login is rejected.
  JOB tab "Today's mission": Gmail "thanks for applying" from that company ticks it (`cave/daily_goal.py`), or tick by hand
  (`POST /daily/mark`).
- **Academics tab:** `pais-cave-canvas.timer` (30 min) → `cave/academics_runner.py` → `data/academics.json`. Needs
  `CANVAS_TOKEN` in `~/pais-cave/.env`. Class times: `~/pais-cave/classes.json`
  `{"classes":[{"course":"STAT 319","days":"TR","start":"10:35","end":"11:50","room":"Thomas 102"}]}` (R = Thursday).
- **Texts:** `pais-cave-brief-morning.timer` (08:55 ET, refreshes Canvas then texts ~9:00) and
  `pais-cave-brief-evening.timer` (20:00 ET, only if today's 6 aren't done). `cave/notify.py` = Twilio SMS, waits for the
  carrier verdict, falls back to Gmail email when blocked (30034/30032 until A2P/toll-free registration clears).
  Dry run: `cd ~/pais-cave && .venv/bin/python -m cave.brief morning --dry`.
  PSU blocks student API tokens, so it runs off the Canvas Calendar Feed (`CANVAS_ICS_URL`): due dates + tests, no grades.
  Grades: `data/grades.json` (gitignored) written by a Claude-in-Chrome grade sync of the Canvas session → publisher `grades` section → Grades card.

## Cloud move (2026-10-02)
Job scout + AI Brief now run ON ORACLE: `pais-cave-scout.timer` (06:00 ET) and `pais-cave-ainews.timer` (06:15 ET),
scripts in `~/pais-cave/scout/` (`PAIS_CLOUD=1`), Restart=on-failure every 20 min. Claude login = `CLAUDE_CODE_OAUTH_TOKEN`
(personal account, from `claude setup-token`) in `~/pais-cave/.env`; it shares that account's usage limits. Mac LaunchAgents
`com.taran.pais-dailyjobs` / `-ainews` are `.plist.disabled`. Cloud runs don't append to the vault Job Pipeline.
