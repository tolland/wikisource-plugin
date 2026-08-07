#!/usr/bin/env sh
set -eu

: "${WTBOT_VIEWER_HOST:=127.0.0.1}"
: "${WTBOT_VIEWER_PORT:=5173}"

cat << 'EOF'
       _
__   _(_) _____      _____ _ __
\ \ / / |/ _ \ \ /\ / / _ \ '__|
 \ V /| |  __/\ V  V /  __/ |
  \_/ |_|\___| \_/\_/ \___|_|

EOF

npm run dev -- --host "${WTBOT_VIEWER_HOST}" --port "${WTBOT_VIEWER_PORT}"
