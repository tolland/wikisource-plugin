<script lang="ts">
  import { onMount } from 'svelte';
  import { page as routePage } from '$app/state';
  import { abortBatch, approveBatch, getBatch, pushBatchPage, skipPromotion } from '$lib/api';
  import ActionButton from '$lib/components/ActionButton.svelte';
  import Notice from '$lib/components/Notice.svelte';
  import PageHeading from '$lib/components/PageHeading.svelte';
  import TextField from '$lib/components/TextField.svelte';
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
  let approvedBy = $state('');

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
    return batch.status === 'approved' || batch.status === 'running';
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

  const approve = () =>
    run(() => approveBatch(batchPk, approvedBy), `Approved by ${approvedBy}.`);

  const pushNext = () =>
    run(() => pushBatchPage(batchPk), 'Pushed one revision.');

  function unhappy(current: Batch): number {
    return current.promotions.filter(
      (row) => row.status === 'conflict' || row.status === 'error'
    ).length;
  }

  async function pushRest(): Promise<void> {
    // The same one-page call in a loop, stopping the moment a row does not
    // push cleanly. A conflict means the world moved under the batch, and the
    // remaining pages were staged on the same assumption -- grinding through
    // them is how one bad assumption gets written three hundred times.
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
          message = `Stopped after ${pushed} page(s): a row did not push cleanly.`;
          return;
        }
      }
      message = `Pushed ${pushed} page(s).`;
    } catch (err) {
      error = err instanceof Error ? err.message : 'The run stopped on an error';
    } finally {
      busy = false;
    }
  }

  const skip = (row: PromotionRow) =>
    run(() => skipPromotion(batchPk, row.pk), `Skipped ${row.target_title}.`);

  const abort = () =>
    run(() => abortBatch(batchPk), 'Run aborted. Pages already pushed stay pushed.');

  onMount(load);
</script>

<p class="crumb"><a href="/sync">&larr; Sync report</a></p>

{#if loading}
  <p class="state">Loading...</p>
{:else if batch}
  <PageHeading
    eyebrow={`${batch.source_site} → ${batch.target_site}`}
    title={batch.label ?? `Batch #${batch.pk}`}
    count={`${batch.status}${batch.approved_by ? ` · approved by ${batch.approved_by}` : ''}`}
  >
    <p class="other">{batch.source_index_title}</p>
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

  {#if batch.status === 'draft'}
    <section class="approve" aria-label="Approval">
      <h2>Approve this run</h2>
      <p>
        Nothing is written until somebody signs it off, and the name is stored with
        the batch &mdash; "did a person agree to this" is exactly the fact an audit
        wants, and a convenient default would erase it.
      </p>
      <div class="row">
        <TextField label="Approved by" bind:value={approvedBy} placeholder="your name" />
        <ActionButton disabled={busy || !approvedBy.trim()} onclick={approve}>
          Approve
        </ActionButton>
      </div>
    </section>
  {:else}
    <section class="run" aria-label="Push">
      <div class="row">
        <ActionButton disabled={busy || !canPush} onclick={pushNext}>
          Push the next page
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
        moved, and the remaining pages are built on the same assumption. Aborting
        skips what is left; pages already pushed stay pushed.
      </small>
    </section>
  {/if}

  <table class="promotions">
    <thead>
      <tr>
        <th scope="col">#</th>
        <th scope="col">Status</th>
        <th scope="col">Page / source revision</th>
        <th scope="col">Intent</th>
        <th scope="col">Base</th>
        <th scope="col">Result</th>
        <th scope="col"></th>
      </tr>
    </thead>
    <tbody>
      {#each batch.promotions as row}
        <tr>
          <td>{row.page_number ?? '?'}</td>
          <td>
            <span class="chip {STATUSES[row.status]?.tone ?? 'quiet'}">
              {STATUSES[row.status]?.label ?? row.status}
            </span>
          </td>
          <td class="title">
            {row.target_title}
            <small>source revision #{row.source_revision_pk} · {row.body_length.toLocaleString()} characters</small>
            {#if row.error_message}
              <small class="why">{row.error_message}</small>
            {/if}
          </td>
          <td>{row.intent}</td>
          <td class="revs">{row.base_revid ?? (row.predecessor_promotion_pk ? 'previous result' : '—')}</td>
          <td class="revs">{row.result_revid ?? '—'}</td>
          <td>
            {#if row.status === 'staged'}
              <button type="button" class="link" disabled={busy} onclick={() => skip(row)}>
                Skip
              </button>
            {/if}
          </td>
        </tr>
      {/each}
    </tbody>
  </table>
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

  h2 {
    margin: 0 0 0.4rem;
    font-size: 1rem;
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

  .approve,
  .run {
    border: 1px solid rgba(72, 49, 31, 0.18);
    border-radius: 20px;
    background: rgba(255, 248, 230, 0.72);
    margin-bottom: 1.5rem;
    padding: 1.1rem 1.2rem;
  }

  .approve p {
    margin: 0 0 0.8rem;
    max-width: 46rem;
    color: #73583d;
    font-size: 0.88rem;
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
    width: 100%;
    border-collapse: collapse;
  }

  .promotions th,
  .promotions td {
    border-bottom: 1px solid rgba(72, 49, 31, 0.14);
    padding: 0.55rem 0.5rem;
    text-align: left;
    vertical-align: top;
  }

  .promotions th {
    color: #73583d;
    font-family: "Avenir Next", "Gill Sans", sans-serif;
    font-size: 0.72rem;
    letter-spacing: 0.06em;
    text-transform: uppercase;
  }

  .promotions .title {
    overflow-wrap: anywhere;
  }

  .promotions small {
    display: block;
    margin-top: 0.2rem;
    color: #73583d;
    font-size: 0.76rem;
  }

  .promotions small.why {
    color: #7d5510;
  }

  .promotions .revs {
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 0.82rem;
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
