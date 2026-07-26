<script lang="ts">
  import { onMount } from 'svelte';
  import { page as routePage } from '$app/state';
  import { getPage, listNamespaces, listPages, listSites } from '$lib/api';
  import Notice from '$lib/components/Notice.svelte';
  import PageHeading from '$lib/components/PageHeading.svelte';
  import SiteSelect from '$lib/components/SiteSelect.svelte';
  import WikitextArticle from '$lib/components/WikitextArticle.svelte';
  import { siteLabel } from '$lib/format';
  import type { CachedPage, Site, WikiNamespace } from '$lib/types';

  let sites: Site[] = $state([]);
  let selectedSitePk: number | null = $state(null);
  let namespaces: WikiNamespace[] = $state([]);
  let query = $state('');
  let results: CachedPage[] = $state([]);
  let selectedPage: CachedPage | null = $state(null);
  let loadingSites = $state(true);
  let searching = $state(false);
  let loadingPage = $state(false);
  let error = $state('');
  let searchTimer: ReturnType<typeof setTimeout> | undefined;
  let searchSequence = 0;

  function selectedSite(): Site | undefined {
    return sites.find((site) => site.pk === selectedSitePk);
  }

  function titleFragment(value = query): string | null {
    const colon = value.indexOf(':');
    if (colon < 1) return null;

    const namespace = value.slice(0, colon).trim().toLocaleLowerCase();
    const knownNamespace = namespaces.some((item) =>
      [item.local_name, item.canonical_name].some(
        (name) => name && name.toLocaleLowerCase() === namespace
      )
    );
    if (!knownNamespace) return null;

    const fragment = value.slice(colon + 1).trimStart();
    return fragment.length >= 3 ? fragment : null;
  }

  function namespaceSuggestions(): WikiNamespace[] {
    if (query.includes(':')) return [];
    const prefix = query.trim().toLocaleLowerCase();
    if (prefix.length < 2) return [];
    return namespaces.filter((item) =>
      [item.local_name, item.canonical_name].some((name) =>
        name.toLocaleLowerCase().startsWith(prefix)
      )
    );
  }

  function completeNamespace(namespace: WikiNamespace): void {
    query = `${namespace.local_name || namespace.canonical_name}:`;
    results = [];
  }

  function searchHint(): string {
    if (!query.includes(':')) return 'Type at least 2 letters to complete the namespace first.';
    const namespace = query.slice(0, query.indexOf(':')).trim().toLocaleLowerCase();
    if (!namespaces.some((item) => [item.local_name, item.canonical_name]
      .some((name) => name && name.toLocaleLowerCase() === namespace))) {
      return 'Choose a namespace from the suggestions.';
    }
    return 'Type at least 3 characters of the title after the namespace.';
  }

  async function searchPages(): Promise<void> {
    const trimmed = query.trim();
    if (selectedSitePk == null || titleFragment(trimmed) == null) {
      results = [];
      searching = false;
      return;
    }

    const sequence = ++searchSequence;
    searching = true;
    error = '';
    try {
      const params = new URLSearchParams({
        site_pk: String(selectedSitePk),
        title_contains: trimmed,
        limit: '12'
      });
      const matches = await listPages(params);
      if (sequence !== searchSequence) return;
      results = matches;

      const exact = trimmed ? results.find((item) => item.title === trimmed) : null;
      if (exact) {
        await openPage(exact.pk);
      }
    } catch (err) {
      if (sequence !== searchSequence) return;
      error = err instanceof Error ? err.message : 'Failed to search pages';
    } finally {
      if (sequence === searchSequence) searching = false;
    }
  }

  function scheduleSearch(): void {
    if (searchTimer) clearTimeout(searchTimer);
    results = [];
    searchSequence += 1;
    if (titleFragment() == null) {
      searching = false;
      return;
    }
    searchTimer = setTimeout(() => void searchPages(), 250);
  }

  async function changeSite(): Promise<void> {
    selectedPage = null;
    query = '';
    results = [];
    namespaces = selectedSitePk == null ? [] : await listNamespaces(selectedSitePk);
  }

  async function openPage(pk: number): Promise<void> {
    loadingPage = true;
    error = '';
    try {
      selectedPage = await getPage(pk);
      query = selectedPage.title;
      results = [];
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
      namespaces = selectedSitePk == null ? [] : await listNamespaces(selectedSitePk);
      query = requestedTitle;

      if (requestedPagePk) {
        await openPage(requestedPagePk);
      } else if (selectedSitePk != null && titleFragment(requestedTitle) != null) {
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
  <section class="search-pane" aria-label="Page search">
    <div class="brand">
      <PageHeading
        eyebrow="Cache object"
        title="Pages"
        count={selectedSite() ? siteLabel(selectedSite() as Site) : ''}
      />
    </div>

    {#if error}
      <Notice>{error}</Notice>
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
      {:else}
        <SiteSelect {sites} bind:value={selectedSitePk} onchange={() => void changeSite()} />
      {/if}

      <label class="title-field">
        <span>Title</span>
        <input
          bind:value={query}
          oninput={scheduleSearch}
          name="title"
          placeholder="Page:Tra..."
          type="search"
          autocomplete="off"
          aria-describedby="title-hint"
          aria-controls="title-suggestions"
          role="combobox"
          aria-autocomplete="list"
          aria-expanded={results.length > 0 || namespaceSuggestions().length > 0}
        />
        <small id="title-hint">{searchHint()}</small>
        {#if namespaceSuggestions().length > 0}
          <div id="title-suggestions" class="suggestions" role="listbox">
            {#each namespaceSuggestions() as namespace}
              <button
                type="button"
                role="option"
                aria-selected="false"
                onclick={() => completeNamespace(namespace)}
              >
                {namespace.local_name || namespace.canonical_name}:
              </button>
            {/each}
          </div>
        {:else if results.length > 0}
          <div id="title-suggestions" class="suggestions" role="listbox">
            {#each results as item}
              <button
                type="button"
                role="option"
                aria-selected={selectedPage?.pk === item.pk}
                onclick={() => openPage(item.pk)}
              >
                {item.title}
              </button>
            {/each}
          </div>
        {/if}
      </label>

      <button
        class="submit"
        type="submit"
        disabled={selectedSitePk == null || titleFragment() == null || searching}
      >
        {searching ? 'Searching...' : 'Search'}
      </button>
    </form>
  </section>

  <section class="page-content" aria-live="polite">
    {#if loadingPage}
      <div class="empty">Loading page...</div>
    {:else if selectedPage}
      <WikitextArticle
        eyebrow={selectedPage.namespace_role}
        title={selectedPage.title}
        content={selectedPage.text}
      >
        {#snippet meta()}
          <span>PK {selectedPage?.pk}</span>
          {#if selectedPage?.content_model}
            <span>{selectedPage.content_model}</span>
          {/if}
          {#if selectedPage?.revid}
            <span>Revision {selectedPage.revid}</span>
          {/if}
          {#if selectedPage?.text}
            <span>{selectedPage.text.length.toLocaleString()} characters</span>
          {/if}
        {/snippet}
      </WikitextArticle>
    {:else}
      <div class="empty">Complete a title above to view a cached page.</div>
    {/if}
  </section>
</section>

<style>
  .page-workspace {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
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
    grid-template-columns: minmax(12rem, 18rem) minmax(18rem, 1fr) auto;
    align-items: end;
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

  input {
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

  .submit {
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

  .submit:disabled {
    cursor: default;
    opacity: 0.55;
  }

  .title-field {
    position: relative;
  }

  .title-field > small {
    color: #73583d;
    font-size: 0.76rem;
  }

  .suggestions {
    position: absolute;
    z-index: 10;
    top: calc(100% + 0.35rem);
    right: 0;
    left: 0;
    display: grid;
    gap: 0.2rem;
    max-height: 20rem;
    overflow-y: auto;
    border: 1px solid rgba(87, 58, 37, 0.22);
    border-radius: 12px;
    background: #fffaf0;
    box-shadow: 0 12px 30px rgba(72, 49, 31, 0.16);
    padding: 0.35rem;
  }

  .suggestions button {
    border: 1px solid rgba(87, 58, 37, 0.18);
    border-radius: 12px;
    background: rgba(255, 252, 240, 0.6);
    color: inherit;
    padding: 0.75rem 0.9rem;
    text-align: left;
    transition: border-color 120ms, background 120ms, transform 120ms;
  }

  .suggestions button:hover,
  .suggestions button:focus-visible {
    border-color: #9c5632;
    background: #fff7e6;
    transform: translateY(-1px);
  }

  .page-content {
    min-width: 0;
  }

  @media (max-width: 920px) {
    .search-form {
      grid-template-columns: 1fr;
    }
  }
</style>
