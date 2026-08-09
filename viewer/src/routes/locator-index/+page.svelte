<script lang="ts">
  import { onMount } from 'svelte';
  import { dumpLocatorIndex, listIndexPages, lookupPageNumbers, lookupSections } from '$lib/api';
  import Notice from '$lib/components/Notice.svelte';
  import PageHeading from '$lib/components/PageHeading.svelte';
  import WorkPicker from '$lib/components/WorkPicker.svelte';
  import type {
    IndexPageSummary,
    LocatorIndexDump,
    LocatorPageNumberMatch,
    LocatorSectionMatch,
    SectionRole
  } from '$lib/types';

  type Mode = 'section' | 'page-number' | 'dump';

  const ALL_ROLES: SectionRole[] = ['begin', 'end', 'anchor_template'];

  let works: IndexPageSummary[] = $state([]);
  let selected: IndexPageSummary | null = $state(null);
  let worksLoading = $state(true);
  let worksError = $state('');

  let mode: Mode = $state('section');
  let query = $state('');
  let roles: Set<SectionRole> = $state(new Set(['begin', 'anchor_template']));
  let minConfidence: 'explicit' | 'inferred' = $state('inferred');

  let sectionMatches: LocatorSectionMatch[] = $state([]);
  let pageNumberMatches: LocatorPageNumberMatch[] = $state([]);
  let dump: LocatorIndexDump | null = $state<LocatorIndexDump | null>(null);
  let dumpFilter = $state('');
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
    } catch (err) {
      worksError = err instanceof Error ? err.message : 'Failed to load Index pages';
    } finally {
      worksLoading = false;
    }
  }

  async function runLookup(): Promise<void> {
    sectionMatches = [];
    pageNumberMatches = [];
    dump = null;
    lookupError = '';
    if (!selected) {
      return;
    }
    if (mode !== 'dump' && query.trim().length === 0) {
      return;
    }
    lookupLoading = true;
    try {
      const path = indexPath(selected);
      if (mode === 'section') {
        sectionMatches = await lookupSections(path, query.trim(), [...roles]);
      } else if (mode === 'page-number') {
        pageNumberMatches = await lookupPageNumbers(path, query.trim(), minConfidence);
      } else {
        dump = await dumpLocatorIndex(path);
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

  function pagelistValue(entry: { text?: string | null; style?: string | null; value?: number | null }): string {
    if (entry.text != null) return entry.text;
    if (entry.value != null) return entry.style === 'arabic' ? String(entry.value) : `${entry.style} (${entry.value})`;
    return '—';
  }

  // Debounced live lookup for the two query modes; the dump mode has no
  // query to debounce, it just (re)loads on work/mode change.
  let debounceHandle: ReturnType<typeof setTimeout> | undefined;
  $effect(() => {
    void selected;
    void mode;
    void query;
    void roles;
    void minConfidence;
    clearTimeout(debounceHandle);
    const delay = mode === 'dump' ? 0 : 250;
    debounceHandle = setTimeout(() => void runLookup(), delay);
    return () => clearTimeout(debounceHandle);
  });

  const filteredPagelist = $derived(
    dump
      ? dump.pagelist_assignments.filter(
          (a) =>
            !dumpFilter ||
            String(a.scan_page).includes(dumpFilter) ||
            pagelistValue(a).toLowerCase().includes(dumpFilter.toLowerCase())
        )
      : []
  );
  const filteredPages = $derived(
    dump
      ? dump.pages.filter(
          (p) =>
            !dumpFilter ||
            p.page.title.toLowerCase().includes(dumpFilter.toLowerCase()) ||
            String(p.page.scan_page).includes(dumpFilter) ||
            (p.label ?? '').toLowerCase().includes(dumpFilter.toLowerCase())
        )
      : []
  );
  const filteredSections = $derived(
    dump
      ? dump.sections.filter(
          (s) =>
            !dumpFilter ||
            s.section_id.toLowerCase().includes(dumpFilter.toLowerCase()) ||
            s.page.title.toLowerCase().includes(dumpFilter.toLowerCase())
        )
      : []
  );

  onMount(loadWorks);
</script>

<PageHeading eyebrow="On-the-fly resolution" title="Locator index" count={`${works.length} indexed works`} />
<p class="blurb">
  Resolve a back-of-book reference — a printed page number, or a section/paragraph
  id like Hertz's numbered definitions or the Tractatus's propositions — to the
  <code>Page:</code> that holds it. Nothing here is persisted; every query recomputes
  from the current cache. "Everything" is <code>GET /locator-index/dump</code> — for
  inspection here, not the shape a completion feature should call (see the endpoint's
  own docstring).
</p>

<WorkPicker {works} bind:selected loading={worksLoading} error={worksError} />

{#if !selected}
  <div class="empty">Select a work above to look up a locator within it.</div>
{:else}
  <div class="query-bar">
    <div class="kind-toggle" role="group" aria-label="Locator mode">
      <button type="button" class:active={mode === 'section'} onclick={() => (mode = 'section')}>
        Section / paragraph id
      </button>
      <button type="button" class:active={mode === 'page-number'} onclick={() => (mode = 'page-number')}>
        Page number
      </button>
      <button type="button" class:active={mode === 'dump'} onclick={() => (mode = 'dump')}>
        Everything
      </button>
    </div>

    {#if mode === 'dump'}
      <input type="text" placeholder="filter..." bind:value={dumpFilter} aria-label="Filter dump tables" />
    {:else}
      <input
        type="text"
        placeholder={mode === 'section' ? "e.g. 'p-273' or '3.21'" : "e.g. '273'"}
        bind:value={query}
        aria-label="Locator query"
      />

      {#if mode === 'section'}
        <div class="option-row" role="group" aria-label="Occurrence roles">
          {#each ALL_ROLES as role}
            <label>
              <input type="checkbox" checked={roles.has(role)} onchange={() => toggleRole(role)} />
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
    {/if}
  </div>

  {#if lookupError}
    <Notice>{lookupError}</Notice>
  {/if}

  {#if lookupLoading}
    <p class="state">Loading...</p>
  {:else if mode === 'dump'}
    {#if dump}
      <div class="dump-grid">
        <section class="dump-panel">
          <h2>Pagelist entries <small>({filteredPagelist.length})</small></h2>
          {#if filteredPagelist.length === 0}
            <div class="empty">No explicit &lt;pagelist&gt; entries{dumpFilter ? ' match the filter' : ''}.</div>
          {:else}
            <div class="scroll">
              <table>
                <thead>
                  <tr>
                    <th>scan #</th>
                    <th>kind</th>
                    <th>value</th>
                  </tr>
                </thead>
                <tbody>
                  {#each filteredPagelist as entry}
                    <tr>
                      <td>{entry.scan_page}</td>
                      <td><span class="pill role-{entry.kind}">{entry.kind}</span></td>
                      <td>{pagelistValue(entry)}</td>
                    </tr>
                  {/each}
                </tbody>
              </table>
            </div>
          {/if}
        </section>

        <section class="dump-panel">
          <h2>Pages <small>({filteredPages.length})</small></h2>
          {#if filteredPages.length === 0}
            <div class="empty">No pages{dumpFilter ? ' match the filter' : ''}.</div>
          {:else}
            <div class="scroll">
              <table>
                <thead>
                  <tr>
                    <th>scan #</th>
                    <th>Page:</th>
                    <th>label</th>
                    <th>confidence</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {#each filteredPages as entry}
                    <tr>
                      <td>{entry.page.scan_page}</td>
                      <td>{entry.page.title}</td>
                      <td>{entry.label ?? '—'}</td>
                      <td><span class="pill confidence-{entry.confidence}">{entry.confidence}</span></td>
                      <td>
                        <button type="button" class="copy" onclick={() => copyPath(entry.page.path)}>
                          {copiedPath === entry.page.path ? 'copied' : 'copy path'}
                        </button>
                      </td>
                    </tr>
                  {/each}
                </tbody>
              </table>
            </div>
          {/if}
        </section>

        <section class="dump-panel">
          <h2>Sections &amp; anchors <small>({filteredSections.length})</small></h2>
          {#if filteredSections.length === 0}
            <div class="empty">No section/anchor occurrences{dumpFilter ? ' match the filter' : ''}.</div>
          {:else}
            <div class="scroll">
              <table>
                <thead>
                  <tr>
                    <th>section id</th>
                    <th>role</th>
                    <th>scan #</th>
                    <th>Page:</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {#each filteredSections as match}
                    <tr>
                      <td><code>{match.section_id}</code></td>
                      <td><span class="pill role-{match.role}">{match.role}</span></td>
                      <td>{match.page.scan_page}</td>
                      <td>{match.page.title}</td>
                      <td>
                        <button type="button" class="copy" onclick={() => copyPath(match.page.path)}>
                          {copiedPath === match.page.path ? 'copied' : 'copy path'}
                        </button>
                      </td>
                    </tr>
                  {/each}
                </tbody>
              </table>
            </div>
          {/if}
        </section>
      </div>
    {/if}
  {:else if mode === 'section'}
    {#if query.trim().length === 0}
      <div class="empty">Type a locator to search {selected.title}.</div>
    {:else if sectionMatches.length === 0}
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
  {:else if query.trim().length === 0}
    <div class="empty">Type a locator to search {selected.title}.</div>
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

<style>
  .blurb {
    max-width: 64rem;
    margin: 0.75rem 0 1.4rem;
    color: #73583d;
    font-size: 0.9rem;
    line-height: 1.5;
  }

  .blurb code {
    font-size: 0.85em;
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
    flex-wrap: wrap;
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

  .dump-grid {
    display: grid;
    gap: 1.4rem;
  }

  .dump-panel h2 {
    font-size: 1rem;
    margin-bottom: 0.6rem;
  }

  .dump-panel h2 small {
    color: #73583d;
    font-weight: 400;
  }

  .scroll {
    max-height: 22rem;
    overflow: auto;
    border: 1px solid rgba(72, 49, 31, 0.14);
    border-radius: 14px;
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
    position: sticky;
    top: 0;
    background: #fffaf0;
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
</style>
