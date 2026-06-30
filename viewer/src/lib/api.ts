import type {
  FetchCreate,
  FetchResponse,
  IndexPageDetail,
  IndexPageSummary,
  ListChildrenResponse,
  CachedPage,
  ReadContentResponse,
  Site
} from '$lib/types';

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`/api${path}`);
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

async function postJson<T>(path: string, payload: unknown): Promise<T> {
  const response = await fetch(`/api${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

export function listSites(): Promise<Site[]> {
  return getJson<Site[]>('/sites/');
}

export function listIndexPages(): Promise<IndexPageSummary[]> {
  return getJson<IndexPageSummary[]>('/viewer/indexes');
}

export function getIndexPage(pk: number): Promise<IndexPageDetail> {
  return getJson<IndexPageDetail>(`/viewer/indexes/${pk}`);
}

export function listPages(params: URLSearchParams = new URLSearchParams()): Promise<CachedPage[]> {
  const suffix = params.size > 0 ? `?${params.toString()}` : '';
  return getJson<CachedPage[]>(`/pages/${suffix}`);
}

export function getPage(pk: number): Promise<CachedPage> {
  return getJson<CachedPage>(`/pages/${pk}`);
}

export function createFetch(payload: FetchCreate): Promise<FetchResponse> {
  return postJson<FetchResponse>('/fetch/', payload);
}

export function listVfsChildren(path: string): Promise<ListChildrenResponse> {
  return getJson<ListChildrenResponse>(`/vfs/children?path=${encodeURIComponent(path)}`);
}

export function readVfsContent(path: string): Promise<ReadContentResponse> {
  return getJson<ReadContentResponse>(`/vfs/content?path=${encodeURIComponent(path)}`);
}
