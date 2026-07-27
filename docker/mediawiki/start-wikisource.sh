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

cd /var/www/html

until mysqladmin ping \
  --host="$MW_DB_HOST" \
  --user="$MW_DB_USER" \
  --password="$MW_DB_PASSWORD" \
  --silent; do
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

  cat >> LocalSettings.php <<'PHP'

// Minimal Wikisource-like configuration for e2e tests.
define( 'NS_PAGE', 104 );
define( 'NS_PAGE_TALK', 105 );
define( 'NS_INDEX', 106 );
define( 'NS_INDEX_TALK', 107 );

$wgExtraNamespaces[NS_PAGE] = 'Page';
$wgExtraNamespaces[NS_PAGE_TALK] = 'Page_talk';
$wgExtraNamespaces[NS_INDEX] = 'Index';
$wgExtraNamespaces[NS_INDEX_TALK] = 'Index_talk';

$wgProofreadPageNamespaceIds = [
    'page' => NS_PAGE,
    'index' => NS_INDEX,
];

$wgEnableUploads = true;
$wgGroupPermissions['*']['edit'] = true;
$wgGroupPermissions['*']['createpage'] = true;
$wgGroupPermissions['*']['createtalk'] = true;

// DjVu scans: required for Index: pagination and page-image reference scans.
$wgFileExtensions[] = 'djvu';
// $wgDjvuDump = 'djvutoxml';
$wgDjvuDump = "djvudump";
$wgDjvuRenderer = 'ddjvu';
$wgDjvuTxt = 'djvutxt';
$wgDjvuPostProcessor = "pnmtojpeg";
$wgDjvuOutputExtension = 'jpg';

// Imports (Special:Import / importDump.php) are how test fixtures are seeded
// with real revision history.
$wgGroupPermissions['sysop']['import'] = true;
$wgGroupPermissions['sysop']['importupload'] = true;

wfLoadExtension( 'ProofreadPage' );
wfLoadExtension( 'TemplateStyles' );
wfLoadExtension( 'Scribunto' );
PHP
fi

php maintenance/update.php --quick

exec apache2-foreground
