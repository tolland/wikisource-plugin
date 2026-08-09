import type {
  FetchCreate,
  FetchResponse,
  IndexPageDetail,
  IndexPageSummary,
  ListChildrenResponse,
  LocatorIndexDump,
  LocatorPageNumberMatch,
  LocatorSectionMatch,
  CachedPage,
  Commit,
  CommitRunResponse,
  PendingCommitPage,
  ReadContentResponse,
  SectionRole,
  Site,
  SiteCredential,
  SitePayload,
  WikiNamespace,
  CredentialPayload,
  OcrBackend,
  OcrBackendList,
  OcrBackendPayload,
  OcrCatalog
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

async function putJson<T>(path: string, payload: unknown): Promise<T> {
  const response = await fetch(`/api${path}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

async function deleteRequest(path: string): Promise<void> {
  const response = await fetch(`/api${path}`, { method: 'DELETE' });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
}

export function listSites(): Promise<Site[]> {
  return getJson<Site[]>('/sites/');
}

export function listNamespaces(sitePk: number): Promise<WikiNamespace[]> {
  return getJson<WikiNamespace[]>(`/namespaces/?site_pk=${sitePk}`);
}

export function createSite(payload: SitePayload): Promise<Site> {
  return postJson<Site>('/sites/', payload);
}

export function updateSite(sitePk: number, payload: SitePayload): Promise<Site> {
  return putJson<Site>(`/sites/${sitePk}`, payload);
}

export async function getSiteCredential(sitePk: number): Promise<SiteCredential | null> {
  const response = await fetch(`/api/sites/${sitePk}/credential`);
  if (response.status === 404) return null;
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<SiteCredential>;
}

export function saveSiteCredential(
  sitePk: number,
  payload: CredentialPayload
): Promise<SiteCredential> {
  return putJson<SiteCredential>(`/sites/${sitePk}/credential`, payload);
}

export function deleteSiteCredential(sitePk: number): Promise<void> {
  return deleteRequest(`/sites/${sitePk}/credential`);
}

// OCR config routes use a plain scope string, so the viewer maps each site
// to its family/code scope when calling the main wtbot API.
function ocrScopeQuery(
  site: Pick<Site, 'family' | 'code'>,
  extra?: Record<string, string>
): string {
  return new URLSearchParams({ scope: `${site.family}/${site.code}`, ...extra }).toString();
}

export async function listOcrBackends(
  site: Pick<Site, 'family' | 'code'>
): Promise<OcrBackend[]> {
  // enabled_only=false: the admin UI needs to show (and let you re-enable)
  // disabled backends too, unlike the plugin's page-scoped discovery.
  const result = await getJson<OcrBackendList>(
    `/ocr/backends?${ocrScopeQuery(site, { enabled_only: 'false' })}`
  );
  return result.backends;
}

/**
 * The engines and languages a backend actually offers. Cached server-side
 * (the raw list is hundreds of kilobytes); pass `refresh` to bypass that.
 */
export function listOcrModels(
  site: Pick<Site, 'family' | 'code'>,
  name?: string,
  refresh = false
): Promise<OcrCatalog> {
  const extra: Record<string, string> = {};
  if (name) extra.backend = name;
  if (refresh) extra.refresh = 'true';
  return getJson<OcrCatalog>(`/ocr/models?${ocrScopeQuery(site, extra)}`);
}

export function saveOcrBackend(
  site: Pick<Site, 'family' | 'code'>,
  name: string,
  payload: OcrBackendPayload
): Promise<OcrBackend> {
  return putJson<OcrBackend>(
    `/ocr/config/${encodeURIComponent(name)}?${ocrScopeQuery(site)}`,
    payload
  );
}

export function deleteOcrBackend(
  site: Pick<Site, 'family' | 'code'>,
  name: string
): Promise<void> {
  return deleteRequest(`/ocr/config/${encodeURIComponent(name)}?${ocrScopeQuery(site)}`);
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

export function listPendingCommits(): Promise<PendingCommitPage[]> {
  return getJson<PendingCommitPage[]>('/commits/pending');
}

export function approvePendingCommit(pagePk: number, force = false): Promise<Commit> {
  const suffix = force ? '?force=true' : '';
  return postJson<Commit>(`/commits/${pagePk}${suffix}`, {});
}

export async function cancelPendingCommit(pagePk: number): Promise<CommitRunResponse> {
  const response = await fetch(`/api/commits/${pagePk}/pending`, { method: 'DELETE' });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<CommitRunResponse>;
}

export function listVfsChildren(path: string): Promise<ListChildrenResponse> {
  return getJson<ListChildrenResponse>(`/vfs/children?path=${encodeURIComponent(path)}`);
}

export function readVfsContent(path: string): Promise<ReadContentResponse> {
  return getJson<ReadContentResponse>(`/vfs/content?path=${encodeURIComponent(path)}`);
}

export function lookupPageNumbers(
  path: string,
  query: string,
  minConfidence: 'explicit' | 'inferred' = 'inferred'
): Promise<LocatorPageNumberMatch[]> {
  const params = new URLSearchParams({ path, query, min_confidence: minConfidence });
  return getJson<LocatorPageNumberMatch[]>(`/locator-index/page-numbers?${params}`);
}

export function lookupSections(
  path: string,
  query: string,
  roles: SectionRole[] = ['begin', 'anchor_template']
): Promise<LocatorSectionMatch[]> {
  const params = new URLSearchParams({ path, query, roles: roles.join(',') });
  return getJson<LocatorSectionMatch[]>(`/locator-index/sections?${params}`);
}

export function dumpLocatorIndex(path: string): Promise<LocatorIndexDump> {
  const params = new URLSearchParams({ path });
  return getJson<LocatorIndexDump>(`/locator-index/dump?${params}`);
}
