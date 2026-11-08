#!/usr/bin/env bash
# chrome-cdp.sh - the CDP Chrome the importer drives, on ONE persistent profile.
#
#   chrome-cdp.sh start            start it (unless CDP already answers), open the olx.ro
#                                  and admin tabs, wait until CDP answers
#   chrome-cdp.sh stop             close the Chrome running on this profile
#   chrome-cdp.sh restart          stop + start (e.g. after OLX_BLOCKED)
#   chrome-cdp.sh status           does CDP answer? which profile, how big?
#   chrome-cdp.sh backup [dir]     tar.gz of the profile without its caches (Chrome closed);
#                                  default dir ~/.hermes/backups
#   chrome-cdp.sh restore <file>   put a backup back as the profile (Chrome closed; the
#                                  current profile is moved aside, not deleted)
#
# The profile is a folder: logins (3ceasuri.ro admin, olx.ro), cookies and tabs live in
# it and survive every restart as long as the same folder is used. It stays OUTSIDE the
# repo on purpose - it holds a signed-in admin session; never commit it.
#
# Env: CHROME_PROFILE (default ~/.hermes/chrome-debug), CDP_PORT (9222), CHROME_BIN
#      (google-chrome), CDP_ADDRESS (0.0.0.0, as the user starts it). NOTE: 0.0.0.0 lets
#      anyone who can reach this port drive the browser - signed in to the admin - with
#      no password. CDP_ADDRESS=127.0.0.1 keeps it on this machine.
set -euo pipefail

PROFILE="${CHROME_PROFILE:-$HOME/.hermes/chrome-debug}"
PORT="${CDP_PORT:-9222}"
ADDR="${CDP_ADDRESS:-0.0.0.0}"
CHROME="${CHROME_BIN:-google-chrome}"
BACKUPS_DEFAULT="$HOME/.hermes/backups"
# caches: rebuilt by Chrome, most of the profile's size, useless in a backup
EXCLUDES=(--exclude='Cache' --exclude='Code Cache' --exclude='GPUCache' --exclude='GrShaderCache'
          --exclude='ShaderCache' --exclude='GraphiteDawnCache' --exclude='DawnCache'
          --exclude='CacheStorage' --exclude='ScriptCache' --exclude='component_crx_cache'
          --exclude='optimization_guide_model_store' --exclude='Crashpad'
          --exclude='Singleton*')

cdp_up() { curl -s -m 2 "http://127.0.0.1:$PORT/json/version" >/dev/null 2>&1; }
on_profile() { pgrep -f -- "--user-data-dir=$PROFILE" >/dev/null 2>&1; }

start() {
  if cdp_up; then
    echo "CDP already answers on :$PORT (profile in use: $PROFILE)"; return 0
  fi
  mkdir -p "$PROFILE"
  nohup "$CHROME" --remote-debugging-address="$ADDR" --remote-debugging-port="$PORT" \
    '--remote-allow-origins=*' --user-data-dir="$PROFILE" --no-first-run \
    --no-default-browser-check "https://www.olx.ro/" "https://3ceasuri.ro/admin/" \
    >"$PROFILE.log" 2>&1 &
  disown || true
  for _ in $(seq 1 30); do
    if cdp_up; then
      echo "CDP up on $ADDR:$PORT | profile $PROFILE"
      curl -s "http://127.0.0.1:$PORT/json/version" | grep -m1 '"Browser"' || true
      echo "Sign in to the admin and olx.ro once if the tabs ask; the profile remembers it."
      return 0
    fi
    sleep 1
  done
  echo "Chrome did not open CDP on :$PORT within 30 s - see $PROFILE.log" >&2; return 1
}

stop() {
  if ! on_profile; then echo "no Chrome on $PROFILE"; return 0; fi
  pkill -TERM -f -- "--user-data-dir=$PROFILE" || true
  for _ in $(seq 1 15); do on_profile || { echo "Chrome closed"; return 0; }; sleep 1; done
  echo "Chrome still running on $PROFILE - close it by hand" >&2; return 1
}

status() {
  if cdp_up; then echo "CDP: up on :$PORT"; else echo "CDP: down on :$PORT"; fi
  if on_profile; then echo "Chrome on profile: yes"; else echo "Chrome on profile: no"; fi
  echo "profile: $PROFILE ($(du -sh "$PROFILE" 2>/dev/null | cut -f1 || echo missing))"
}

backup() {
  local dir="${1:-$BACKUPS_DEFAULT}"
  if on_profile; then
    echo "close Chrome first (chrome-cdp.sh stop): a live profile copies half-written" >&2; return 1
  fi
  [ -d "$PROFILE" ] || { echo "no profile at $PROFILE" >&2; return 1; }
  mkdir -p "$dir"
  local out="$dir/$(basename "$PROFILE")-$(date +%Y%m%d-%H%M).tar.gz"
  tar -C "$PROFILE" "${EXCLUDES[@]}" -czf "$out" .
  echo "backup: $out ($(du -h "$out" | cut -f1))"
}

restore() {
  local file="${1:?usage: chrome-cdp.sh restore <backup.tar.gz>}"
  if on_profile; then echo "close Chrome first (chrome-cdp.sh stop)" >&2; return 1; fi
  [ -f "$file" ] || { echo "no such file: $file" >&2; return 1; }
  if [ -d "$PROFILE" ]; then
    local aside="$PROFILE.before-restore-$(date +%Y%m%d-%H%M)"
    mv "$PROFILE" "$aside"; echo "current profile moved to $aside"
  fi
  mkdir -p "$PROFILE"
  tar -C "$PROFILE" -xzf "$file"
  echo "restored $file -> $PROFILE"
}

case "${1:-}" in
  start) start ;;
  stop) stop ;;
  restart) stop && start ;;
  status) status ;;
  backup) shift; backup "${1:-}" ;;
  restore) shift; restore "${1:-}" ;;
  *) sed -n '2,24p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
