<script lang="ts">
  import { onMount } from 'svelte';
  import { listBatches } from '$lib/api';
  import Notice from '$lib/components/Notice.svelte';
  import PageHeading from '$lib/components/PageHeading.svelte';
  import type { Batch, BatchStatus } from '$lib/types';

  /**
   * Every push run staged so far, in one list -- the answer to "what is
   * pending, and did any promotion come back with an error". A batch's own
   * screen (`/sync/batches/[pk]`) answers that for one run; this is where a
   * person starts when they do not already have the pk in hand.
   */

  let batches: Batch[] = $state([]);
  let loading = $state(true);
  let error = $state('');

  const STATUSES: Record<BatchStatus, { label: string; tone: string }> = {
    draft: { label: 'draft', tone: 'quiet' },
    running: { label: 'running', tone: 'in' },
    complete: { label: 'complete', tone: 'go' },
    partial: { label: 'partial', tone: 'warn' },
    aborted: { label: 'aborted', tone: 'quiet' }
  };

  function errorCount(batch: Batch): number {
    return (batch.counts.conflict ?? 0) + (batch.counts.error ?? 0);
  }

  function firstError(batch: Batch): string | null {
    const row = batch.promotions.find((p) => p.error_message);
    return row?.error_message ?? null;
  }

  async function load(): Promise<void> {
    loading = true;
    error = '';
    try {
      batches = await listBatches();
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to load the batches';
    } finally {
      loading = false;
    }
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
  <Notice>{error}</Notice>
{/if}

{#if loading}
  <p class="state">Loading...</p>
{:else if batches.length === 0}
  <p class="state">
    No runs yet. Stage one from <a href="/sync">a work-level sync report</a> or
    <a href="/sync-page">a single page</a>.
  </p>
{:else}
  <table class="batches">
    <thead>
      <tr>
        <th scope="col">#</th>
        <th scope="col">Status</th>
        <th scope="col">Direction</th>
        <th scope="col">Progress</th>
        <th scope="col"></th>
      </tr>
    </thead>
    <tbody>
      {#each batches as batch}
        <tr>
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
        <tr class="run-row">
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
    margin-top: 1.5rem;
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
</style>
