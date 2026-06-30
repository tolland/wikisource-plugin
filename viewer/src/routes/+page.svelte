<script lang="ts">
  import { onMount } from 'svelte';
  import { listIndexPages, listSites } from '$lib/api';
  import type { IndexPageSummary, Site } from '$lib/types';

  let sites: Site[] = $state([]);
  let indexes: IndexPageSummary[] = $state([]);
  let loading = $state(true);
  let error = $state('');

  async function loadWorkspace(): Promise<void> {
    loading = true;
    error = '';
    try {
      [sites, indexes] = await Promise.all([listSites(), listIndexPages()]);
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to load workspace';
    } finally {
      loading = false;
    }
  }

  onMount(loadWorkspace);
</script>

<section class="hero">
  <p class="eyebrow">Manual proofread workflow</p>
  <h1>Inspect the local cache before committing upstream.</h1>
  <p class="lede">
    Treat fetched Wikisource pages like a working tree: fetch remote wikitext,
    inspect cached records, review edits from the VFS, then prepare commits back
    to MediaWiki.
  </p>
</section>

{#if error}
  <div class="notice">{error}</div>
{/if}

<section class="cards" aria-label="Cache overview">
  <a class="card" href="/fetch">
    <span class="card-kicker">Checkout</span>
    <strong>Fetch pages</strong>
    <small>Pull Index: and Page: records into SQLite.</small>
  </a>
  <a class="card" href="/indexes">
    <span class="card-kicker">Working tree</span>
    <strong>{loading ? '...' : indexes.length} Index pages</strong>
    <small>Open cached proofread indexes and inspect their source.</small>
  </a>
  <a class="card" href="/vfs">
    <span class="card-kicker">Editor view</span>
    <strong>Virtual files</strong>
    <small>Browse the VFS projection exposed to the IntelliJ plugin.</small>
  </a>
</section>

<section class="panel-grid">
  <article class="panel">
    <header>
      <p class="eyebrow">Sites</p>
      <h2>Configured wikis</h2>
    </header>
    {#if loading}
      <p class="state">Loading sites...</p>
    {:else if sites.length === 0}
      <p class="state">No sites have been fetched yet.</p>
    {:else}
      <ul class="record-list">
        {#each sites as site}
          <li>
            <strong>{site.family}:{site.code}</strong>
            <span>{site.api_url ?? site.host ?? 'local cache site'}</span>
          </li>
        {/each}
      </ul>
    {/if}
  </article>

  <article class="panel">
    <header>
      <p class="eyebrow">Recent indexes</p>
      <h2>Cached work</h2>
    </header>
    {#if loading}
      <p class="state">Loading indexes...</p>
    {:else if indexes.length === 0}
      <p class="state">No Index: pages are cached.</p>
    {:else}
      <ul class="record-list">
        {#each indexes.slice(0, 8) as page}
          <li>
            <a href={`/indexes?pk=${page.pk}`}>{page.title}</a>
            <span>{page.body_length.toLocaleString()} chars</span>
          </li>
        {/each}
      </ul>
    {/if}
  </article>
</section>

<style>
  .hero {
    max-width: 64rem;
  }

  .hero h1 {
    max-width: 58rem;
    font-size: clamp(2.8rem, 7vw, 6.8rem);
    letter-spacing: -0.06em;
  }

  .lede {
    max-width: 52rem;
    color: #594430;
    font-size: clamp(1.05rem, 2vw, 1.35rem);
    line-height: 1.55;
  }

  .cards {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 1rem;
    margin: 2rem 0;
  }

  .card,
  .panel {
    border: 1px solid rgba(72, 49, 31, 0.18);
    border-radius: 24px;
    background: rgba(255, 252, 240, 0.68);
    box-shadow: 0 20px 60px rgba(62, 44, 30, 0.12);
  }

  .card {
    color: inherit;
    min-height: 10rem;
    padding: 1.3rem;
    text-decoration: none;
    transition: transform 160ms ease, border-color 160ms ease;
  }

  .card:hover {
    transform: translateY(-2px);
    border-color: #9c5632;
  }

  .card strong,
  .card small,
  .card-kicker {
    display: block;
  }

  .card strong {
    margin-top: 0.5rem;
    font-size: 1.45rem;
  }

  .card small {
    margin-top: 0.7rem;
    color: #73583d;
    line-height: 1.4;
  }

  .card-kicker {
    color: #9c5632;
    font-family: "Avenir Next", "Gill Sans", sans-serif;
    font-size: 0.72rem;
    font-weight: 800;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }

  .panel-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 1rem;
  }

  .panel {
    padding: 1.3rem;
  }

  .panel h2 {
    font-size: clamp(1.6rem, 3vw, 2.5rem);
  }

  .record-list {
    display: grid;
    gap: 0.65rem;
    list-style: none;
    margin: 1rem 0 0;
    padding: 0;
  }

  .record-list li {
    border-top: 1px solid rgba(72, 49, 31, 0.12);
    display: grid;
    gap: 0.25rem;
    padding-top: 0.65rem;
  }

  .record-list a,
  .record-list strong {
    color: #241b13;
    font-weight: 800;
    text-decoration: none;
  }

  .record-list a:hover {
    color: #9c5632;
  }

  .record-list span {
    color: #73583d;
    font-family: "Avenir Next", "Gill Sans", sans-serif;
    font-size: 0.82rem;
  }

  @media (max-width: 880px) {
    .cards,
    .panel-grid {
      grid-template-columns: 1fr;
    }
  }
</style>
