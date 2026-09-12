<script lang="ts">
  import { onMount } from 'svelte';
  import { listBatches, pushBatchPage } from '$lib/api';
  import ActionButton from '$lib/components/ActionButton.svelte';
  import Notice from '$lib/components/Notice.svelte';
  import PageHeading from '$lib/components/PageHeading.svelte';
  import SelectField from '$lib/components/SelectField.svelte';
  import type { Batch, BatchStatus } from '$lib/types';

  /**
   * Every push run staged so far, in one list -- the answer to "what is
   * pending, and did any promotion come back with an error". A batch's own
   * screen (`/sync/batches/[pk]`) answers that for one run; this is where a
   * person starts when they do not already have the pk in hand.
   */

  let batches: Batch[] = $state([]);
  let loading = $state(true);
  let pushing = $state(false);
  let progress = $state<{ current: number; total: number; title: string; step?: string } | null>(null);
  let error = $state('');
  let message = $state('');
  let statusFilter: 'all' | BatchStatus = $state('draft');
  let selectedBatchPks: number[] = $state([]);
  let failures: { pk: number; title: string; error: string }[] = $state([]);

  const STATUSES: Record<BatchStatus, { label: string; tone: string }> = {
    draft: { label: 'draft', tone: 'quiet' },
    running: { label: 'running', tone: 'in' },
    complete: { label: 'complete', tone: 'go' },
    partial: { label: 'partial', tone: 'warn' },
    aborted: { label: 'aborted', tone: 'quiet' }
  };

  function isPushable(batch: Batch): boolean {
    return batch.remaining > 0 && (batch.status === 'draft' || batch.status === 'running');
  }

  function errorCount(batch: Batch): number {
    return (batch.counts.conflict ?? 0) + (batch.counts.error ?? 0);
  }

  function firstError(batch: Batch): string | null {
    const row = batch.promotions.find((p) => p.error_message);
    return row?.error_message ?? null;
  }

  const countsByStatus = $derived.by(() => {
    const counts: Record<string, number> = {
      all: batches.length,
      draft: 0,
      running: 0,
      partial: 0,
      complete: 0,
      aborted: 0
    };
    for (const b of batches) {
      if (counts[b.status] !== undefined) {
        counts[b.status]++;
      }
    }
    return counts;
  });

  const openDraftBatches = $derived(
    batches.filter((b) => b.status === 'draft' && b.remaining > 0)
  );

  const visible = $derived.by((): Batch[] => {
    if (statusFilter === 'all') return batches;
    return batches.filter((b) => b.status === statusFilter);
  });

  const selectableVisible = $derived(visible.filter(isPushable));

  const allVisibleSelected = $derived(
    selectableVisible.length > 0 &&
      selectableVisible.every((b) => selectedBatchPks.includes(b.pk))
  );

  const selectedCount = $derived(selectedBatchPks.length);

  async function load(): Promise<void> {
    loading = true;
    error = '';
    try {
      batches = await listBatches();
      const currentPks = new Set(batches.map((b) => b.pk));
      selectedBatchPks = selectedBatchPks.filter((pk) => currentPks.has(pk));
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to load the batches';
    } finally {
      loading = false;
    }
  }

  function toggleBatch(batchPk: number): void {
    selectedBatchPks = selectedBatchPks.includes(batchPk)
      ? selectedBatchPks.filter((pk) => pk !== batchPk)
      : [...selectedBatchPks, batchPk];
  }

  function selectDrafts(): void {
    const draftPks = openDraftBatches.map((b) => b.pk);
    selectedBatchPks = [...new Set([...selectedBatchPks, ...draftPks])];
  }

  function toggleVisible(): void {
    const visiblePks = selectableVisible.map((b) => b.pk);
    if (allVisibleSelected) {
      selectedBatchPks = selectedBatchPks.filter((pk) => !visiblePks.includes(pk));
    } else {
      selectedBatchPks = [...new Set([...selectedBatchPks, ...visiblePks])];
    }
  }

  function clearSelection(): void {
    selectedBatchPks = [];
  }

  async function pushSelected(): Promise<void> {
    if (selectedBatchPks.length === 0 || pushing) return;

    pushing = true;
    error = '';
    message = '';
    failures = [];

    const toPush = batches.filter(
      (b) => selectedBatchPks.includes(b.pk) && isPushable(b)
    );
    let successes = 0;
    const batchFailures: { pk: number; title: string; error: string }[] = [];
    const succeededPks: number[] = [];

    for (let i = 0; i < toPush.length; i++) {
      const batch = toPush[i];
      const batchTitle = batch.label ?? batch.source_title;
      progress = {
        current: i + 1,
        total: toPush.length,
        title: batchTitle,
        step: 'Starting push...'
      };

      try {
        let current: Batch = batch;
        let hadError = false;

        while (current.remaining > 0 && (current.status === 'draft' || current.status === 'running')) {
          const totalRevs = current.promotions.length;
          const revIndex = totalRevs - current.remaining + 1;
          progress = {
            current: i + 1,
            total: toPush.length,
            title: batchTitle,
            step: `Replaying revision ${revIndex} of ${totalRevs}...`
          };

          const failuresBefore = (current.counts.conflict ?? 0) + (current.counts.error ?? 0);
          current = await pushBatchPage(batch.pk);

          const failuresAfter = (current.counts.conflict ?? 0) + (current.counts.error ?? 0);
          if (failuresAfter > failuresBefore) {
            const firstErr = current.promotions.find((p) => p.error_message)?.error_message
              ?? 'A revision did not push cleanly (conflict or error).';
            batchFailures.push({
              pk: batch.pk,
              title: batchTitle,
              error: firstErr
            });
            hadError = true;
            break;
          }
        }

        if (!hadError) {
          if (current.status === 'complete' || current.remaining === 0) {
            successes++;
            succeededPks.push(batch.pk);
          } else {
            batchFailures.push({
              pk: batch.pk,
              title: batchTitle,
              error: `Batch finished with status: ${current.status}`
            });
          }
        }
      } catch (err) {
        batchFailures.push({
          pk: batch.pk,
          title: batchTitle,
          error: err instanceof Error ? err.message : 'Push failed'
        });
      }
    }

    selectedBatchPks = selectedBatchPks.filter((pk) => !succeededPks.includes(pk));
    pushing = false;
    progress = null;
    failures = batchFailures;

    if (successes > 0 && batchFailures.length === 0) {
      message = `Successfully pushed ${successes} batch${successes === 1 ? '' : 'es'}.`;
    } else if (successes > 0 && batchFailures.length > 0) {
      message = `Pushed ${successes} batch${successes === 1 ? '' : 'es'}, but ${batchFailures.length} had errors.`;
    } else if (batchFailures.length > 0) {
      error = `Failed to push ${batchFailures.length} batch${batchFailures.length === 1 ? '' : 'es'}.`;
    }

    await load();
  }

  onMount(load);
</script>

<PageHeading eyebrow="Every run" title="Push batches">
  <p class="description">
    Every page staged so far, newest first. A batch is one page and its ordered
    source revisions; <code>partial</code> means part of that revision chain needs
    a look.
  </p>
</PageHeading>

{#if error}
  <Notice kind="error">{error}</Notice>
{/if}

{#if message}
  <Notice kind="success">{message}</Notice>
{/if}

{#if failures.length > 0}
  <section class="failures-summary" aria-label="Push errors">
    <h3>Issues encountered during batch push</h3>
    <ul>
      {#each failures as item}
        <li>
          <a class="drill" href={`/sync/batches/${item.pk}`}>
            <strong>{item.title}</strong> (#{item.pk})
          </a>
          <span class="failure-msg">&mdash; {item.error}</span>
        </li>
      {/each}
    </ul>
  </section>
{/if}

{#if progress}
  <section class="progress-banner" aria-live="polite">
    <div class="progress-bar-container">
      <div
        class="progress-bar-fill"
        style={`width: ${(progress.current / progress.total) * 100}%`}
      ></div>
    </div>
    <div class="progress-status">
      <strong>Pushing batch {progress.current} of {progress.total}: {progress.title}</strong>
      {#if progress.step}
        <small>{progress.step}</small>
      {/if}
    </div>
  </section>
{/if}

{#if !loading && batches.length > 0}
  <div class="filter-bar">
    <div class="filter-left">
      <SelectField label="Status" bind:value={statusFilter}>
        <option value="all">All runs ({countsByStatus.all})</option>
        <option value="draft">Draft ({countsByStatus.draft})</option>
        <option value="running">Running ({countsByStatus.running})</option>
        <option value="partial">Partial / needs review ({countsByStatus.partial})</option>
        <option value="complete">Complete ({countsByStatus.complete})</option>
        <option value="aborted">Aborted ({countsByStatus.aborted})</option>
      </SelectField>
    </div>

    <div class="filter-actions">
      {#if openDraftBatches.length > 0}
        <ActionButton
          variant="ghost"
          onclick={selectDrafts}
          disabled={pushing}
        >
          Select all draft ({openDraftBatches.length})
        </ActionButton>
      {/if}

      {#if selectableVisible.length > 0}
        <ActionButton
          variant="ghost"
          onclick={toggleVisible}
          disabled={pushing}
        >
          {allVisibleSelected ? 'Deselect visible' : 'Select all visible'}
        </ActionButton>
      {/if}

      {#if selectedCount > 0}
        <ActionButton
          variant="ghost"
          onclick={clearSelection}
          disabled={pushing}
        >
          Clear selection
        </ActionButton>

        <ActionButton
          variant="approve"
          onclick={pushSelected}
          disabled={pushing}
        >
          {pushing ? 'Pushing...' : `Push selected (${selectedCount})`}
        </ActionButton>
      {/if}
    </div>
  </div>
{/if}

{#if loading}
  <p class="state">Loading...</p>
{:else if batches.length === 0}
  <p class="state">
    No runs yet. Stage one from <a href="/sync">a work-level sync report</a> or
    <a href="/sync-page">a single page</a>.
  </p>
{:else if visible.length === 0}
  <p class="state">No batches matching status <code>{statusFilter}</code>.</p>
{:else}
  <table class="batches">
    <thead>
      <tr>
        <th scope="col" class="select-col">
          <input
            type="checkbox"
            aria-label="Select all pushable batches in this view"
            checked={allVisibleSelected}
            disabled={selectableVisible.length === 0 || pushing}
            onchange={toggleVisible}
          />
        </th>
        <th scope="col">#</th>
        <th scope="col">Status</th>
        <th scope="col">Direction</th>
        <th scope="col">Progress</th>
        <th scope="col"></th>
      </tr>
    </thead>
    <tbody>
      {#each visible as batch (batch.pk)}
        {@const selected = selectedBatchPks.includes(batch.pk)}
        {@const pushable = isPushable(batch)}
        <tr class:selected>
          <td class="select-col">
            {#if pushable}
              <input
                type="checkbox"
                aria-label={`Select batch ${batch.pk}`}
                checked={selected}
                disabled={pushing}
                onchange={() => toggleBatch(batch.pk)}
              />
            {/if}
          </td>
          <td>{batch.pk}</td>
          <td>
            <span class="chip {STATUSES[batch.status]?.tone ?? 'quiet'}">
              {STATUSES[batch.status]?.label ?? batch.status}
            </span>
          </td>
          <td class="dir">{batch.source_site} &rarr; {batch.target_site}</td>
          <td class="progress">
            {batch.promotions.length - batch.remaining}/{batch.promotions.length} settled
          </td>
          <td>
            <a class="drill" href={`/sync/batches/${batch.pk}`}>Open</a>
          </td>
        </tr>
        <tr class="run-row" class:selected>
          <td></td>
          <td colspan="5">
            <span class="run-label">Run</span>
            <span class="title">
              {batch.label ?? batch.source_title}
              {#if batch.label && batch.label !== batch.source_title}
                <small>{batch.source_title}</small>
              {/if}
            </span>
            {#if errorCount(batch) > 0}
              <small class="why">
                {errorCount(batch)} needs a look
                {#if firstError(batch)}&mdash; {firstError(batch)}{/if}
              </small>
            {/if}
          </td>
        </tr>
      {/each}
    </tbody>
  </table>
{/if}

<style>
  .description,
  .state {
    color: #73583d;
  }

  .description code {
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  }

  .state a {
    color: #9c5632;
  }

  .failures-summary {
    margin-bottom: 1.2rem;
    padding: 1rem 1.2rem;
    border: 1px solid rgba(127, 47, 34, 0.35);
    border-radius: 14px;
    background: rgba(253, 242, 240, 0.85);
  }

  .failures-summary h3 {
    margin: 0 0 0.5rem;
    color: #7f2f22;
    font-size: 0.95rem;
  }

  .failures-summary ul {
    margin: 0;
    padding-left: 1.2rem;
    color: #7f2f22;
    font-size: 0.88rem;
  }

  .failures-summary li {
    margin-bottom: 0.3rem;
  }

  .failures-summary .failure-msg {
    color: #551e16;
  }

  .progress-banner {
    margin-bottom: 1.2rem;
    padding: 0.9rem 1.1rem;
    border: 1px solid rgba(40, 107, 76, 0.35);
    border-radius: 14px;
    background: rgba(229, 246, 235, 0.8);
  }

  .progress-bar-container {
    height: 6px;
    margin-bottom: 0.6rem;
    border-radius: 3px;
    background: rgba(40, 107, 76, 0.18);
    overflow: hidden;
  }

  .progress-bar-fill {
    height: 100%;
    border-radius: 3px;
    background: #286b4c;
    transition: width 0.2s ease-out;
  }

  .progress-status {
    display: flex;
    flex-wrap: wrap;
    justify-content: space-between;
    align-items: center;
    gap: 0.5rem;
    color: #24543f;
    font-size: 0.88rem;
  }

  .progress-status small {
    color: #2e624b;
    font-size: 0.82rem;
  }

  .filter-bar {
    display: flex;
    flex-wrap: wrap;
    gap: 1rem;
    align-items: end;
    justify-content: space-between;
    margin-top: 1.2rem;
    margin-bottom: 1.2rem;
    padding-bottom: 0.6rem;
    border-bottom: 1px solid rgba(72, 49, 31, 0.12);
  }

  .filter-left {
    min-width: 14rem;
  }

  .filter-actions {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.6rem 0.85rem;
  }

  .chip {
    display: inline-flex;
    gap: 0.4rem;
    align-items: baseline;
    border: 1px solid;
    border-radius: 999px;
    font-family: "Avenir Next", "Gill Sans", sans-serif;
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.04em;
    padding: 0.28rem 0.68rem;
    text-transform: uppercase;
    white-space: nowrap;
  }

  .chip.go {
    border-color: rgba(40, 107, 76, 0.42);
    background: rgba(229, 246, 235, 0.72);
    color: #24543f;
  }

  .chip.in {
    border-color: rgba(61, 95, 146, 0.42);
    background: rgba(232, 240, 252, 0.72);
    color: #2f4a74;
  }

  .chip.warn {
    border-color: rgba(176, 120, 20, 0.42);
    background: rgba(255, 244, 219, 0.8);
    color: #7d5510;
  }

  .chip.quiet {
    border-color: rgba(72, 49, 31, 0.22);
    background: rgba(255, 252, 240, 0.7);
    color: #73583d;
  }

  .batches {
    width: 100%;
    margin-top: 0.5rem;
    border-collapse: collapse;
  }

  .batches th,
  .batches td {
    border-bottom: 1px solid rgba(72, 49, 31, 0.14);
    padding: 0.55rem 0.5rem;
    text-align: left;
    vertical-align: top;
  }

  .batches th {
    color: #73583d;
    font-family: "Avenir Next", "Gill Sans", sans-serif;
    font-size: 0.72rem;
    letter-spacing: 0.06em;
    text-transform: uppercase;
  }

  .batches .select-col {
    width: 2rem;
    padding-right: 0.15rem;
    text-align: center;
  }

  .batches input[type='checkbox'] {
    width: 1rem;
    height: 1rem;
    accent-color: #286b4c;
    cursor: pointer;
  }

  .batches input[type='checkbox']:disabled {
    cursor: default;
    opacity: 0.4;
  }

  .batches tr.selected td {
    background: rgba(40, 107, 76, 0.06);
  }

  .batches .title {
    overflow-wrap: anywhere;
  }

  .batches tr:not(.run-row) td {
    border-bottom: 0;
  }

  .batches .run-row td {
    padding-top: 0.15rem;
    padding-bottom: 0.8rem;
  }

  .run-label {
    display: inline-block;
    min-width: 3.4rem;
    margin-right: 0.45rem;
    color: #73583d;
    font-family: "Avenir Next", "Gill Sans", sans-serif;
    font-size: 0.68rem;
    font-weight: 700;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    vertical-align: top;
  }

  .run-row .title {
    display: inline;
  }

  .batches small {
    display: block;
    margin-top: 0.2rem;
    color: #73583d;
    font-size: 0.76rem;
  }

  .batches small.why {
    margin-left: 3.85rem;
    color: #7d5510;
  }

  .batches .dir,
  .batches .progress {
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 0.8rem;
    white-space: nowrap;
  }

  .drill {
    color: #9c5632;
    font-family: "Avenir Next", "Gill Sans", sans-serif;
    font-size: 0.76rem;
    font-weight: 700;
    text-decoration: none;
    text-transform: uppercase;
    white-space: nowrap;
  }

  .drill:hover {
    text-decoration: underline;
  }
</style>
