<script>
  import VfsBrowser from './VfsBrowser.svelte';

  let activeTab = $state('indexes');

  // ---- Index viewer state ----
  let indexes = $state([]);
  let selected = $state(null);
  let loadingList = $state(true);
  let loadingPage = $state(false);
  let error = $state('');

  async function loadIndexes() {
    loadingList = true;
    error = '';
    try {
      const response = await fetch('/api/viewer/indexes');
      if (!response.ok) throw new Error(`Failed to load index pages (${response.status})`);
      indexes = await response.json();
      if (indexes.length > 0) await loadPage(indexes[0].pk);
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to load index pages';
    } finally {
      loadingList = false;
    }
  }

  async function loadPage(pk) {
    loadingPage = true;
    error = '';
    try {
      const response = await fetch(`/api/viewer/indexes/${pk}`);
      if (!response.ok) throw new Error(`Failed to load page (${response.status})`);
      selected = await response.json();
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to load page';
    } finally {
      loadingPage = false;
    }
  }

  loadIndexes();
</script>

<svelte:head>
  <title>Wikisource Cache Viewer</title>
</svelte:head>

<div class="app">
  <div class="tab-bar" role="tablist">
    <button
      role="tab"
      aria-selected={activeTab === 'indexes'}
      class:active={activeTab === 'indexes'}
      onclick={() => activeTab = 'indexes'}
    >Index viewer</button>
    <button
      role="tab"
      aria-selected={activeTab === 'vfs'}
      class:active={activeTab === 'vfs'}
      onclick={() => activeTab = 'vfs'}
    >VFS browser</button>
  </div>

  <div class="tab-content">
    {#if activeTab === 'indexes'}
      <main class="shell">
        <section class="sidebar" aria-label="Index pages">
          <div class="brand">
            <p class="eyebrow">SQLite cache</p>
            <h1>Index pages</h1>
            <p class="count">{indexes.length} cached</p>
          </div>

          {#if loadingList}
            <p class="state">Loading index pages...</p>
          {:else if indexes.length === 0}
            <p class="state">No records found with namespace_role "index".</p>
          {:else}
            <nav class="index-list">
              {#each indexes as page}
                <button
                  type="button"
                  class:active={selected?.pk === page.pk}
                  onclick={() => loadPage(page.pk)}
                >
                  <span>{page.title}</span>
                  <small>
                    {page.body_length.toLocaleString()} chars
                    {#if page.page_count}
                      / {page.page_count} pages
                    {/if}
                  </small>
                </button>
              {/each}
            </nav>
          {/if}
        </section>

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
              <div class="wikitext">{selected.body}</div>
            </article>
          {:else}
            <div class="empty">Select an Index page to inspect its cached body.</div>
          {/if}
        </section>
      </main>
    {:else}
      <VfsBrowser />
    {/if}
  </div>
</div>

<style>
  .app {
    display: flex;
    flex-direction: column;
    min-height: 100vh;
  }

  .tab-bar {
    display: flex;
    gap: 0;
    border-bottom: 1px solid rgba(72, 49, 31, 0.22);
    background: rgba(255, 248, 230, 0.9);
    backdrop-filter: blur(10px);
    padding: 0 1.5rem;
  }

  .tab-bar button {
    background: none;
    border: none;
    border-bottom: 2px solid transparent;
    cursor: pointer;
    padding: 0.85rem 1.25rem;
    color: #73583d;
    font-family: "Avenir Next", "Gill Sans", sans-serif;
    font-size: 0.82rem;
    font-weight: 600;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    transition: color 140ms, border-color 140ms;
    margin-bottom: -1px;
  }

  .tab-bar button:hover { color: #241b13; }
  .tab-bar button.active {
    color: #9c5632;
    border-bottom-color: #9c5632;
  }

  .tab-content {
    flex: 1;
    display: flex;
    flex-direction: column;
  }

  /* ---- Index viewer (carried over from original) ---- */
  .shell {
    display: grid;
    grid-template-columns: minmax(18rem, 26rem) minmax(0, 1fr);
    flex: 1;
  }

  .sidebar {
    border-right: 1px solid rgba(72, 49, 31, 0.22);
    background: rgba(255, 248, 230, 0.72);
    backdrop-filter: blur(10px);
    padding: 2rem;
  }

  .brand { margin-bottom: 2rem; }

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
  .index-list small { display: block; }
  .index-list span { font-weight: 700; }
  .index-list small {
    margin-top: 0.45rem;
    color: #73583d;
    font-family: "Avenir Next", "Gill Sans", sans-serif;
  }

  .content {
    padding: clamp(1rem, 4vw, 4rem);
    overflow: auto;
  }

  article { animation: enter 260ms ease both; }
  header { margin-bottom: 1.5rem; }

  .wikitext {
    min-height: 55vh;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    border: 1px solid rgba(72, 49, 31, 0.18);
    border-radius: 24px;
    background: rgba(255, 252, 240, 0.82);
    box-shadow: 0 24px 70px rgba(62, 44, 30, 0.18);
    padding: clamp(1rem, 3vw, 2rem);
    font-family: "Berkeley Mono", "SFMono-Regular", Consolas, monospace;
    font-size: 0.95rem;
    line-height: 1.65;
  }

  @keyframes enter {
    from { opacity: 0; transform: translateY(8px); }
    to { opacity: 1; transform: translateY(0); }
  }

  @media (max-width: 760px) {
    .shell { grid-template-columns: 1fr; }
    .sidebar { border-right: 0; border-bottom: 1px solid rgba(72, 49, 31, 0.22); }
  }
</style>
