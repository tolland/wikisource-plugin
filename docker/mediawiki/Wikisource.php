<?php

error_reporting( -1 );
ini_set( 'display_errors', 1 );

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

$wgFileExtensions[] = 'pdf';
$wgFileExtensions[] = 'svg';
$wgFileExtensions[] = 'djvu';
$wgFileExtensions[] = 'odt';
$wgFileExtensions[] = 'ods';
$wgFileExtensions[] = 'docx';
$wgFileExtensions[] = 'xls';

$wgDebugToolbar = true;
$wgShowExceptionDetails = true;
$wgScribuntoDefaultEngine = 'luastandalone';
// $wgScribuntoEngineConf['luastandalone']['errorFile'] = '/tmp/scribunto.log';

// don't cache pages as we want to see updates immediately
$wgCachePages = false;
$wgParserCacheType = CACHE_NONE;

$wgDefaultUserOptions[ 'usecodemirror' ] = true;
$wgMaxUploadSize = 512 * 1024 * 1024;

wfLoadExtension( 'Cite' );
wfLoadExtension( 'CodeEditor' );
wfLoadExtension( 'CodeMirror' );
wfLoadExtension( 'Gadgets' );
wfLoadExtension( 'JsonConfig' );
wfLoadExtension( 'LabeledSectionTransclusion' );
wfLoadExtension( 'Math' );
wfLoadExtension( 'ParserFunctions' );
wfLoadExtension( 'PdfHandler' );
wfLoadExtension( 'ProofreadPage' );
wfLoadExtension( 'Scribunto' );
wfLoadExtension( 'TemplateData' );
wfLoadExtension( 'TemplateStyles' );
wfLoadExtension( 'VisualEditor' );
wfLoadExtension( 'WikiEditor' );
wfLoadExtension( 'Wikisource' );

$wgUploadBaseUrl = getenv('MW_SERVER');
