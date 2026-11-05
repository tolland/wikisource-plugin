<script lang="ts">
  import { onMount } from 'svelte';
  import {
    createFetch,
    listFetchRequests,
    listSites,
    retryFetches,
    startBackgroundDrain
  } from '$lib/api';
  import { EventFeed } from '$lib/eventFeed.svelte';
  import ActionButton from '$lib/components/ActionButton.svelte';
  import FormRow from '$lib/components/FormRow.svelte';
  import Notice from '$lib/components/Notice.svelte';
  import PageHeading from '$lib/components/PageHeading.svelte';
  import SelectField from '$lib/components/SelectField.svelte';
  import SiteSelect from '$lib/components/SiteSelect.svelte';
  import TextField from '$lib/components/TextField.svelte';
  import { siteLabel } from '$lib/format';
  import type { ChangeEvent, FetchKind, FetchRequest, FetchResponse, FetchStatus, Site } from '$lib/types';

  let title = $state('Index:');
  let sites: Site[] = $state([]);
  let selectedSitePk: number | null = $state(null);
  let kind: FetchKind = $state('single');
  let depth = $state(0);
  let revisions = $state(1);
  let loadingSites = $state(true);
  let loading = $state(false);
  let error = $state('');
  let result: FetchResponse | null = $state(null);
  let drainAfterQueue = $state(true);

  type Tab = 'feed' | 'failures' | 'queue';
  let tab: Tab = $state('feed');
  let problemsOnly = $state(false);
  let queueFilter: FetchStatus | '' = $state('');
  let requests: FetchRequest[] = $state([]);
  let failures: FetchRequest[] = $state([]);
  let busy = $state(false);
  let notice = $state('');

  // Request lists are refetched when the feed says something changed, at most
  // once per burst: a book draining is hundreds of events a minute.
  let refreshTimer: ReturnType<typeof setTimeout> | undefined;
  function scheduleRefresh(): void {
    clearTimeout(refreshTimer);
    refreshTimer = setTimeout(() => void refreshLists(), 400);
  }

  const feed = new EventFeed((event: ChangeEvent) => {
    if (event.topic === 'fetch' || event.kind === 'drain_finished') scheduleRefresh();
  });

  const sitesByPk = $derived(new Map(sites.map((site) => [site.pk, site])));
  const failureCount = $derived(feed.counts.error ?? failures.length);
  const shownEvents = $derived(
    (problemsOnly
      ? feed.events.filter((event) => event.level !== 'info')
      : feed.events
    )
      .slice()
      .reverse()
  );

  const selectedSite = $derived(sites.find((site) => site.pk === selectedSitePk) ?? null);

  async function loadSites(): Promise<void> {
    loadingSites = true;
    error = '';
    try {
      sites = await listSites();
      selectedSitePk = sites[0]?.pk ?? null;
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to load sites';
    } finally {
      loadingSites = false;
    }
  }

  async function submitFetch(): Promise<void> {
    // The site is named by its registered label, not by family/code/api_url:
    // nothing conjures a site from a fetch request's parameters, so a fetch
    // against an unregistered wiki is a 404 rather than a new Site row.
    const label = selectedSite?.label;
    if (!label) {
      error = 'Register a site first -- a fetch names a registered wiki by label.';
      return;
    }
    loading = true;
    error = '';
    result = null;
    try {
      result = await createFetch({ title, label, kind, depth, revisions });
      if (drainAfterQueue) await drain();
    } catch (err) {
      error = err instanceof Error ? err.message : 'Fetch request failed';
    } finally {
      loading = false;
    }
  }

  async function refreshLists(): Promise<void> {
    try {
      [requests, failures] = await Promise.all([
        listFetchRequests(queueFilter ? { status: queueFilter } : {}),
        listFetchRequests({ status: 'error', limit: 500 })
      ]);
    } catch (err) {
      notice = err instanceof Error ? err.message : 'Failed to load fetch requests';
    }
  }

  async function drain(): Promise<void> {
    notice = '';
    try {
      const started = await startBackgroundDrain();
      if (!started.started) notice = 'A drain is already running.';
    } catch (err) {
      notice = err instanceof Error ? err.message : 'Failed to start the drain';
    }
  }

  /** Requeue and drain: a retry that does not run is only half a retry. */
  async function retry(pks?: number[]): Promise<void> {
    busy = true;
    notice = '';
    try {
      const { requeued } = await retryFetches(pks);
      notice = `Requeued ${requeued.length} request(s).`;
      if (requeued.length > 0) await drain();
      await refreshLists();
    } catch (err) {
      notice = err instanceof Error ? err.message : 'Retry failed';
    } finally {
      busy = false;
    }
  }

  function clock(iso: string | null | undefined): string {
    return iso ? new Date(iso.endsWith('Z') || iso.includes('+') ? iso : `${iso}Z`).toLocaleTimeString() : '';
  }

  function siteName(sitePk: number | null | undefined): string {
    const site = sitePk == null ? undefined : sitesByPk.get(sitePk);
    return site ? siteLabel(site) : '';
  }

  const FEED_STATE: Record<string, string> = {
    connecting: 'connecting...',
    live: 'live',
    reconnecting: 'reconnecting...',
    closed: 'closed'
  };

  $effect(() => {
    // Re-list when the filter changes.
    queueFilter;
    void refreshLists();
  });

  onMount(() => {
    void loadSites();
    feed.start();
    return () => {
      feed.stop();
      clearTimeout(refreshTimer);
    };
  });
</script>

<PageHeading eyebrow="Checkout" title="Fetch wikitext into the local cache.">
  <p class="description">
    Queues a fetch, then drains the queue on the server. Results and failures
    arrive on the live feed below as the worker records them, so a dropped
    connection here loses nothing.
  </p>
</PageHeading>

<section class="status" aria-label="Queue status">
  <span class="pill feed-{feed.state}" title={feed.polling ? 'websocket unavailable; polling' : ''}>
    {FEED_STATE[feed.state]}{feed.polling ? ' (polling)' : ''}
  </span>
  <span class="count"><b>{feed.counts.pending ?? 0}</b> pending</span>
  <span class="count"><b>{feed.counts.in_progress ?? 0}</b> in progress</span>
  <span class="count"><b>{feed.counts.done ?? 0}</b> done</span>
  <span class="count" class:bad={failureCount > 0}><b>{failureCount}</b> failed</span>
  <span class="grow"></span>
  {#if feed.draining}<span class="pill draining">draining...</span>{/if}
  <ActionButton variant="secondary" disabled={feed.draining} onclick={drain}>Drain queue</ActionButton>
  <ActionButton variant="secondary" disabled={busy || failureCount === 0} onclick={() => retry()}>
    Retry all failed
  </ActionButton>
</section>

{#if notice}
  <p class="state">{notice}</p>
{/if}

<form class="fetch-form" onsubmit={(event) => { event.preventDefault(); void submitFetch(); }}>
  <TextField label="Title" bind:value={title} required placeholder="Index:Example.djvu" />

  {#if loadingSites}
    <p class="state">Loading sites...</p>
  {:else if sites.length > 1}
    <SiteSelect {sites} bind:value={selectedSitePk} />
  {:else if sites.length === 1}
    <div class="site-summary">
      <span>Site</span>
      <strong>{siteLabel(sites[0])}</strong>
      <small>{sites[0].api_url ?? `${sites[0].family}:${sites[0].code}`}</small>
    </div>
  {:else}
    <Notice>No sites registered. Add one on the Sites page before fetching.</Notice>
  {/if}

  <FormRow>
    <SelectField label="Kind" bind:value={kind}>
      <option value="single">single</option>
      <option value="index">index</option>
    </SelectField>
    <TextField label="Depth" type="number" min="0" max="3" bind:value={depth} />
    <TextField label="Revisions" type="number" min="1" max="500" bind:value={revisions} />
  </FormRow>

  <p class="hint">
    <strong>Revisions</strong> is how far back from the head to store. 1 is a normal
    fetch -- the head is all the editor and the VFS need. More fills in history for
    the cross-site anchor search, which cannot find a match at the head when one side
    was imported from an older revision of the other. Index fan-out children inherit
    it.
  </p>

  <div class="submit-row">
    <ActionButton type="submit" disabled={loading}>
      {loading ? 'Queueing...' : 'Fetch into cache'}
    </ActionButton>
    <label class="check">
      <input type="checkbox" bind:checked={drainAfterQueue} /> start draining straight away
    </label>
  </div>
</form>

{#if error}
  <Notice>{error}</Notice>
{/if}

{#if result}
  <p class="state">
    Queued #{result.request.pk} <strong>{result.request.title}</strong>
    ({result.request.status}). Watch it below.
  </p>
{/if}

<nav class="tabs" aria-label="Fetch views">
  <button class:active={tab === 'feed'} onclick={() => (tab = 'feed')}>Live feed</button>
  <button class:active={tab === 'failures'} onclick={() => (tab = 'failures')}>
    Failures{failures.length ? ` (${failures.length})` : ''}
  </button>
  <button class:active={tab === 'queue'} onclick={() => (tab = 'queue')}>Queue</button>
</nav>

{#if tab === 'feed'}
  <label class="check"><input type="checkbox" bind:checked={problemsOnly} /> problems only</label>
  {#if shownEvents.length === 0}
    <p class="state">Nothing yet. Events appear here as workers record them.</p>
  {/if}
  <ul class="feed">
    {#each shownEvents as event (event.pk)}
      <li class="lvl-{event.level}">
        <details>
          <summary>
            <time>{clock(event.at)}</time>
            <span class="kind">{event.kind.replace('_', ' ')}</span>
            {#if event.title}<span class="title">{event.title}</span>{/if}
            <span class="msg">{event.message ?? ''}</span>
          </summary>
          <dl class="meta">
            {#if event.request_pk}<div><dt>request</dt><dd>#{event.request_pk}</dd></div>{/if}
            {#if event.site_pk}<div><dt>site</dt><dd>{siteName(event.site_pk) || event.site_pk}</dd></div>{/if}
            {#if event.failure_kind}<div><dt>failure</dt><dd>{event.failure_kind}</dd></div>{/if}
            {#if event.http_status}<div><dt>HTTP</dt><dd>{event.http_status}</dd></div>{/if}
            {#if event.retry_after}<div><dt>retry after</dt><dd>{event.retry_after}s</dd></div>{/if}
          </dl>
          {#if event.detail}<pre>{event.detail}</pre>{/if}
        </details>
      </li>
    {/each}
  </ul>
{:else if tab === 'failures'}
  {#if failures.length === 0}
    <p class="state">No failed requests.</p>
  {/if}
  <ul class="rows">
    {#each failures as row (row.pk)}
      <li>
        <div>
          <strong>{row.title}</strong>
          <small>#{row.pk} - {siteName(row.site_pk)} - {row.kind}</small>
          <p class="err">{row.error_message}</p>
        </div>
        <ActionButton variant="secondary" disabled={busy} onclick={() => retry([row.pk])}>Retry</ActionButton>
      </li>
    {/each}
  </ul>
{:else}
  <label class="check">
    status
    <select bind:value={queueFilter}>
      <option value="">all</option>
      <option value="pending">pending</option>
      <option value="in_progress">in progress</option>
      <option value="done">done</option>
      <option value="error">error</option>
    </select>
  </label>
  <ul class="rows">
    {#each requests as row (row.pk)}
      <li>
        <div>
          <strong>{row.title}</strong>
          <small>
            #{row.pk}{row.parent_pk ? ` of #${row.parent_pk}` : ''} - {siteName(row.site_pk)} - {row.kind}
            {#if row.progress_total} - {row.progress_done ?? 0}/{row.progress_total}{/if}
          </small>
        </div>
        <span class="pill st-{row.status}">{row.status.replace('_', ' ')}</span>
      </li>
    {/each}
  </ul>
{/if}

<style>
  .hint {
    max-width: 46rem;
    color: #73583d;
    font-size: 0.84rem;
  }

  .description {
    color: #594430;
    font-size: 1.1rem;
    line-height: 1.55;
  }

  .fetch-form,
  .result {
    border: 1px solid rgba(72, 49, 31, 0.18);
    border-radius: 24px;
    background: rgba(255, 252, 240, 0.72);
    box-shadow: 0 20px 60px rgba(62, 44, 30, 0.12);
    margin-top: 1.5rem;
    max-width: 48rem;
    padding: 1.3rem;
  }

  .fetch-form {
    display: grid;
    gap: 1rem;
  }

  .site-summary {
    border: 1px solid rgba(72, 49, 31, 0.16);
    border-radius: 14px;
    background: rgba(255, 253, 245, 0.68);
    display: grid;
    gap: 0.25rem;
    padding: 0.85rem 0.95rem;
  }

  .site-summary strong,
  .site-summary small {
    display: block;
  }

  .site-summary small {
    color: #73583d;
    font-family: "Avenir Next", "Gill Sans", sans-serif;
    font-size: 0.82rem;
  }

  .site-summary span,
  dt {
    color: #73583d;
    font-family: "Avenir Next", "Gill Sans", sans-serif;
    font-size: 0.74rem;
    font-weight: 800;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }

  .submit-row {
    justify-self: start;
  }

  dl {
    display: grid;
    gap: 0.8rem;
    margin: 1rem 0 0;
  }

  dl div {
    border-top: 1px solid rgba(72, 49, 31, 0.14);
    padding-top: 0.8rem;
  }

  dd {
    margin: 0.2rem 0 0;
  }

  .status {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.6rem 1.1rem;
    margin-top: 1.2rem;
    font-family: "Avenir Next", "Gill Sans", sans-serif;
    font-size: 0.85rem;
  }
  .status .grow {
    flex: 1;
  }
  .count.bad b {
    color: #a3262a;
  }
  .pill {
    border-radius: 999px;
    border: 1px solid rgba(72, 49, 31, 0.25);
    padding: 0.15rem 0.6rem;
    font-size: 0.74rem;
    font-weight: 800;
    letter-spacing: 0.06em;
    text-transform: uppercase;
  }
  .feed-live,
  .st-done {
    background: #dcebd0;
  }
  .feed-reconnecting,
  .feed-connecting,
  .draining,
  .st-in_progress {
    background: #f6e6b8;
  }
  .st-error {
    background: #f1c9c4;
  }
  .submit-row {
    display: flex;
    align-items: center;
    gap: 1rem;
  }
  .check {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    font-size: 0.82rem;
    color: #73583d;
  }
  .tabs {
    display: flex;
    gap: 0.4rem;
    margin: 1.6rem 0 0.8rem;
  }
  .tabs button {
    cursor: pointer;
    border: 1px solid rgba(72, 49, 31, 0.2);
    border-radius: 999px;
    background: transparent;
    padding: 0.4rem 0.9rem;
    font-family: "Avenir Next", "Gill Sans", sans-serif;
    font-size: 0.78rem;
    font-weight: 700;
    color: #73583d;
  }
  .tabs button.active {
    background: #9c5632;
    color: #fff8e6;
  }
  ul.feed,
  ul.rows {
    list-style: none;
    margin: 0.6rem 0 0;
    padding: 0;
    max-width: 62rem;
  }
  .feed li,
  .rows li {
    border-top: 1px solid rgba(72, 49, 31, 0.14);
    padding: 0.5rem 0.2rem;
  }
  .rows li {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 1rem;
  }
  .rows small {
    display: block;
    color: #73583d;
  }
  .err {
    margin: 0.2rem 0 0;
    color: #a3262a;
    font-size: 0.84rem;
  }
  summary {
    cursor: pointer;
    display: flex;
    flex-wrap: wrap;
    gap: 0.2rem 0.7rem;
    align-items: baseline;
    font-size: 0.86rem;
  }
  summary time {
    color: #73583d;
    font-variant-numeric: tabular-nums;
  }
  summary .kind {
    font-family: "Avenir Next", "Gill Sans", sans-serif;
    font-size: 0.72rem;
    font-weight: 800;
    letter-spacing: 0.06em;
    text-transform: uppercase;
  }
  .lvl-error .kind,
  .lvl-error .msg {
    color: #a3262a;
  }
  .lvl-warning .kind {
    color: #a06a00;
  }
  .meta {
    display: flex;
    flex-wrap: wrap;
    gap: 0.4rem 1.2rem;
    margin: 0.5rem 0 0;
  }
  .meta div {
    border: 0;
    padding: 0;
  }
  pre {
    overflow-x: auto;
    max-height: 18rem;
    margin: 0.5rem 0 0;
    padding: 0.7rem;
    border-radius: 10px;
    background: rgba(72, 49, 31, 0.07);
    font-size: 0.74rem;
  }
</style>
