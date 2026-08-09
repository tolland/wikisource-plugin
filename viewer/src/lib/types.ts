export type FetchKind = 'single' | 'index';
export type FetchStatus = 'pending' | 'running' | 'done' | 'error';
export type NamespaceRole =
  | 'main'
  | 'page'
  | 'index'
  | 'file'
  | 'template'
  | 'module'
  | 'category'
  | 'author'
  | 'book'
  | 'other';

export interface Site {
  pk: number;
  family: string;
  code: string;
  articlepath?: string | null;
  api_url?: string | null;
  label?: string | null;
  created_at?: string | null;
}

export interface WikiNamespace {
  pk: number;
  site_pk: number;
  key: number;
  canonical_name: string;
  local_name: string;
  role: NamespaceRole;
  subpages: boolean;
  content: boolean;
  case?: string | null;
}

export interface SitePayload {
  family: string;
  code: string;
  articlepath?: string;
  api_url?: string | null;
  label?: string | null;
}

export interface SiteCredential {
  site_pk: number;
  username: string;
  password: string;
  bot_name?: string | null;
  updated_at: string;
}

export interface CredentialPayload {
  username: string;
  password: string;
  bot_name?: string | null;
}

export type OcrBackendKind = 'wikimedia' | 'token_api';

export interface OcrBackend {
  name: string;
  kind: OcrBackendKind;
  base_url: string;
  default_engine?: string | null;
  default_langs: string[];
  default_prompt?: string | null;
  enabled: boolean;
  has_api_token: boolean;
  supports_prompt: boolean;
  supports_segment: boolean;
  /** Whether GET /ocr/models can enumerate this backend's engines/languages. */
  supports_discovery: boolean;
}

/** One recognizable language/model of an engine, e.g. `en` / "English". */
export interface OcrModel {
  code: string;
  title: string;
}

/**
 * One engine a backend offers. An empty `models` is normal rather than a
 * failure: pix2tex reads mathematical notation and has no language
 * dimension at all.
 */
export interface OcrEngine {
  engine: string;
  models: OcrModel[];
}

/**
 * What one backend can be asked for, from GET /ocr/models. A non-null
 * `error` means discovery failed and `engines` is empty; the backend is
 * still runnable on its configured defaults.
 */
export interface OcrCatalog {
  backend: string;
  engines: OcrEngine[];
  error?: string | null;
}

export interface OcrBackendPayload {
  kind: OcrBackendKind;
  base_url: string;
  api_token?: string | null;
  default_engine?: string | null;
  default_langs: string[];
  default_prompt?: string | null;
  enabled: boolean;
}

export interface OcrBackendList {
  backends: OcrBackend[];
}

export interface IndexPageSummary {
  pk: number;
  title: string;
  family: string;
  code: string;
  page_count?: number | null;
  revid?: number | null;
  content_model?: string | null;
  body_length: number;
}

export interface IndexPageDetail extends IndexPageSummary {
  body: string;
}

export interface FetchRequest {
  pk: number;
  site_pk: number;
  title: string;
  kind: FetchKind;
  depth: number;
  revisions: number;
  status: string;
  progress_total?: number | null;
  progress_done?: number | null;
  error_message?: string | null;
}

export interface CachedPage {
  pk: number;
  site_pk: number;
  title: string;
  namespace_role: NamespaceRole;
  namespace_key?: number | null;
  content_model?: string | null;
  text?: string | null;
  pageid?: number | null;
  revid?: number | null;
  remote_timestamp?: string | null;
  contributor?: string | null;
  comment?: string | null;
  sha1?: string | null;
  local_modified_at?: string | null;
  dirty: boolean;
  fetch_status: string;
  fetch_error?: string | null;
}

export interface FetchCreate {
  title: string;
  /** The registered site to fetch from. A site is never created by a fetch. */
  label: string;
  kind?: FetchKind;
  depth?: number;
  /**
   * Revisions to store, counting back from the head. 1 is a normal fetch; more
   * fills in history for the cross-site anchor search, which cannot find a
   * match at the head when one side was imported from an older revision of the
   * other.
   */
  revisions?: number;
}

export interface FetchResponse {
  request: FetchRequest;
  page?: CachedPage | null;
}

export type CommitStatus = 'pending' | 'success' | 'conflict' | 'error';

export interface Commit {
  pk: number;
  page_pk: number;
  base_revid: number;
  submitted_body: string;
  comment?: string | null;
  status: CommitStatus;
  result_revid?: number | null;
  error_message?: string | null;
  created_at: string;
}

export interface CommitRunResponse {
  handled: number;
}

export interface PendingCommitJournal {
  pk: number;
  base_revid?: number | null;
  body: string;
  comment?: string | null;
  saved_at: string;
}

export interface PendingCommitPage {
  page_pk: number;
  site_pk: number;
  title: string;
  current_revid?: number | null;
  base_revid: number;
  comment?: string | null;
  base_body?: string | null;
  submitted_body: string;
  pending_count: number;
  first_saved_at: string;
  latest_saved_at: string;
  journals: PendingCommitJournal[];
}

export type NodeKind = 'file' | 'directory';

export interface VfsNode {
  path: string;
  name: string;
  kind: NodeKind;
  stable_id?: number | null;
  revid?: number | null;
  timestamp?: string | null;
  length?: number | null;
  writable: boolean;
}

export interface ListChildrenResponse {
  parent_path: string;
  children: VfsNode[];
}

export interface ReadContentResponse {
  path: string;
  revid?: number | null;
  content_base64: string;
}

/* --- cross-site links -----------------------------------------------------
 *
 * Three levels, and the viewer navigates them in order:
 *
 *   work      two Index: pages that are the same work        /links
 *   page pair one page of that work, on both sides           /links/[work]
 *   revisions the two histories, and what matches in them    /links/pairs/[pk]
 *
 * The third exists because the anchor search stops at the heads: a page whose
 * two sides have both moved on has no proposable link even when the matching
 * revision pair is plainly there, and a person can see it and assert it.
 */

export type MatchOutcome =
  | 'same'
  | 'local_ahead'
  | 'remote_ahead'
  | 'quality_differs'
  | 'diverged'
  | 'history_exhausted'
  | 'no_counterpart'
  | 'unfetched'
  | 'already_linked';

export type LinkOrigin = 'copy' | 'title_match' | 'manual' | 'reconciled';

export interface WorkSummary {
  pk: number;
  page_link_pk: number;
  created_at: string;
  local_title: string;
  remote_title: string;
  local_site: string;
  remote_site: string;
  local_page_pk: number;
  remote_page_pk: number;
  /** Page pairs claimed by this work. */
  pairs: number;
  /** Of those, how many have at least one revision link. */
  linked: number;
  /** Page: children the local index has cached, paired or not. */
  local_pages: number;
}

export interface IndexCandidate {
  page_pk: number;
  title: string;
  page_count?: number | null;
  cached_pages: number;
  /** Non-null when this index is already half of a tracked work. */
  work_pk?: number | null;
  paired_with?: string | null;
}

export interface CandidateList {
  site: string;
  site_pk: number;
  indexes: IndexCandidate[];
}

export interface LinkWorkResult {
  work: WorkSummary;
  created: boolean;
  paired: number;
  adopted: number;
  unpaired: string[];
}

export interface PagePair {
  pair_pk?: number | null;
  page_number?: number | null;
  outcome: MatchOutcome;
  proposable: boolean;
  /** True when a deeper fetch could turn this into a link. */
  resolvable_by_fetch: boolean;
  local_title: string;
  remote_title?: string | null;
  local_revid?: number | null;
  remote_revid?: number | null;
  local_ahead_by: number;
  remote_ahead_by: number;
  significance?: string | null;
  detail?: string | null;
  rungs: number;
}

export interface WorkDetail {
  work: WorkSummary;
  pages: PagePair[];
  counts: Record<string, number>;
  needs_history: number;
}

export interface ProposeWorkResult {
  counts: Record<string, number>;
  confirmed: number;
}

export interface FetchHistoryResult {
  queued: number;
  pages: number;
  revisions: number;
  note: string;
}

export interface RevisionRow {
  revision_pk: number;
  revid: number;
  parent_revid?: number | null;
  timestamp?: string | null;
  contributor?: string | null;
  comment?: string | null;
  is_head: boolean;
  /** Two revisions with the same digest hold the same content, either site. */
  comparable_sha1?: string | null;
  content_sha1?: string | null;
  level?: number | null;
  user?: string | null;
  linked_to: number[];
}

export interface RevisionMatch {
  local_revision_pk: number;
  remote_revision_pk: number;
  local_revid: number;
  remote_revid: number;
  local_ahead_by: number;
  remote_ahead_by: number;
  is_heads: boolean;
  linked: boolean;
  link_pk?: number | null;
}

export interface RungRow {
  pk: number;
  local_revision_pk: number;
  remote_revision_pk: number;
  origin: LinkOrigin;
}

export interface PairRevisions {
  pair_pk: number;
  local_title: string;
  remote_title: string;
  local_site: string;
  remote_site: string;
  local: RevisionRow[];
  remote: RevisionRow[];
  matches: RevisionMatch[];
  rungs: RungRow[];
  local_history_complete: boolean;
  remote_history_complete: boolean;
}

/* --- sync report ----------------------------------------------------------
 *
 * Directional, unlike the link layer beneath it. A pairing says two pages are
 * the same page and does not care which is which; a sync asks what would be
 * written and to which wiki, so reversing it reverses the answer.
 */

export type SyncVerdict =
  | 'in_sync'
  | 'create'
  | 'push'
  | 'pull'
  | 'diverged'
  | 'unlinked'
  | 'source_missing'
  | 'unknown';

export type ScanStatus = 'ok' | 'mismatch' | 'unverifiable';

export interface ScanCheck {
  status: ScanStatus;
  detail: string;
  source_file?: string | null;
  target_file?: string | null;
  source_sha1?: string | null;
  target_sha1?: string | null;
  source_page_count?: number | null;
  target_page_count?: number | null;
  blocks: boolean;
}

export interface SyncSide {
  site: string;
  site_pk: number;
  index_title: string;
  exists: boolean;
  cached_pages: number;
  /** Paginated slots holding no revision: known absent, not unfetched. */
  placeholder_pages: number;
}

export interface SyncPage {
  verdict: SyncVerdict;
  page_number?: number | null;
  source_title?: string | null;
  target_title?: string | null;
  pair_pk?: number | null;
  target_is_placeholder: boolean;
  source_revid?: number | null;
  target_revid?: number | null;
  anchor_source_revid?: number | null;
  anchor_target_revid?: number | null;
  rungs: number;
  source_ahead_by: number;
  target_ahead_by: number;
  detail?: string | null;
  /** True when a push in the reported direction would write this page. */
  actionable: boolean;
}

export interface SyncReport {
  source: SyncSide;
  target: SyncSide;
  scan: ScanCheck;
  pages: SyncPage[];
  counts: Record<string, number>;
  actionable: number;
  work_pk?: number | null;
  blockers: string[];
  blocked: boolean;
}

export interface SyncRequest {
  source_label?: string | null;
  target_label?: string | null;
  index_title: string;
  target_index_title?: string | null;
}

// ---- Locator index (GET /locator-index/{page-numbers,sections}) ----------

export type LocatorConfidence = 'explicit' | 'inferred' | 'unknown';
export type SectionRole = 'begin' | 'end' | 'anchor_template';

export interface LocatorPageRef {
    path: string;
    title: string;
    scan_page: number;
}

export interface LocatorPageNumberMatch {
    label: string;
    confidence: LocatorConfidence;
    page: LocatorPageRef;
}

export interface LocatorSectionMatch {
    section_id: string;
    role: SectionRole;
    page: LocatorPageRef;
}
