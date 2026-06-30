<script lang="ts">
  import { onMount } from 'svelte';
  import { page as routePage } from '$app/state';
  import { getPage, listPages, listSites } from '$lib/api';
  import WikitextViewer from '$lib/components/WikitextViewer.svelte';
  import type { CachedPage, Site } from '$lib/types';

  let sites: Site[] = $state([]);
  let selectedSitePk: number | null = $state(null);
  let query = $state('');
  let results: CachedPage[] = $state([]);
  let selectedPage: CachedPage | null = $state(null);
  let loadingSites = $state(true);
  let searching = $state(false);
  let loadingPage = $state(false);
  let error = $state('');

  function siteLabel(site: Site): string {
    return site.label || `${site.family}:${site.code}`;
  }

  function selectedSite(): Site | undefined {
    return sites.find((site) => site.pk === selectedSitePk);
  }

  async function searchPages(): Promise<void> {
    if (selectedSitePk == null) return;

    searching = true;
    error = '';
    try {
      const params = new URLSearchParams({
        site_pk: String(selectedSitePk),
        limit: '50'
      });
      const trimmed = query.trim();
      if (trimmed) params.set('title_contains', trimmed);
      results = await listPages(params);

      const exact = trimmed ? results.find((item) => item.title === trimmed) : null;
      if (exact) {
        await openPage(exact.pk);
      } else if (results.length === 1) {
        await openPage(results[0].pk);
      }
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to search pages';
    } finally {
      searching = false;
    }
  }

  async function openPage(pk: number): Promise<void> {
    loadingPage = true;
    error = '';
    try {
      selectedPage = await getPage(pk);
      query = selectedPage.title;
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to load page';
    } finally {
      loadingPage = false;
    }
  }

  async function loadSites(): Promise<void> {
    loadingSites = true;
    error = '';
    try {
      sites = await listSites();
      const requestedSitePk = Number(routePage.url.searchParams.get('site_pk'));
      const requestedPagePk = Number(routePage.url.searchParams.get('page_pk'));
      const requestedTitle = routePage.url.searchParams.get('title') ?? '';
      selectedSitePk =
        sites.find((site) => site.pk === requestedSitePk)?.pk ?? sites[0]?.pk ?? null;
      query = requestedTitle;

      if (requestedPagePk) {
        await openPage(requestedPagePk);
      } else if (selectedSitePk != null) {
        await searchPages();
      }
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to load sites';
    } finally {
      loadingSites = false;
    }
  }

  onMount(loadSites);
</script>

<section class="page-workspace">
  <aside class="search-pane" aria-label="Page search">
    <div class="brand">
      <p class="eyebrow">Cache object</p>
      <h1>Pages</h1>
      {#if selectedSite()}
        <p class="count">{siteLabel(selectedSite() as Site)}</p>
      {/if}
    </div>

    {#if error}
      <div class="notice">{error}</div>
    {/if}

    <form
      class="search-form"
      onsubmit={(event) => {
        event.preventDefault();
        void searchPages();
      }}
    >
      {#if loadingSites}
        <p class="state">Loading sites...</p>
      {:else if sites.length === 0}
        <p class="state">No sites have been fetched yet.</p>
      {:else if sites.length > 1}
        <label>
          <span>Site</span>
          <select bind:value={selectedSitePk} onchange={() => searchPages()}>
            {#each sites as site}
              <option value={site.pk}>{siteLabel(site)}</option>
            {/each}
          </select>
        </label>
      {/if}

      <label>
        <span>Title</span>
        <input
          bind:value={query}
          name="title"
          placeholder="Page:, Template:, Book:, ..."
          type="search"
        />
      </label>

      <button type="submit" disabled={selectedSitePk == null || searching}>
        {searching ? 'Searching...' : 'Search'}
      </button>
    </form>

    {#if results.length > 0}
      <nav class="result-list" aria-label="Search results">
        {#each results as item}
          <button
            type="button"
            class:active={selectedPage?.pk === item.pk}
            onclick={() => openPage(item.pk)}
          >
            <span>{item.title}</span>
            <small>
              {item.content_model ?? 'unknown'}
              {#if item.revid}
                / r{item.revid}
              {/if}
            </small>
          </button>
        {/each}
      </nav>
    {:else if !loadingSites && !searching}
      <p class="state">No matching pages.</p>
    {/if}
  </aside>

  <section class="page-content" aria-live="polite">
    {#if loadingPage}
      <div class="empty">Loading page...</div>
    {:else if selectedPage}
      <article>
        <header>
          <p class="eyebrow">{selectedPage.namespace_role}</p>
          <h2>{selectedPage.title}</h2>
          <div class="meta">
            <span>PK {selectedPage.pk}</span>
            {#if selectedPage.content_model}
              <span>{selectedPage.content_model}</span>
            {/if}
            {#if selectedPage.revid}
              <span>Revision {selectedPage.revid}</span>
            {/if}
            {#if selectedPage.text}
              <span>{selectedPage.text.length.toLocaleString()} characters</span>
            {/if}
          </div>
        </header>
        <WikitextViewer content={selectedPage.text} />
      </article>
    {:else}
      <div class="empty">Select a cached page.</div>
    {/if}
  </section>
</section>

<style>
  .page-workspace {
    display: grid;
    grid-template-columns: minmax(20rem, 34rem) minmax(0, 1fr);
    gap: clamp(1rem, 3vw, 2rem);
  }

  .search-pane {
    border: 1px solid rgba(72, 49, 31, 0.18);
    border-radius: 24px;
    background: rgba(255, 248, 230, 0.72);
    padding: 1.4rem;
  }

  .brand {
    margin-bottom: 1.4rem;
  }

  .search-form {
    display: grid;
    gap: 0.9rem;
  }

  label {
    display: grid;
    gap: 0.35rem;
  }

  label span {
    color: #73583d;
    font-family: "Avenir Next", "Gill Sans", sans-serif;
    font-size: 0.72rem;
    font-weight: 800;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }

  input,
  select {
    width: 100%;
    border: 1px solid rgba(87, 58, 37, 0.22);
    border-radius: 12px;
    background: rgba(255, 252, 240, 0.82);
    color: inherit;
    font: inherit;
    padding: 0.8rem 0.9rem;
  }

  button {
    cursor: pointer;
  }

  .search-form button {
    border: 0;
    border-radius: 12px;
    background: #9c5632;
    color: #fff8e6;
    font-family: "Avenir Next", "Gill Sans", sans-serif;
    font-size: 0.82rem;
    font-weight: 800;
    letter-spacing: 0.06em;
    padding: 0.85rem 1rem;
    text-transform: uppercase;
  }

  .search-form button:disabled {
    cursor: default;
    opacity: 0.55;
  }

  .result-list {
    display: grid;
    gap: 0.55rem;
    margin-top: 1.25rem;
  }

  .result-list button {
    border: 1px solid rgba(87, 58, 37, 0.18);
    border-radius: 12px;
    background: rgba(255, 252, 240, 0.6);
    color: inherit;
    padding: 0.75rem 0.9rem;
    text-align: left;
    transition: border-color 120ms, background 120ms, transform 120ms;
  }

  .result-list button:hover,
  .result-list button.active {
    border-color: #9c5632;
    background: #fff7e6;
    transform: translateY(-1px);
  }

  .result-list span,
  .result-list small {
    display: block;
  }

  .result-list span {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-weight: 700;
  }

  .result-list small {
    margin-top: 0.35rem;
    color: #73583d;
    font-family: "Avenir Next", "Gill Sans", sans-serif;
    font-size: 0.72rem;
  }

  .page-content {
    min-width: 0;
  }

  article {
    animation: enter 260ms ease both;
  }

  header {
    margin-bottom: 1.5rem;
  }

  h2 {
    word-break: break-word;
  }

  @media (max-width: 920px) {
    .page-workspace {
      grid-template-columns: 1fr;
    }
  }
</style>
