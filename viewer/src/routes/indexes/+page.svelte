<script lang="ts">
  import { onMount } from 'svelte';
  import { page } from '$app/state';
  import { getIndexPage, listIndexPages } from '$lib/api';
  import WikitextViewer from '$lib/components/WikitextViewer.svelte';
  import type { IndexPageDetail, IndexPageSummary } from '$lib/types';

  let indexes: IndexPageSummary[] = $state([]);
  let selected: IndexPageDetail | null = $state(null);
  let loadingList = $state(true);
  let loadingPage = $state(false);
  let error = $state('');

  async function loadPage(pk: number): Promise<void> {
    loadingPage = true;
    error = '';
    try {
      selected = await getIndexPage(pk);
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to load index page';
    } finally {
      loadingPage = false;
    }
  }

  async function loadIndexes(): Promise<void> {
    loadingList = true;
    error = '';
    try {
      indexes = await listIndexPages();
      const requestedPk = Number(page.url.searchParams.get('pk'));
      const initial = indexes.find((item) => item.pk === requestedPk) ?? indexes[0];
      if (initial) await loadPage(initial.pk);
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to load index pages';
    } finally {
      loadingList = false;
    }
  }

  onMount(loadIndexes);
</script>

<section class="index-workspace">
  <aside class="sidebar" aria-label="Index pages">
    <div class="brand">
      <p class="eyebrow">Working tree</p>
      <h1>Index pages</h1>
      <p class="count">{indexes.length} cached</p>
    </div>

    {#if loadingList}
      <p class="state">Loading index pages...</p>
    {:else if indexes.length === 0}
      <p class="state">No records found with namespace_role "index".</p>
    {:else}
      <nav class="index-list">
        {#each indexes as item}
          <button
            type="button"
            class:active={selected?.pk === item.pk}
            onclick={() => loadPage(item.pk)}
          >
            <span>{item.title}</span>
            <small>
              {item.body_length.toLocaleString()} chars
              {#if item.page_count}
                / {item.page_count} pages
              {/if}
            </small>
          </button>
        {/each}
      </nav>
    {/if}
  </aside>

  <section class="content" aria-live="polite">
    {#if error}
      <div class="notice">{error}</div>
    {/if}

    {#if loadingPage}
      <div class="empty">Loading wikitext...</div>
    {:else if selected}
      <article>
        <header>
          <p class="eyebrow">Index wikitext</p>
          <h2>{selected.title}</h2>
          <div class="meta">
            <span>PK {selected.pk}</span>
            {#if selected.revid}
              <span>Revision {selected.revid}</span>
            {/if}
            <span>{selected.body_length.toLocaleString()} characters</span>
          </div>
        </header>
        <WikitextViewer content={selected.body} />
      </article>
    {:else}
      <div class="empty">Select an Index page to inspect its cached body.</div>
    {/if}
  </section>
</section>

<style>
  .index-workspace {
    display: grid;
    grid-template-columns: minmax(18rem, 26rem) minmax(0, 1fr);
    gap: clamp(1rem, 3vw, 2rem);
  }

  .sidebar {
    border: 1px solid rgba(72, 49, 31, 0.18);
    border-radius: 24px;
    background: rgba(255, 248, 230, 0.72);
    padding: 1.4rem;
  }

  .brand {
    margin-bottom: 2rem;
  }

  .index-list {
    display: grid;
    gap: 0.75rem;
  }

  .index-list button {
    width: 100%;
    cursor: pointer;
    border: 1px solid rgba(87, 58, 37, 0.2);
    border-radius: 18px;
    background: rgba(255, 252, 240, 0.64);
    color: inherit;
    padding: 1rem;
    text-align: left;
    transition: transform 160ms ease, border-color 160ms ease, background 160ms ease;
  }

  .index-list button:hover,
  .index-list button.active {
    transform: translateY(-1px);
    border-color: #9c5632;
    background: #fff7e6;
  }

  .index-list span,
  .index-list small {
    display: block;
  }

  .index-list span {
    font-weight: 700;
  }

  .index-list small {
    margin-top: 0.45rem;
    color: #73583d;
    font-family: "Avenir Next", "Gill Sans", sans-serif;
  }

  .content {
    min-width: 0;
  }

  article {
    animation: enter 260ms ease both;
  }

  header {
    margin-bottom: 1.5rem;
  }

  @media (max-width: 860px) {
    .index-workspace {
      grid-template-columns: 1fr;
    }
  }
</style>
