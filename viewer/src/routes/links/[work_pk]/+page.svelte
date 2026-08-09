<script lang="ts">
  import { onMount } from 'svelte';
  import { page } from '$app/state';
  import { fetchWorkHistory, getWork, proposeWork } from '$lib/api';
  import ActionButton from '$lib/components/ActionButton.svelte';
  import Notice from '$lib/components/Notice.svelte';
  import PageHeading from '$lib/components/PageHeading.svelte';
  import type { MatchOutcome, PagePair, WorkDetail } from '$lib/types';

  /**
   * Level 2: one work's pages, and what comparing each says right now.
   *
   * The outcomes are recomputed server-side per load rather than stored,
   * because the fix for the two most common ones is to hold more revisions --
   * a cached verdict would be stale exactly after the action taken to fix it.
   *
   * Two actions, matching the two outcomes that are not verdicts:
   *
   *   fetch history  queues deeper fetches for the pages whose anchor search
   *                  ran out of revisions (history_exhausted, quality_differs)
   *   propose        re-runs the comparison and links what has become linkable
   *
   * Anything a page needs beyond that is per-page, and lives one level down.
   */

  const workPk = Number(page.params.work_pk);

  let detail: WorkDetail | null = $state(null);
  let loading = $state(true);
  let busy = $state(false);
  let error = $state('');
  let message = $state('');
  let revisions = $state(10);

  /** How each outcome reads, and what it means for the reviewer. */
  const OUTCOMES: Record<MatchOutcome, { label: string; tone: string; note: string }> = {
    same: { label: 'same', tone: 'ok', note: 'Heads hold the same content.' },
    local_ahead: { label: 'local ahead', tone: 'ok', note: 'We have edits the other side does not.' },
    remote_ahead: { label: 'remote ahead', tone: 'ok', note: 'They have edits we do not.' },
    already_linked: { label: 'linked', tone: 'ok', note: 'Already asserted.' },
    quality_differs: {
      label: 'quality differs',
      tone: 'warn',
      note: 'Same words, different proofreading level, and no anchor in the revisions held.'
    },
    history_exhausted: {
      label: 'history exhausted',
      tone: 'warn',
      note: 'No anchor in the revisions held, and the history is incomplete. Not a verdict: fetch more.'
    },
    diverged: {
      label: 'diverged',
      tone: 'bad',
      note: 'The transcriptions differ, with the full history held. A person has to reconcile these.'
    },
    unfetched: { label: 'unfetched', tone: 'bad', note: 'A side has no cached head revision.' },
    no_counterpart: { label: 'no counterpart', tone: 'bad', note: 'Nothing on the other site holds this page.' }
  };

  const stuck = $derived.by((): PagePair[] => {
    if (detail === null) return [];
    return detail.pages.filter((row) => row.resolvable_by_fetch);
  });

  async function load(): Promise<void> {
    loading = true;
    error = '';
    try {
      detail = await getWork(workPk);
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to load the work';
    } finally {
      loading = false;
    }
  }

  async function run(action: () => Promise<string>): Promise<void> {
    busy = true;
    error = '';
    message = '';
    try {
      message = await action();
      await load();
    } catch (err) {
      error = err instanceof Error ? err.message : 'The action failed';
    } finally {
      busy = false;
    }
  }

  const queueHistory = (allPages: boolean) =>
    run(async () => {
      const result = await fetchWorkHistory(workPk, revisions, allPages);
      return `${result.note} Queued ${result.queued} fetch(es) over ${result.pages} page(s), ${result.revisions} revisions each.`;
    });

  const propose = (confirm: boolean) =>
    run(async () => {
      const result = await proposeWork(workPk, confirm);
      return confirm
        ? `Linked ${result.confirmed} page pair(s).`
        : `Nothing written. ${Object.entries(result.counts)
            .map(([outcome, count]) => `${outcome}=${count}`)
            .join('  ')}`;
    });

  function pairHref(row: PagePair): string | null {
    return row.pair_pk ? `/links/pairs/${row.pair_pk}` : null;
  }

  onMount(load);
</script>

<p class="crumb"><a href="/links">&larr; Linked works</a></p>

{#if loading}
  <p class="state">Loading...</p>
{:else if detail}
  <PageHeading
    eyebrow={`${detail.work.local_site} ↔ ${detail.work.remote_site}`}
    title={detail.work.local_title}
    count={`${detail.work.linked}/${detail.work.pairs} page pairs linked`}
  >
    <p class="other">{detail.work.remote_title}</p>
  </PageHeading>

  {#if error}
    <Notice>{error}</Notice>
  {/if}
  {#if message}
    <Notice kind="success">{message}</Notice>
  {/if}

  <section class="summary" aria-label="Outcomes">
    {#each Object.entries(detail.counts) as [outcome, count]}
      <span class="chip {OUTCOMES[outcome as MatchOutcome]?.tone ?? 'bad'}">
        {OUTCOMES[outcome as MatchOutcome]?.label ?? outcome}
        <strong>{count}</strong>
      </span>
    {/each}
  </section>

  <section class="actions" aria-label="Resolve">
    <div class="action">
      <h2>Fetch more history</h2>
      <p>
        {detail.needs_history} page(s) report no anchor in the revisions held. Neither
        outcome says the two sides disagree -- the matching revision is usually one
        or two edits back, on a side nobody fetched deeply. Both sides are queued.
      </p>
      <div class="row">
        <label>
          Revisions per page
          <input type="number" min="2" max="200" bind:value={revisions} />
        </label>
        <ActionButton disabled={busy || detail.needs_history === 0} onclick={() => queueHistory(false)}>
          Queue the {detail.needs_history} stuck page(s)
        </ActionButton>
        <ActionButton variant="ghost" disabled={busy} onclick={() => queueHistory(true)}>
          Queue every page
        </ActionButton>
      </div>
      <small>Queued only -- run a drain from the Fetch page, then reload this one.</small>
    </div>

    <div class="action">
      <h2>Propose links</h2>
      <p>
        Re-compares every page and links the pairs that hold the same content. The step
        after a fetch: the anchor search has more history to walk.
      </p>
      <div class="row">
        <ActionButton variant="ghost" disabled={busy} onclick={() => propose(false)}>
          Report only
        </ActionButton>
        <ActionButton disabled={busy} onclick={() => propose(true)}>
          Link what can be linked
        </ActionButton>
      </div>
    </div>
  </section>

  {#if stuck.length}
    <p class="stuck-hint">
      Pages that need a person: open one to see both histories side by side and link a
      revision pair the search will not propose.
    </p>
  {/if}

  <table class="pages">
    <thead>
      <tr>
        <th scope="col">#</th>
        <th scope="col">Outcome</th>
        <th scope="col">Page</th>
        <th scope="col">Revisions</th>
        <th scope="col">Rungs</th>
        <th scope="col"></th>
      </tr>
    </thead>
    <tbody>
      {#each detail.pages as row}
        <tr class={OUTCOMES[row.outcome]?.tone ?? 'bad'}>
          <td>{row.page_number ?? '?'}</td>
          <td>
            <span class="chip {OUTCOMES[row.outcome]?.tone ?? 'bad'}">
              {OUTCOMES[row.outcome]?.label ?? row.outcome}
            </span>
          </td>
          <td class="title">
            {row.local_title}
            {#if row.detail}
              <small>{row.detail}</small>
            {:else}
              <small>{OUTCOMES[row.outcome]?.note ?? ''}</small>
            {/if}
          </td>
          <td class="revs">
            {row.local_revid ?? '-'} / {row.remote_revid ?? '-'}
            {#if row.local_ahead_by || row.remote_ahead_by}
              <small>
                {#if row.local_ahead_by}local +{row.local_ahead_by}{/if}
                {#if row.local_ahead_by && row.remote_ahead_by}, {/if}
                {#if row.remote_ahead_by}remote +{row.remote_ahead_by}{/if}
              </small>
            {/if}
          </td>
          <td>{row.rungs}</td>
          <td>
            {#if pairHref(row)}
              <a class="drill" href={pairHref(row)}>Revisions</a>
            {/if}
          </td>
        </tr>
      {/each}
    </tbody>
  </table>
{:else}
  <Notice>{error || 'No such work.'}</Notice>
{/if}

<style>
  .crumb a {
    color: #73583d;
    font-family: "Avenir Next", "Gill Sans", sans-serif;
    font-size: 0.8rem;
    text-decoration: none;
  }

  .other {
    color: #73583d;
  }

  .state {
    color: #73583d;
  }

  .summary {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    margin: 1rem 0 1.5rem;
  }

  .chip {
    display: inline-flex;
    gap: 0.4rem;
    align-items: baseline;
    border: 1px solid;
    border-radius: 999px;
    font-family: "Avenir Next", "Gill Sans", sans-serif;
    font-size: 0.74rem;
    font-weight: 700;
    letter-spacing: 0.04em;
    padding: 0.3rem 0.7rem;
    text-transform: uppercase;
    white-space: nowrap;
  }

  .chip.ok {
    border-color: rgba(40, 107, 76, 0.4);
    background: rgba(229, 246, 235, 0.72);
    color: #24543f;
  }

  .chip.warn {
    border-color: rgba(176, 120, 20, 0.42);
    background: rgba(255, 244, 219, 0.8);
    color: #7d5510;
  }

  .chip.bad {
    border-color: rgba(178, 69, 47, 0.42);
    background: rgba(255, 238, 233, 0.76);
    color: #7f2f22;
  }

  .actions {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(20rem, 1fr));
    gap: 1rem;
    margin-bottom: 1.75rem;
  }

  .action {
    border: 1px solid rgba(72, 49, 31, 0.18);
    border-radius: 20px;
    background: rgba(255, 248, 230, 0.72);
    padding: 1.1rem 1.2rem;
  }

  .action h2 {
    margin: 0 0 0.4rem;
    font-size: 1rem;
  }

  .action p {
    margin: 0 0 0.8rem;
    color: #73583d;
    font-size: 0.88rem;
  }

  .action small {
    display: block;
    margin-top: 0.6rem;
    color: #8a6a45;
    font-size: 0.76rem;
  }

  .row {
    display: flex;
    flex-wrap: wrap;
    gap: 0.6rem;
    align-items: end;
  }

  .row label {
    display: grid;
    gap: 0.3rem;
    color: #73583d;
    font-family: "Avenir Next", "Gill Sans", sans-serif;
    font-size: 0.74rem;
    text-transform: uppercase;
  }

  .row input {
    width: 6rem;
    border: 1px solid rgba(72, 49, 31, 0.28);
    border-radius: 10px;
    background: rgba(255, 252, 240, 0.9);
    padding: 0.6rem;
  }

  .stuck-hint {
    color: #7d5510;
    font-size: 0.88rem;
  }

  .pages {
    width: 100%;
    border-collapse: collapse;
  }

  .pages th,
  .pages td {
    border-bottom: 1px solid rgba(72, 49, 31, 0.14);
    padding: 0.6rem 0.5rem;
    text-align: left;
    vertical-align: top;
  }

  .pages th {
    color: #73583d;
    font-family: "Avenir Next", "Gill Sans", sans-serif;
    font-size: 0.72rem;
    letter-spacing: 0.06em;
    text-transform: uppercase;
  }

  .pages .title {
    overflow-wrap: anywhere;
  }

  .pages small {
    display: block;
    margin-top: 0.2rem;
    color: #73583d;
    font-size: 0.76rem;
  }

  .pages .revs {
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 0.82rem;
    white-space: nowrap;
  }

  .drill {
    color: #9c5632;
    font-family: "Avenir Next", "Gill Sans", sans-serif;
    font-size: 0.76rem;
    font-weight: 700;
    text-transform: uppercase;
    white-space: nowrap;
  }
</style>
