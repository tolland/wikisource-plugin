<script lang="ts">
  import { onMount } from 'svelte';
  import { page as routePage } from '$app/state';
  import { abortBatch, getBatch, pushBatchPage, skipPromotion } from '$lib/api';
  import ActionButton from '$lib/components/ActionButton.svelte';
  import DiffView from '$lib/components/DiffView.svelte';
  import Notice from '$lib/components/Notice.svelte';
  import PageHeading from '$lib/components/PageHeading.svelte';
  import { buildLineDiff } from '$lib/diff';
  import type { Batch, PromotionRow, PromotionStatus } from '$lib/types';

  /**
   * A staged push run, driven one source revision at a time.
   *
   * That is the whole shape of this page. There is no "push everything"
   * button, because a rate-limited wiki should get one request rather than
   * three hundred, and because a reviewer watching a run needs somewhere to
   * stop. "Push next" is the primary action; "push the rest" walks the same
   * call in a loop and halts the moment a row does not come back pushed.
   */

  const batchPk = Number(routePage.params.batch_pk);

  let batch: Batch | null = $state(null);
  let loading = $state(true);
  let busy = $state(false);
  let error = $state('');
  let message = $state('');

  const STATUSES: Record<PromotionStatus, { label: string; tone: string }> = {
    staged: { label: 'staged', tone: 'quiet' },
    pushed: { label: 'pushed', tone: 'go' },
    conflict: { label: 'conflict', tone: 'warn' },
    error: { label: 'error', tone: 'bad' },
    skipped: { label: 'skipped', tone: 'quiet' }
  };

  const canPush = $derived.by((): boolean => {
    if (batch === null) return false;
    if (batch.remaining === 0) return false;
    return batch.status === 'draft' || batch.status === 'running';
  });
  const diffs = $derived.by(() => {
    const result = new Map<number, ReturnType<typeof buildLineDiff>>();
    for (const row of batch?.promotions ?? []) {
      if (row.submitted_body != null) {
        result.set(row.pk, buildLineDiff(row.base_body ?? '', row.submitted_body));
      }
    }
    return result;
  });

  async function load(): Promise<void> {
    loading = true;
    error = '';
    try {
      batch = await getBatch(batchPk);
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to load the batch';
    } finally {
      loading = false;
    }
  }

  async function run(action: () => Promise<Batch>, note: string): Promise<void> {
    busy = true;
    error = '';
    message = '';
    try {
      batch = await action();
      message = note;
    } catch (err) {
      error = err instanceof Error ? err.message : 'The action failed';
    } finally {
      busy = false;
    }
  }

  const pushNext = () =>
    run(() => pushBatchPage(batchPk), 'Pushed one revision.');

  function unhappy(current: Batch): number {
    return current.promotions.filter(
      (row) => row.status === 'conflict' || row.status === 'error'
    ).length;
  }

  async function pushRest(): Promise<void> {
    // The same one-page call in a loop, stopping the moment a row does not
    // push cleanly. Every later revision depends on the preceding result, so a
    // conflict stops the chain rather than attempting descendants of a failed edit.
    busy = true;
    error = '';
    message = '';
    let pushed = 0;
    try {
      let current: Batch | null = batch;
      while (current !== null && current.remaining > 0) {
        const failuresBefore = unhappy(current);
        current = await pushBatchPage(batchPk);
        batch = current;
        pushed += 1;
        if (unhappy(current) > failuresBefore) {
          message = `Stopped after ${pushed} revision(s): a row did not push cleanly.`;
          return;
        }
      }
      message = `Pushed ${pushed} revision(s).`;
    } catch (err) {
      error = err instanceof Error ? err.message : 'The run stopped on an error';
    } finally {
      busy = false;
    }
  }

  const skip = (row: PromotionRow) =>
    run(() => skipPromotion(batchPk, row.pk), `Skipped source revision ${row.source_revid}.`);

  const abort = () =>
    run(() => abortBatch(batchPk), 'Run aborted. Revisions already pushed stay pushed.');

  onMount(load);
</script>

<p class="crumb"><a href="/sync">&larr; Sync report</a></p>

{#if loading}
  <p class="state">Loading...</p>
{:else if batch}
  <PageHeading
    eyebrow={`${batch.source_site} → ${batch.target_site}`}
    title={batch.label ?? `Batch #${batch.pk}`}
    count={batch.status}
  >
    <p class="other">{batch.source_title} &rarr; {batch.target_title}</p>
  </PageHeading>

  {#if error}
    <Notice>{error}</Notice>
  {/if}
  {#if message}
    <Notice kind="success">{message}</Notice>
  {/if}

  <section class="summary" aria-label="Progress">
    {#each Object.entries(batch.counts) as [status, count]}
      <span class="chip {STATUSES[status as PromotionStatus]?.tone ?? 'quiet'}">
        {STATUSES[status as PromotionStatus]?.label ?? status}
        <strong>{count}</strong>
      </span>
    {/each}
    <span class="total">{batch.remaining} still to push</span>
  </section>

  {#if batch.status === 'draft' || batch.status === 'running'}
    <section class="run" aria-label="Push">
      <div class="row">
        <ActionButton disabled={busy || !canPush} onclick={pushNext}>
          Push the next revision
        </ActionButton>
        <ActionButton variant="secondary" disabled={busy || !canPush} onclick={pushRest}>
          Push the rest
        </ActionButton>
        <ActionButton
          variant="danger"
          disabled={busy || batch.remaining === 0}
          onclick={abort}
        >
          Abort
        </ActionButton>
      </div>
      <small>
        One revision per request. &ldquo;Push the rest&rdquo; walks the same call and stops
        the moment a row does not push cleanly &mdash; a conflict means the world
        moved, and the remaining revisions depend on that failed step. Aborting
        skips what is left; revisions already pushed stay pushed.
      </small>
    </section>
  {/if}

  <section class="promotions" aria-label="Revision changes">
    <h2>Changes to push</h2>
    <p class="diff-intro">
      Each source revision is shown against the exact preceding state in this frozen
      batch. The first update starts at the linked target anchor; later revisions start
      at the preceding change below.
    </p>
    {#each batch.promotions as row, index}
      {@const diff = diffs.get(row.pk)}
      <article class="promotion">
        <header class="promotion-header">
          <div>
            <p class="revision-title">
              Revision {index + 1} of {batch.promotions.length}
              <span class="source-revid">source r{row.source_revid}</span>
            </p>
            <p class="revision-meta">
              {row.intent}
              &middot; base {row.base_revid ?? (row.predecessor_promotion_pk ? 'previous result' : 'new page')}
              {#if row.result_revid != null}&middot; result r{row.result_revid}{/if}
              &middot; {row.body_length.toLocaleString()} characters
            </p>
            <p class="comment">Edit summary: {row.comment || '(empty)'}</p>
          </div>
          <div class="promotion-actions">
            <span class="chip {STATUSES[row.status]?.tone ?? 'quiet'}">
              {STATUSES[row.status]?.label ?? row.status}
            </span>
            {#if row.status === 'staged'}
              <button type="button" class="link" disabled={busy} onclick={() => skip(row)}>
                Skip
              </button>
            {/if}
          </div>
        </header>
        {#if row.error_message}
          <p class="why">{row.error_message}</p>
        {/if}
        {#if row.submitted_body != null && row.base_body == null && row.intent === 'update'}
          <p class="why">The cached target anchor body is unavailable; the whole submitted body is shown as added.</p>
        {/if}
        {#if row.submitted_body == null}
          <p class="why">Diff bodies are unavailable. Reload after the wtbot service has restarted.</p>
        {/if}
        {#if diff}
          <div class="diff-summary">
            <span class="added">+{diff.added.toLocaleString()}</span>
            <span class="removed">-{diff.removed.toLocaleString()}</span>
            <span>{diff.unchanged.toLocaleString()} unchanged lines</span>
          </div>
          <DiffView {diff} />
        {/if}
      </article>
    {/each}
  </section>
{:else}
  <Notice>{error || 'No such batch.'}</Notice>
{/if}

<style>
  .crumb a {
    color: #73583d;
    font-family: "Avenir Next", "Gill Sans", sans-serif;
    font-size: 0.8rem;
    text-decoration: none;
  }

  .state,
  .other {
    color: #73583d;
  }

  .summary {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    align-items: center;
    margin: 1rem 0;
  }

  .total {
    color: #73583d;
    font-size: 0.86rem;
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

  .chip.quiet {
    border-color: rgba(72, 49, 31, 0.22);
    background: rgba(255, 252, 240, 0.7);
    color: #73583d;
  }

  .run {
    border: 1px solid rgba(72, 49, 31, 0.18);
    border-radius: 20px;
    background: rgba(255, 248, 230, 0.72);
    margin-bottom: 1.5rem;
    padding: 1.1rem 1.2rem;
  }

  .row {
    display: flex;
    flex-wrap: wrap;
    gap: 0.6rem;
    align-items: end;
  }

  .run small {
    display: block;
    max-width: 52rem;
    margin-top: 0.7rem;
    color: #8a6a45;
    font-size: 0.78rem;
  }

  .promotions {
    display: grid;
    gap: 1rem;
  }

  .promotions h2 {
    margin: 0;
    font-size: 1.2rem;
  }

  .diff-intro {
    max-width: 60rem;
    margin: -0.5rem 0 0;
    color: #73583d;
    font-size: 0.86rem;
  }

  .promotion {
    min-width: 0;
    border: 1px solid rgba(72, 49, 31, 0.18);
    border-radius: 16px;
    background: rgba(255, 252, 240, 0.7);
    padding: 1rem;
  }

  .promotion-header {
    display: flex;
    justify-content: space-between;
    gap: 1rem;
  }

  .revision-title {
    margin: 0;
    font-family: "Avenir Next", "Gill Sans", sans-serif;
    font-weight: 700;
  }

  .source-revid {
    margin-left: 0.5rem;
    color: #9c5632;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 0.82rem;
  }

  .revision-meta,
  .comment {
    margin: 0.25rem 0 0;
    color: #73583d;
    font-size: 0.8rem;
  }

  .comment {
    overflow-wrap: anywhere;
  }

  .promotion-actions {
    display: flex;
    gap: 0.6rem;
    align-items: center;
  }

  .why {
    margin: 0.75rem 0;
    color: #7d5510;
    font-size: 0.82rem;
  }

  .diff-summary {
    display: flex;
    gap: 0.75rem;
    margin-top: 0.75rem;
    color: #73583d;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 0.76rem;
  }

  .diff-summary .added {
    color: #286b4c;
  }

  .diff-summary .removed {
    color: #a13c22;
  }

  .link {
    border: 0;
    background: none;
    color: #9c5632;
    cursor: pointer;
    font-family: "Avenir Next", "Gill Sans", sans-serif;
    font-size: 0.76rem;
    font-weight: 700;
    text-transform: uppercase;
  }
</style>
