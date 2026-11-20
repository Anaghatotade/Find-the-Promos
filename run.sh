#!/usr/bin/env bash
# PromoFinder launcher for Linux and macOS.
#
#   ./run.sh                 start the web app and open it in your browser
#   ./run.sh cli run X.zip   run the command-line tool (any `python -m promofinder` arguments)
#   ./run.sh test            run the automated tests
#   ./run.sh check           check the environment without starting anything
#   ./run.sh reset           delete the local environment (.venv) so the next launch rebuilds it
#
# First launch: finds Python 3.10+, creates .venv, installs requirements (about a minute), creates .env.
# Later launches: starts immediately. Dependencies are reinstalled only when requirements.txt changes.
set -euo pipefail
cd "$(dirname "$0")"
say() { printf '\033[1m%s\033[0m\n' "$*"; }
die() { printf '\n\033[31mPromoFinder could not start:\033[0m %s\n\n' "$*" >&2; exit 1; }

if [ "${1:-}" = "reset" ]; then rm -rf .venv; say "Removed .venv. Run ./run.sh to rebuild it."; exit 0; fi

# 1. Python 3.10 or newer
PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then PY="$c"; break; fi
done
[ -n "$PY" ] || die "Python 3.10 or newer was not found.
  macOS:          brew install python   (or download it from https://www.python.org/downloads/)
  Ubuntu/Debian:  sudo apt install python3 python3-venv
Then run ./run.sh again."

# 2. Private environment in .venv (rebuilt if missing, broken, or created on another computer/OS)
VPY=.venv/bin/python
if [ ! -x "$VPY" ] || ! "$VPY" -c 'import sys' >/dev/null 2>&1; then
  [ -d .venv ] && { say "Rebuilding .venv (it was created for another computer or is damaged)"; rm -rf .venv; }
  say "First launch: creating a private Python environment with $($PY --version 2>&1)"
  "$PY" -m venv .venv 2>/dev/null || die "could not create a virtual environment.
  Ubuntu/Debian:  sudo apt install python3-venv   then run ./run.sh again."
fi

# 3. Dependencies (only when requirements.txt changed since the last install)
HASH=$("$VPY" -c "import hashlib;print(hashlib.sha256(open('requirements.txt','rb').read()).hexdigest())")
if [ "$(cat .venv/.requirements.sha256 2>/dev/null || true)" != "$HASH" ]; then
  say "Installing dependencies (one time, needs internet)..."
  "$VPY" -m pip install --disable-pip-version-check -q --upgrade pip >/dev/null 2>&1 || true
  "$VPY" -m pip install --disable-pip-version-check -q -r requirements.txt || die "installing dependencies failed (see the messages above).
  Check your internet connection, then run ./run.sh again. To start over: ./run.sh reset"
  echo "$HASH" > .venv/.requirements.sha256
fi
"$VPY" -c "import flask, numpy, scipy, sklearn, yaml, vaderSentiment" 2>/dev/null || {
  rm -f .venv/.requirements.sha256; die "dependencies are incomplete. Run ./run.sh again (or ./run.sh reset)."; }

# 4. Local settings file for optional API keys
[ -f .env ] || { cp .env.example .env; say "Created .env (optional API keys go there; it never leaves this computer)."; }

export PYTHONUTF8=1 FLASK_SKIP_DOTENV=1
case "${1:-}" in
  check) "$VPY" -c "import promofinder, sys; print('PromoFinder', promofinder.__version__, 'ready on Python', sys.version.split()[0])"
         "$VPY" -c "from promofinder.llm import load_dotenv, llm_status; from promofinder.config import load_config; load_dotenv(); print('LLM:', llm_status(load_config('config.yaml'))['message'])"
         exit 0 ;;
  test)  shift; "$VPY" -m pip install --disable-pip-version-check -q pytest >/dev/null 2>&1 || true
         exec "$VPY" -m pytest -q tests "$@" ;;
  cli)   shift; exec "$VPY" -m promofinder "$@" ;;
esac

# 5. Start the web app (it picks the next free port if 7860 is taken) and open the browser
export PROMOFINDER_OPEN_BROWSER="${PROMOFINDER_OPEN_BROWSER:-1}"
exec "$VPY" app.py
