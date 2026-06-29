<script>
  let indexes = [];
  let selected = null;
  let loadingList = true;
  let loadingPage = false;
  let error = '';

  async function loadIndexes() {
    loadingList = true;
    error = '';

    try {
      const response = await fetch('/api/viewer/indexes');
      if (!response.ok) {
        throw new Error(`Failed to load index pages (${response.status})`);
      }
      indexes = await response.json();
      if (indexes.length > 0) {
        await loadPage(indexes[0].pk);
      }
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
      if (!response.ok) {
        throw new Error(`Failed to load page (${response.status})`);
      }
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
            on:click={() => loadPage(page.pk)}
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
