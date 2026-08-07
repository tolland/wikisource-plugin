#!/usr/bin/env bash
set -euo pipefail

: "${WTBOT_DATABASE_URL:=sqlite:////data/wtbot.db}"
: "${WTBOT_BLOB_ROOT:=/data/blobs}"
: "${WTBOT_HOST:=127.0.0.1}"
: "${WTBOT_PORT:=8000}"
: "${WTBOT_RESET_DB:=0}"

cat << 'EOF'
          _   _           _   _ _
__      _| |_| |__   ___ | |_| | |
\ \ /\ / / __| '_ \ / _ \| __| | |
 \ V  V /| |_| |_) | (_) | |_|_|_|
  \_/\_/  \__|_.__/ \___/ \__(_|_)

EOF

# The database is disposable by design. It holds a *cache* of wiki content plus
# the local edit journal -- everything in it is either refetchable or was going
# to be pushed to a wiki -- so a harness that wants a clean slate should not
# have to reason about migrations or leftover rows from a previous shape of the
# schema. `down --volumes` throws it away; WTBOT_RESET_DB=1 throws it away
# without touching the wikis, which are the slow half to rebuild.
if [ "$WTBOT_RESET_DB" = "1" ]; then
  case "$WTBOT_DATABASE_URL" in
    sqlite:///*)
      # SQLAlchemy spells the path after exactly three slashes, so a fourth is
      # the leading slash of an absolute path: sqlite:////data/x.db is
      # /data/x.db, sqlite:///x.db is relative.
      db_path="${WTBOT_DATABASE_URL#sqlite:///}"
      printf 'WTBOT_RESET_DB=1: removing %s\n' "$db_path"
      # -wal and -shm too: WAL is on for every connection, and a stale WAL
      # beside a deleted database is how you get a file that is empty and
      # locked at the same time.
      rm -f "$db_path" "$db_path-wal" "$db_path-shm"
      ;;
    *)
      printf 'WTBOT_RESET_DB=1 ignored: %s is not sqlite\n' "$WTBOT_DATABASE_URL" >&2
      ;;
  esac
fi

mkdir -p "$WTBOT_BLOB_ROOT"

# Migrations run in the app factory (wtbot.main.create_app -> init_db), so
# there is no separate migrate step to keep in sync with it.
exec uvicorn wtbot.main:app --host "$WTBOT_HOST" --port "$WTBOT_PORT"
