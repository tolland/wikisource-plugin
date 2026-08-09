<script lang="ts">
  import { onMount } from 'svelte';
  import {
    linkWork,
    listIndexCandidates,
    listSites,
    listWorks,
    untrackWork
  } from '$lib/api';
  import { siteLabel } from '$lib/format';
  import ActionButton from '$lib/components/ActionButton.svelte';
  import Notice from '$lib/components/Notice.svelte';
  import PageHeading from '$lib/components/PageHeading.svelte';
  import SiteSelect from '$lib/components/SiteSelect.svelte';
  import type { CandidateList, IndexCandidate, Site, WorkSummary } from '$lib/types';

  /**
   * Level 1: pick two sites, pick an index on each, track the work.
   *
   * Two columns because that is what the model is -- every link is between two
   * sites, and neither is privileged. Tracked works are pinned above the
   * columns rather than mixed into them: "what are we already tracking" and
   * "what could we track" are different questions, and the first is the one a
   * returning reviewer came to answer.
   */

  let sites: Site[] = $state([]);
  let localPk: number | null = $state(null);
  let remotePk: number | null = $state(null);

  let localColumn: CandidateList | null = $state(null);
  let remoteColumn: CandidateList | null = $state(null);
  let localChoice: IndexCandidate | null = $state(null);
  let remoteChoice: IndexCandidate | null = $state(null);

  let works: WorkSummary[] = $state([]);
  let loading = $state(true);
  let busy = $state(false);
  let error = $state('');
  let message = $state('');

  const localSite = $derived(sites.find((site) => site.pk === localPk) ?? null);
  const remoteSite = $derived(sites.find((site) => site.pk === remotePk) ?? null);
  const canLink = $derived(
    Boolean(localChoice && remoteChoice && localSite && remoteSite && localPk !== remotePk)
  );

  function label(site: Site | null): string {
    return site?.label ?? (site ? siteLabel(site) : '');
  }

  async function loadWorks(): Promise<void> {
    // Unfiltered: a work whose sites are not the two currently selected is
    // still a work, and hiding it makes the page look empty on first visit.
    works = (await listWorks()).works;
  }

  async function loadColumn(which: 'local' | 'remote'): Promise<void> {
    const pk = which === 'local' ? localPk : remotePk;
    if (pk === null) return;
    const column = await listIndexCandidates(pk);
    if (which === 'local') {
      localColumn = column;
      localChoice = null;
    } else {
      remoteColumn = column;
      remoteChoice = null;
    }
  }

  async function load(): Promise<void> {
    loading = true;
    error = '';
    try {
      sites = await listSites();
      localPk ??= sites[0]?.pk ?? null;
      remotePk ??= sites[1]?.pk ?? sites[0]?.pk ?? null;
      await Promise.all([loadColumn('local'), loadColumn('remote'), loadWorks()]);
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to load links';
    } finally {
      loading = false;
    }
  }

  async function track(): Promise<void> {
    if (!canLink || !localChoice || !remoteChoice) return;
    busy = true;
    error = '';
    message = '';
    try {
      const result = await linkWork({
        local_label: label(localSite),
        remote_label: label(remoteSite),
        index_title: localChoice.title,
        remote_index_title: remoteChoice.title
      });
      const unpaired = result.unpaired.length
        ? `; ${result.unpaired.length} page(s) with no counterpart`
        : '';
      message = result.created
        ? `Tracking ${result.work.local_title}: ${result.paired} page pair(s) created, ${result.adopted} adopted${unpaired}`
        : `Already tracked; ${result.adopted} page pair(s) adopted${unpaired}`;
      await Promise.all([loadColumn('local'), loadColumn('remote'), loadWorks()]);
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to track the work';
    } finally {
      busy = false;
    }
  }

  async function untrack(work: WorkSummary): Promise<void> {
    busy = true;
    error = '';
    message = '';
    try {
      // Never cascading from here. Releasing the page pairs is recoverable;
      // deleting them throws away ladders that cost real fetches, and that is
      // not a decision to make on a single click in a list.
      await untrackWork(work.pk);
      message = `Stopped tracking ${work.local_title}; its ${work.pairs} page pair(s) were kept`;
      await Promise.all([loadColumn('local'), loadColumn('remote'), loadWorks()]);
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to untrack the work';
    } finally {
      busy = false;
    }
  }

  function choose(which: 'local' | 'remote', candidate: IndexCandidate): void {
    if (which === 'local') localChoice = candidate;
    else remoteChoice = candidate;
  }

  onMount(load);
</script>

<PageHeading
  eyebrow="Cross-site"
  title="Linked works"
  count={`${works.length} tracked`}
/>

{#if error}
  <Notice>{error}</Notice>
{/if}
{#if message}
  <Notice kind="success">{message}</Notice>
{/if}

<section class="tracked" aria-label="Tracked works">
  {#if loading}
    <p class="state">Loading...</p>
  {:else if works.length === 0}
    <p class="state">
      No works tracked yet. Pick an index in each column below and link them.
    </p>
  {:else}
    <ul class="work-list">
      {#each works as work}
        <li>
          <a class="work" href={`/links/${work.pk}`}>
            <span class="titles">
              <strong>{work.local_title}</strong>
              <em>{work.remote_title}</em>
            </span>
            <span class="sites">{work.local_site} &harr; {work.remote_site}</span>
            <span class="counts">
              {work.linked}/{work.pairs} linked
              {#if work.local_pages > work.pairs}
                <small>{work.local_pages - work.pairs} unpaired</small>
              {/if}
            </span>
          </a>
          <ActionButton variant="ghost" disabled={busy} onclick={() => untrack(work)}>
            Untrack
          </ActionButton>
        </li>
      {/each}
    </ul>
  {/if}
</section>

<section class="columns" aria-label="Link two indexes">
  <div class="column">
    <SiteSelect {sites} label="This side" bind:value={localPk} onchange={() => loadColumn('local')} />
    {#if !localColumn}
      <p class="state">Choose a site.</p>
    {:else if localColumn.indexes.length === 0}
      <p class="state">No Index: pages cached for {localColumn.site}. Fetch one first.</p>
    {:else}
      <ul class="index-list">
        {#each localColumn.indexes as candidate}
          <li>
            <button
              type="button"
              class:selected={localChoice?.page_pk === candidate.page_pk}
              class:tracked={candidate.work_pk !== null && candidate.work_pk !== undefined}
              onclick={() => choose('local', candidate)}
            >
              <span>{candidate.title}</span>
              <small>
                {candidate.cached_pages} page(s) cached
                {#if candidate.paired_with}
                  &middot; tracked against {candidate.paired_with}
                {/if}
              </small>
            </button>
          </li>
        {/each}
      </ul>
    {/if}
  </div>

  <div class="column">
    <SiteSelect
      {sites}
      label="Other side"
      bind:value={remotePk}
      onchange={() => loadColumn('remote')}
    />
    {#if !remoteColumn}
      <p class="state">Choose a site.</p>
    {:else if remoteColumn.indexes.length === 0}
      <p class="state">No Index: pages cached for {remoteColumn.site}. Fetch one first.</p>
    {:else}
      <ul class="index-list">
        {#each remoteColumn.indexes as candidate}
          <li>
            <button
              type="button"
              class:selected={remoteChoice?.page_pk === candidate.page_pk}
              class:tracked={candidate.work_pk !== null && candidate.work_pk !== undefined}
              onclick={() => choose('remote', candidate)}
            >
              <span>{candidate.title}</span>
              <small>
                {candidate.cached_pages} page(s) cached
                {#if candidate.paired_with}
                  &middot; tracked against {candidate.paired_with}
                {/if}
              </small>
            </button>
          </li>
        {/each}
      </ul>
    {/if}
  </div>
</section>

<div class="link-bar">
  <ActionButton disabled={!canLink || busy} onclick={track}>Link these indexes</ActionButton>
  {#if localPk !== null && localPk === remotePk}
    <span class="hint">Pick two different sites: a work is tracked across wikis.</span>
  {:else if !canLink}
    <span class="hint">Select one index in each column.</span>
  {:else}
    <span class="hint">
      {localChoice?.title} &harr; {remoteChoice?.title}. Pages are paired by page
      number at the same time.
    </span>
  {/if}
</div>

<style>
  .state {
    color: #73583d;
  }

  .tracked {
    margin: 1.5rem 0 2.5rem;
  }

  .work-list,
  .index-list {
    display: grid;
    gap: 0.6rem;
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .work-list li {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    gap: 0.75rem;
    align-items: center;
  }

  .work {
    display: grid;
    grid-template-columns: minmax(0, 2fr) minmax(0, 1fr) auto;
    gap: 1rem;
    align-items: center;
    border: 1px solid rgba(87, 58, 37, 0.2);
    border-radius: 18px;
    background: rgba(255, 252, 240, 0.64);
    color: inherit;
    padding: 0.9rem 1.1rem;
    text-decoration: none;
  }

  .work:hover {
    border-color: #9c5632;
    background: #fff7e6;
  }

  .titles strong,
  .titles em {
    display: block;
    min-width: 0;
    overflow-wrap: anywhere;
  }

  .titles em {
    color: #73583d;
    font-style: normal;
    font-size: 0.86rem;
  }

  .sites,
  .counts {
    color: #73583d;
    font-family: "Avenir Next", "Gill Sans", sans-serif;
    font-size: 0.8rem;
  }

  .counts small {
    display: block;
    color: #8a5a2b;
  }

  .columns {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: clamp(1rem, 3vw, 2rem);
  }

  .column {
    border: 1px solid rgba(72, 49, 31, 0.18);
    border-radius: 24px;
    background: rgba(255, 248, 230, 0.72);
    padding: 1.2rem;
  }

  .index-list {
    margin-top: 1rem;
  }

  .index-list button {
    width: 100%;
    cursor: pointer;
    border: 1px solid rgba(87, 58, 37, 0.2);
    border-radius: 16px;
    background: rgba(255, 252, 240, 0.64);
    color: inherit;
    padding: 0.8rem 0.9rem;
    text-align: left;
  }

  .index-list button.tracked {
    border-left: 4px solid #286b4c;
  }

  .index-list button.selected {
    border-color: #9c5632;
    background: #fff7e6;
  }

  .index-list span,
  .index-list small {
    display: block;
    overflow-wrap: anywhere;
  }

  .index-list small {
    margin-top: 0.35rem;
    color: #73583d;
    font-family: "Avenir Next", "Gill Sans", sans-serif;
    font-size: 0.76rem;
  }

  .link-bar {
    display: flex;
    flex-wrap: wrap;
    gap: 0.75rem 1rem;
    align-items: center;
    margin-top: 1.5rem;
  }

  .hint {
    color: #73583d;
    font-size: 0.86rem;
  }

  @media (max-width: 860px) {
    .columns {
      grid-template-columns: 1fr;
    }

    .work {
      grid-template-columns: 1fr;
    }
  }
</style>
