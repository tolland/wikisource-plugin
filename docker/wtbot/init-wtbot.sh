#!/bin/bash

set -eu -o pipefail

sites=("local" "remote")
apis=("http://127.0.0.1:18572/api.php" "http://127.0.0.1:18571/api.php")

for i in "${!sites[@]}"; do
    site="${sites[i]}"
    api="${apis[i]}"
    echo "site = $site is api = $api"


uv run wtbot site show "${site}" ||
    uv run wtbot site add \
        --label "${site}" \
        --family "${site}" \
        --code en \
        --api-url "$api" \
        --username admin \
        --password "AdminPassword123!"

uv run wtbot site update "${site}" --read-throttle 0.01

uv run wtbot fetch-page  \
    --revisions 5 \
    --label "${site}" \
    --drain \
    "File:The principles of mechanics presented in a new form (Hertz, 1894).pdf"

uv run wtbot fetch-page  \
    --revisions 5 \
    --label "${site}" \
    --drain \
    "Index:The_principles_of_mechanics_presented_in_a_new_form_(Hertz,_1894).pdf"
done
