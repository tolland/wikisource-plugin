#!/usr/bin/env bash
set -euo pipefail

: "${MW_ADMIN_PASSWORD:=AdminPassword123!}"
: "${MW_ADMIN_USER:=Admin}"
: "${MW_DB_HOST:=db}"
: "${MW_DB_NAME:=mediawiki}"
: "${MW_DB_PASSWORD:=mediawiki}"
: "${MW_DB_USER:=mediawiki}"
: "${MW_LANG:=en}"
: "${MW_SCRIPT_PATH:=}"
: "${MW_SERVER:=http://localhost:8080}"
: "${MW_SITE_NAME:=Test Wikisource}"

# --- seeding ---------------------------------------------------------------
# A wiki seeds itself from these, rather than being seeded from outside once it
# is up. Two wikis given the same values are then identical *because they are
# configured identically*, which is a property compose can guarantee and a
# script that has to remember to do both sides cannot.
: "${SEED_SCANS:=}"       # file extension for importImages, e.g. 'djvu'
: "${SEED_DUMPS:=}"       # space-separated XML dumps under /fixtures/scans
: "${SEED_REVID_BURN:=0}" # throwaway revisions, to desynchronise revids

# Written last, removed first: the healthcheck waits on it so that
# `compose up --wait` cannot return while an import is still running.
READY_MARKER=/var/www/html/images/.harness-ready

cd /var/www/html

rm -f "$READY_MARKER"

cat <<'EOF'

                                _ _    _
 _ __ _   _ _ __      __      _(_) | _(_)___  ___  _   _ _ __ ___ ___
| '__| | | | '_ \ ____\ \ /\ / / | |/ / / __|/ _ \| | | | '__/ __/ _ \
| |  | |_| | | | |_____\ V  V /| |   <| \__ \ (_) | |_| | | | (_|  __/
|_|   \__,_|_| |_|      \_/\_/ |_|_|\_\_|___/\___/ \__,_|_|  \___\___|

EOF


cd /var/www/html

rm -f "$READY_MARKER"

mw_sql() {
  MYSQL_PWD="$MW_DB_PASSWORD" mysql \
    --host="$MW_DB_HOST" \
    --user="$MW_DB_USER" \
    --database="$MW_DB_NAME" \
    --skip-column-names --batch --execute="$1"
}

already_seeded() {
  # Asked of the database rather than a file, because the database is what the
  # persistent volume holds -- a marker file could survive a wiped database or
  # vice versa, and either way round the wiki would come up subtly wrong.
  local count
  count="$(mw_sql 'SELECT COUNT(*) FROM page WHERE page_namespace = 106' || echo 0)"
  [ "${count:-0}" -gt 0 ]
}

until mysqladmin ping \
  --host="$MW_DB_HOST" \
  --user="$MW_DB_USER" \
  --password="$MW_DB_PASSWORD" \
  --silent; do
        echo "waiting 2s for mysql"
        sleep 2
done

if [ ! -f LocalSettings.php ]; then
  php maintenance/install.php \
    --server "$MW_SERVER" \
    --scriptpath "$MW_SCRIPT_PATH" \
    --dbtype mysql \
    --dbserver "$MW_DB_HOST" \
    --dbname "$MW_DB_NAME" \
    --dbuser "$MW_DB_USER" \
    --dbpass "$MW_DB_PASSWORD" \
    --lang "$MW_LANG" \
    --pass "$MW_ADMIN_PASSWORD" \
    "$MW_SITE_NAME" \
    "$MW_ADMIN_USER"

echo "cat out extra bit of LocalSettings"

  cat >> LocalSettings.php <<'PHP'

foreach (glob("LocalSettings.d/*.php") as $filename)
{
    include $filename;
}

PHP

echo "END OF cat out extra bit of LocalSettings"
fi

sleep 1

printf "running maintenance update\n"

php maintenance/run.php update --quick


# Content seeding. Guarded on the database so a warm volume restarts fast and,
# more importantly, so a restart cannot stack extra revisions onto pages whose
# revision counts the tests assert on.
if [ -n "$SEED_DUMPS$SEED_SCANS" ] ; then

  # Burn revision ids before importing anything real. Both wikis install the
  # same modules in the same order from empty, so without this they assign the
  # *same* revids to the same content -- and a bug that compared revids across
  # sites would pass here while failing against real wikis, which is precisely
  # the mistake site-local ids exist to make impossible. Wasting a few ids on
  # one side makes that bug fail loudly in the fixture instead.
  i=1
  while [ "$i" -le "$SEED_REVID_BURN" ]; do
    printf 'Revid burn %s.\n' "$i" \
      | php maintenance/run.php edit \
          -u "$MW_ADMIN_USER" \
          -s "harness: revid burn $i" \
          "Project:Harness revid burn"
    i=$((i + 1))
  done

  if [ -n "$SEED_SCANS" ]; then
    printf 'importing scans (*.%s)\n' "$SEED_SCANS"
    # importImages derives each File: title from the filename (underscores
    # become spaces), which is how the dumps' File: references resolve.
    php maintenance/run.php importImages \
      --comment="harness scan import" \
      "--extensions=$SEED_SCANS" \
      /fixtures/scans
  fi

  for dump in $SEED_DUMPS; do
    printf 'importing dump %s\n' "$dump"
    # --no-updates skips link/category table updates, which rebuildall does in
    # one pass below; importDump preserves each revision's text, timestamp and
    # contributor, which an API-level copy would flatten to a single revision.
    php maintenance/run.php importDump --no-updates "/fixtures/scans/$dump"
  done

  if [ -n "$SEED_DUMPS" ]; then
    # ProofreadPage's Index: pagination needs the link tables --no-updates left
    # empty.
    printf 'rebuilding link tables\n'
#    php maintenance/run.php rebuildall
    php maintenance/run.php showJobs
    php maintenance/run.php runJobs
  fi
fi


touch "$READY_MARKER"

chown www-data:www-data /tmp/scribunto.log || true

exec apache2-foreground
