<?php

error_reporting( -1 );
ini_set( 'display_errors', 1 );

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

$wgWikisourceEnableOcr = true;
$wgWikisourceEnableBulkOcr = true;

// Imports (Special:Import / importDump.php) are how test fixtures are seeded
// with real revision history.
$wgGroupPermissions['sysop']['import'] = true;
$wgGroupPermissions['sysop']['importupload'] = true;

$wgDebugToolbar = true;
$wgShowExceptionDetails = true;
$wgScribuntoDefaultEngine = 'luastandalone';
$wgScribuntoEngineConf['luastandalone']['errorFile'] = '/tmp/scribunto.log';
$wgCachePages = false;

$wgDefaultUserOptions[ 'usecodemirror' ] = true;

wfLoadExtension( 'CodeEditor' );
wfLoadExtension( 'CodeMirror' );
wfLoadExtension( 'Gadgets' );
wfLoadExtension( 'JsonConfig' );
wfLoadExtension( 'LabeledSectionTransclusion' );
wfLoadExtension( 'ParserFunctions' );
wfLoadExtension( 'ProofreadPage' );
wfLoadExtension( 'Scribunto' );
wfLoadExtension( 'TemplateData' );
wfLoadExtension( 'TemplateStyles' );
wfLoadExtension( 'TemplateStyles' );
wfLoadExtension( 'VisualEditor' );
wfLoadExtension( 'WikiEditor' );
wfLoadExtension( 'Wikisource' );
