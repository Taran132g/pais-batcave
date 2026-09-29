#!/bin/bash
# Deploy the PAIS cave API to Oracle. Idempotent. Run from ~/pais-batcave/oracle.
set -euo pipefail
HOST=ubuntu@129.159.182.210
SSH=(ssh -i ~/.ssh/oracle_pais.key -o BatchMode=yes)
cd "$(dirname "$0")"
cp ../server/auth.py cave/auth.py   # single source of truth for login logic
cp ~/agentic_os/tools/market_prices.py cave/market_prices.py        # live price feeds
cp ~/Automated-Trading-Bot/yubit_mark.py cave/yubit_mark.py         # mark-to-market math
cp ../publisher/gmail_jobs.py ../publisher/job.py cave/               # Job tab runs on Oracle
cp ../goals.json .
"${SSH[@]}" $HOST 'mkdir -p ~/pais-cave/data ~/pais-cave/cave ~/pais-cave/assets && chmod 700 ~/pais-cave/data'
scp -i ~/.ssh/oracle_pais.key -q assets/* $HOST:pais-cave/assets/
scp -i ~/.ssh/oracle_pais.key -q cave/*.py pais-cave*.service pais-cave*.timer $HOST:pais-cave/cave/
scp -i ~/.ssh/oracle_pais.key -q goals.json $HOST:pais-cave/goals.json
"${SSH[@]}" $HOST 'set -e; cd ~/pais-cave; mv cave/pais-cave.service .
  [ -x .venv/bin/python ] || python3 -m venv .venv
  .venv/bin/pip install -q --disable-pip-version-check fastapi uvicorn pyotp httpx coinbase-advanced-py
  mv cave/pais-cave-*.service cave/pais-cave-*.timer .
  sudo cp pais-cave.service pais-cave-*.service pais-cave-*.timer /etc/systemd/system/
  mkdir -p data/daily_jobs && chmod 700 data/daily_jobs
  sudo systemctl daemon-reload
  sudo systemctl enable --now pais-cave pais-cave-jobs.timer pais-cave-canvas.timer pais-cave-brief-morning.timer pais-cave-brief-evening.timer
  sudo systemctl restart pais-cave
  sleep 2; systemctl is-active pais-cave; curl -s http://127.0.0.1:8155/session'
