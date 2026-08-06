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
  family: string;
  code: string;
  api_url?: string | null;
  kind?: FetchKind;
  depth?: number;
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
