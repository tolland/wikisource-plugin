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
  host?: string | null;
  api_url?: string | null;
  label?: string | null;
  created_at?: string | null;
}

export interface IndexPageSummary {
  pk: number;
  title: string;
  page_count?: number | null;
  revid?: number | null;
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
  body?: string | null;
  revid?: number | null;
  dirty: boolean;
  fetch_status: string;
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
