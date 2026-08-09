<script lang="ts">
  import { onMount } from 'svelte';
  import { listIndexPages, lookupPageNumbers, lookupSections } from '$lib/api';
  import Notice from '$lib/components/Notice.svelte';
  import PageHeading from '$lib/components/PageHeading.svelte';
  import type {
    IndexPageSummary,
    LocatorPageNumberMatch,
    LocatorSectionMatch,
    SectionRole
  } from '$lib/types';

  type Kind = 'section' | 'page-number';

  const ALL_ROLES: SectionRole[] = ['begin', 'end', 'anchor_template'];

  let works: IndexPageSummary[] = $state([]);
  let selected: IndexPageSummary | null = $state(null);
  let worksLoading = $state(true);
  let worksError = $state('');

  let kind: Kind = $state('section');
  let query = $state('');
  let roles: Set<SectionRole> = $state(new Set(['begin', 'anchor_template']));
  let minConfidence: 'explicit' | 'inferred' = $state('inferred');

  let sectionMatches: LocatorSectionMatch[] = $state([]);
  let pageNumberMatches: LocatorPageNumberMatch[] = $state([]);
  let lookupLoading = $state(false);
  let lookupError = $state('');
  let copiedPath = $state('');

  function indexPath(work: IndexPageSummary): string {
    return `/${work.family}/${work.code}/${work.title}`;
  }

  async function loadWorks(): Promise<void> {
    worksLoading = true;
    worksError = '';
    try {
      works = await listIndexPages();
      selected = works[0] ?? null;
    } catch (err) {
      worksError = err instanceof Error ? err.message : 'Failed to load Index pages';
    } finally {
      worksLoading = false;
    }
  }

  async function runLookup(): Promise<void> {
    sectionMatches = [];
    pageNumberMatches = [];
    lookupError = '';
    if (!selected || query.trim().length === 0) {
      return;
    }
    lookupLoading = true;
    try {
      const path = indexPath(selected);
      if (kind === 'section') {
        sectionMatches = await lookupSections(path, query.trim(), [...roles]);
      } else {
        pageNumberMatches = await lookupPageNumbers(path, query.trim(), minConfidence);
      }
    } catch (err) {
      lookupError = err instanceof Error ? err.message : 'Locator lookup failed';
    } finally {
      lookupLoading = false;
    }
  }

  function toggleRole(role: SectionRole): void {
    const next = new Set(roles);
    if (next.has(role)) {
      next.delete(role);
    } else {
      next.add(role);
    }
    roles = next;
  }

  async function copyPath(path: string): Promise<void> {
    try {
      await navigator.clipboard.writeText(path);
      copiedPath = path;
      setTimeout(() => {
        if (copiedPath === path) copiedPath = '';
      }, 1500);
    } catch {
      // Clipboard access can be denied (permissions, non-secure context); the
      // path is already on screen to select by hand, so this is not fatal.
    }
  }

  // Debounced live lookup: re-run ~250ms after the query/options settle,
  // rather than on every keystroke -- this endpoint is a local SQLite scan
  // over a work's whole Page: set, cheap but not free typing-speed-many-times-
  // per-second.
  let debounceHandle: ReturnType<typeof setTimeout> | undefined;
  $effect(() => {
    // Establish the dependencies explicitly by reading them here.
    void selected;
    void kind;
    void query;
    void roles;
    void minConfidence;
    clearTimeout(debounceHandle);
    debounceHandle = setTimeout(() => void runLookup(), 250);
    return () => clearTimeout(debounceHandle);
  });

  onMount(loadWorks);
</script>

<section class="locator-workspace">
  <aside class="sidebar" aria-label="Works">
    <div class="brand">
      <PageHeading
        eyebrow="On-the-fly resolution"
        title="Locator index"
        count={`${works.length} indexed works`}
      />
      <p class="blurb">
        Resolve a back-of-book reference — a printed page number, or a
        section/paragraph id like Hertz's numbered definitions or the
        Tractatus's propositions — to the <code>Page:</code> that holds it. See
        <code>GET /locator-index/page-numbers</code> and
        <code>GET /locator-index/sections</code>; nothing here is persisted, every
        query recomputes from the current cache.
      </p>
    </div>

    {#if worksError}
      <Notice>{worksError}</Notice>
    {/if}

    {#if worksLoading}
      <p class="state">Loading Index pages...</p>
    {:else if works.length === 0}
      <p class="state">No records found with content_model "proofread-index".</p>
    {:else}
      <nav class="work-list">
        {#each works as work}
          <button
            type="button"
            class:active={selected?.pk === work.pk}
            onclick={() => (selected = work)}
          >
            <span>{work.title}</span>
            <small>{work.family}/{work.code}{#if work.page_count} · {work.page_count} pages{/if}</small>
          </button>
        {/each}
      </nav>
    {/if}
  </aside>

  <section class="content" aria-live="polite">
    {#if !selected}
      <div class="empty">Select a work to look up a locator within it.</div>
    {:else}
      <div class="query-bar">
        <div class="kind-toggle" role="group" aria-label="Locator kind">
          <button type="button" class:active={kind === 'section'} onclick={() => (kind = 'section')}>
            Section / paragraph id
          </button>
          <button
            type="button"
            class:active={kind === 'page-number'}
            onclick={() => (kind = 'page-number')}
          >
            Page number
          </button>
        </div>

        <input
          type="text"
          placeholder={kind === 'section' ? "e.g. 'p-273' or '3.21'" : "e.g. '273'"}
          bind:value={query}
          aria-label="Locator query"
        />

        {#if kind === 'section'}
          <div class="option-row" role="group" aria-label="Occurrence roles">
            {#each ALL_ROLES as role}
              <label>
                <input
                  type="checkbox"
                  checked={roles.has(role)}
                  onchange={() => toggleRole(role)}
                />
                {role}
              </label>
            {/each}
          </div>
        {:else}
          <div class="option-row" role="group" aria-label="Minimum confidence">
            <label>
              <input
                type="radio"
                name="confidence"
                checked={minConfidence === 'inferred'}
                onchange={() => (minConfidence = 'inferred')}
              />
              explicit + inferred
            </label>
            <label>
              <input
                type="radio"
                name="confidence"
                checked={minConfidence === 'explicit'}
                onchange={() => (minConfidence = 'explicit')}
              />
              explicit only
            </label>
          </div>
        {/if}
      </div>

      {#if lookupError}
        <Notice>{lookupError}</Notice>
      {/if}

      {#if query.trim().length === 0}
        <div class="empty">Type a locator to search {selected.title}.</div>
      {:else if lookupLoading}
        <p class="state">Looking up...</p>
      {:else if kind === 'section'}
        {#if sectionMatches.length === 0}
          <div class="empty">No section/anchor occurrences match "{query}".</div>
        {:else}
          <table>
            <thead>
              <tr>
                <th>section id</th>
                <th>role</th>
                <th>Page:</th>
                <th>scan #</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {#each sectionMatches as match}
                <tr>
                  <td><code>{match.section_id}</code></td>
                  <td><span class="pill role-{match.role}">{match.role}</span></td>
                  <td>{match.page.title}</td>
                  <td>{match.page.scan_page}</td>
                  <td>
                    <button type="button" class="copy" onclick={() => copyPath(match.page.path)}>
                      {copiedPath === match.page.path ? 'copied' : 'copy path'}
                    </button>
                  </td>
                </tr>
              {/each}
            </tbody>
          </table>
        {/if}
      {:else if pageNumberMatches.length === 0}
        <div class="empty">No page-number matches for "{query}".</div>
      {:else}
        <table>
          <thead>
            <tr>
              <th>label</th>
              <th>confidence</th>
              <th>Page:</th>
              <th>scan #</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {#each pageNumberMatches as match}
              <tr>
                <td><code>{match.label}</code></td>
                <td><span class="pill confidence-{match.confidence}">{match.confidence}</span></td>
                <td>{match.page.title}</td>
                <td>{match.page.scan_page}</td>
                <td>
                  <button type="button" class="copy" onclick={() => copyPath(match.page.path)}>
                    {copiedPath === match.page.path ? 'copied' : 'copy path'}
                  </button>
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      {/if}
    {/if}
  </section>
</section>

<style>
  .locator-workspace {
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
    margin-bottom: 1.4rem;
  }

  .blurb {
    margin-top: 0.75rem;
    color: #73583d;
    font-size: 0.9rem;
    line-height: 1.5;
  }

  .blurb code {
    font-size: 0.85em;
  }

  .work-list {
    display: grid;
    gap: 0.75rem;
  }

  .work-list button {
    width: 100%;
    cursor: pointer;
    border: 1px solid rgba(87, 58, 37, 0.2);
    border-radius: 18px;
    background: rgba(255, 252, 240, 0.64);
    color: inherit;
    padding: 1rem;
    text-align: left;
    transition:
      transform 160ms ease,
      border-color 160ms ease,
      background 160ms ease;
  }

  .work-list button:hover,
  .work-list button.active {
    transform: translateY(-1px);
    border-color: #9c5632;
    background: #fff7e6;
  }

  .work-list span,
  .work-list small {
    display: block;
  }

  .work-list span {
    font-weight: 700;
  }

  .work-list small {
    margin-top: 0.45rem;
    color: #73583d;
    font-family: 'Avenir Next', 'Gill Sans', sans-serif;
  }

  .content {
    min-width: 0;
  }

  .query-bar {
    display: grid;
    gap: 0.9rem;
    border: 1px solid rgba(72, 49, 31, 0.18);
    border-radius: 20px;
    background: rgba(255, 252, 240, 0.6);
    padding: 1.2rem;
    margin-bottom: 1.2rem;
  }

  .kind-toggle {
    display: flex;
    gap: 0.5rem;
  }

  .kind-toggle button {
    cursor: pointer;
    border: 1px solid rgba(87, 58, 37, 0.25);
    border-radius: 999px;
    background: transparent;
    color: inherit;
    padding: 0.4rem 0.9rem;
    font-size: 0.85rem;
  }

  .kind-toggle button.active {
    background: #9c5632;
    border-color: #9c5632;
    color: #fff8ec;
  }

  .query-bar input[type='text'] {
    border: 1px solid rgba(87, 58, 37, 0.25);
    border-radius: 12px;
    padding: 0.6rem 0.8rem;
    font-size: 1rem;
    background: #fffdf7;
    color: inherit;
  }

  .option-row {
    display: flex;
    flex-wrap: wrap;
    gap: 0.9rem;
    font-size: 0.85rem;
    color: #73583d;
  }

  .option-row label {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    cursor: pointer;
  }

  .empty,
  .state {
    color: #73583d;
    padding: 1.2rem 0;
  }

  table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.92rem;
  }

  th,
  td {
    text-align: left;
    padding: 0.55rem 0.7rem;
    border-bottom: 1px solid rgba(72, 49, 31, 0.14);
  }

  th {
    color: #73583d;
    font-weight: 600;
    font-size: 0.78rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }

  .pill {
    display: inline-block;
    border-radius: 999px;
    padding: 0.15rem 0.6rem;
    font-size: 0.78rem;
    background: rgba(156, 86, 50, 0.14);
  }

  .pill.confidence-explicit,
  .pill.role-begin {
    background: rgba(40, 107, 76, 0.18);
    color: #24543f;
  }

  .pill.confidence-unknown {
    background: rgba(178, 69, 47, 0.18);
    color: #7f2f22;
  }

  .copy {
    cursor: pointer;
    border: 1px solid rgba(87, 58, 37, 0.25);
    border-radius: 999px;
    background: transparent;
    color: inherit;
    padding: 0.25rem 0.7rem;
    font-size: 0.78rem;
  }

  @media (max-width: 860px) {
    .locator-workspace {
      grid-template-columns: 1fr;
    }
  }
</style>
