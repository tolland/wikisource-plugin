<script lang="ts">
  import { goto } from '$app/navigation';
  import { page as routePage } from '$app/state';
  import { onMount } from 'svelte';
  import { approvePendingCommit, cancelPendingCommit, listPendingCommits } from '$lib/api';
  import { buildLineDiff } from '$lib/diff';
  import type { Commit, PendingCommitPage } from '$lib/types';

  let item: PendingCommitPage | null = $state(null);
  let loading = $state(true);
  let action: 'approve' | 'force' | 'cancel' | null = $state(null);
  let error = $state('');
  let lastCommit: Commit | null = $state(null);

  function pagePk(): number {
    return Number(routePage.params.page_pk);
  }

  function formatDate(value: string): string {
    return new Intl.DateTimeFormat(undefined, {
      dateStyle: 'medium',
      timeStyle: 'short'
    }).format(new Date(value));
  }

  function lineCount(value: string): number {
    if (!value) return 0;
    return value.split('\n').length;
  }

  const diff = $derived.by(() => {
    const staged = item;
    return staged ? buildLineDiff(staged.base_body ?? '', staged.submitted_body) : null;
  });
  const hasRevisionWarning = $derived.by(() => {
    const staged = item;
    return staged?.current_revid != null && staged.current_revid !== staged.base_revid;
  });
  const canForceOverwrite = $derived.by(() => {
    const commit = lastCommit;
    return hasRevisionWarning || commit?.status === 'conflict';
  });

  async function loadPage(): Promise<void> {
    loading = true;
    error = '';
    try {
      const pending = await listPendingCommits();
      item = pending.find((entry) => entry.page_pk === pagePk()) ?? null;
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to load staged edit';
    } finally {
      loading = false;
    }
  }

  async function approvePage(force = false): Promise<void> {
    if (!item) return;

    action = force ? 'force' : 'approve';
    error = '';
    lastCommit = null;
    try {
      lastCommit = await approvePendingCommit(item.page_pk, force);
      if (lastCommit.status === 'success') {
        await goto('/commits');
      } else {
        await loadPage();
      }
    } catch (err) {
      error = err instanceof Error ? err.message : 'Commit failed';
    } finally {
      action = null;
    }
  }

  async function cancelPage(): Promise<void> {
    if (!item) return;
    if (!window.confirm('Discard all pending local saves for this page?')) return;

    action = 'cancel';
    error = '';
    try {
      await cancelPendingCommit(item.page_pk);
      await goto('/commits');
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to cancel staged edit';
    } finally {
      action = null;
    }
  }

  onMount(loadPage);
</script>

<section class="review-route">
  <a class="back-link" href="/commits">Back to staged edits</a>

  {#if error}
    <div class="notice">{error}</div>
  {/if}

  {#if lastCommit}
    <div class:notice={lastCommit.status !== 'success'} class="commit-result">
      <strong>{lastCommit.status}</strong>
      {#if lastCommit.result_revid}
        <span>revision {lastCommit.result_revid}</span>
      {/if}
      {#if lastCommit.error_message}
        <span>{lastCommit.error_message}</span>
      {/if}
    </div>
  {/if}

  {#if loading}
    <div class="empty">Loading staged edit...</div>
  {:else if item}
    <article class="review-card">
      <header class="review-header">
        <div>
          <p class="eyebrow">Page {item.page_pk}</p>
          <h1>{item.title}</h1>
          <div class="meta">
            <span>base r{item.base_revid}</span>
            {#if item.current_revid}
              <span>cache r{item.current_revid}</span>
            {/if}
            <span>{lineCount(item.submitted_body).toLocaleString()} lines</span>
            <span>{item.submitted_body.length.toLocaleString()} characters</span>
          </div>
        </div>
        <div class="actions">
          <button class="approve" type="button" onclick={() => approvePage()} disabled={action !== null}>
            {action === 'approve' ? 'Pushing...' : 'Approve page'}
          </button>
          {#if canForceOverwrite}
            <button
              class="force"
              type="button"
              onclick={() => approvePage(true)}
              disabled={action !== null}
            >
              {action === 'force' ? 'Overwriting...' : 'Force overwrite'}
            </button>
          {/if}
          <button class="cancel" type="button" onclick={() => cancelPage()} disabled={action !== null}>
            {action === 'cancel' ? 'Cancelling...' : 'Cancel'}
          </button>
        </div>
      </header>

      <section class="history">
        <p class="eyebrow">Local saves</p>
        <ol>
          {#each item.journals as journal}
            <li>
              <strong>#{journal.pk}</strong>
              <span>{formatDate(journal.saved_at)}</span>
              <span>#{journal.base_revid}</span>
              <small>{journal.body.length.toLocaleString()} chars</small>
            </li>
          {/each}
        </ol>
      </section>

      <section class="diff">
        <div class="section-title">
          <p class="eyebrow">Final change vs original</p>
          {#if diff}
            <span class="diff-stats">
              <span class="stat-added">+{diff.added.toLocaleString()}</span>
              <span class="stat-removed">-{diff.removed.toLocaleString()}</span>
              <span>{formatDate(item.latest_saved_at)}</span>
            </span>
          {/if}
        </div>

        {#if item.base_body == null}
          <p class="diff-note">
            No cached original for this page (new page or never fetched) — the whole submitted
            text is shown as added.
          </p>
        {:else if hasRevisionWarning}
          <p class="diff-note">
            The diff is against the cached remote body currently stored in Page.text at revision
            {item.current_revid}. This pending edit was based on revision {item.base_revid}, so
            this is not a three-way conflict resolution view and may not show the exact text from
            the base revision.
          </p>
        {/if}

        {#if diff}
          {#if diff.blocks.length === 0}
            <div class="empty">The submitted text is identical to the original.</div>
          {:else}
            <div class="diff-blocks" aria-label="Staged wikitext diff">
              {#each diff.blocks as block}
                {#if block.skippedBefore > 0}
                  <div class="diff-skip">
                    {block.skippedBefore.toLocaleString()} unchanged line{block.skippedBefore === 1
                      ? ''
                      : 's'} hidden
                  </div>
                {/if}
                <div class="diff-block">
                  <div class="diff-block-header">
                    @@ -{block.oldStart},{block.oldLines} +{block.newStart},{block.newLines} @@
                  </div>
                  <pre>{#each block.rows as row}<span class={row.kind}><span class="lineno">{row.oldNo ?? ''}</span><span class="lineno">{row.newNo ?? ''}</span><span class="marker">{row.kind === 'added' ? '+' : row.kind === 'removed' ? '-' : ' '}</span>{row.text || ' '}</span>{'\n'}{/each}</pre>
                </div>
              {/each}
            </div>
          {/if}
        {/if}
      </section>
    </article>
  {:else}
    <div class="empty">No staged edit found for this page.</div>
  {/if}
</section>

<style>
  .review-route {
    max-width: 100rem;
  }

  .back-link {
    display: inline-block;
    margin-bottom: 1rem;
    color: #7d4428;
    font-family: "Avenir Next", "Gill Sans", sans-serif;
    font-size: 0.78rem;
    font-weight: 800;
    letter-spacing: 0.06em;
    text-decoration: none;
    text-transform: uppercase;
  }

  .back-link:hover {
    color: #9c5632;
  }

  .commit-result {
    border: 1px solid rgba(40, 107, 76, 0.34);
    border-radius: 12px;
    background: rgba(229, 246, 235, 0.72);
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem 1rem;
    margin-bottom: 1rem;
    padding: 0.85rem 1rem;
  }

  .commit-result strong {
    font-family: "Avenir Next", "Gill Sans", sans-serif;
    text-transform: uppercase;
  }

  .review-card {
    border: 1px solid rgba(72, 49, 31, 0.18);
    border-radius: 16px;
    background: rgba(255, 252, 240, 0.72);
    box-shadow: 0 16px 44px rgba(62, 44, 30, 0.1);
    padding: clamp(1rem, 2vw, 1.5rem);
  }

  .review-header {
    display: flex;
    align-items: start;
    justify-content: space-between;
    gap: 1.25rem;
  }

  .review-header h1 {
    max-width: 78rem;
    font-size: clamp(2rem, 4.5vw, 4.4rem);
    overflow-wrap: anywhere;
  }

  .actions {
    display: flex;
    flex-wrap: wrap;
    justify-content: flex-end;
    gap: 0.55rem;
  }

  .actions button {
    cursor: pointer;
    border: 0;
    border-radius: 12px;
    font-family: "Avenir Next", "Gill Sans", sans-serif;
    font-size: 0.78rem;
    font-weight: 800;
    letter-spacing: 0.06em;
    padding: 0.8rem 0.95rem;
    text-transform: uppercase;
    white-space: nowrap;
  }

  .approve {
    background: #286b4c;
    color: #fffdf5;
  }

  .force {
    background: #7f2f22;
    color: #fff8e6;
  }

  .cancel {
    border: 1px solid rgba(72, 49, 31, 0.24);
    background: rgba(255, 252, 240, 0.78);
    color: #73583d;
  }

  .actions button:disabled {
    cursor: progress;
    opacity: 0.62;
  }

  .history {
    margin-top: 1.4rem;
  }

  .history ol {
    display: grid;
    gap: 0.45rem;
    list-style: none;
    margin: 0.7rem 0 0;
    padding: 0;
  }

  .history li {
    border-top: 1px solid rgba(72, 49, 31, 0.12);
    display: grid;
    grid-template-columns: 5rem minmax(0, 1fr) minmax(0, 1fr) auto;
    gap: 0.75rem;
    padding-top: 0.5rem;
  }

  .history li > :nth-child(2) {
      justify-self: start;
  }

  .history li > :nth-child(3) {
      justify-self: end;
  }

  .history span,
  .history small,
  .section-title span {
    color: #73583d;
    font-family: "Avenir Next", "Gill Sans", sans-serif;
    font-size: 0.76rem;
  }

  .diff {
    margin-top: 1.4rem;
  }

  .section-title {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 1rem;
  }

  .diff-stats {
    display: flex;
    gap: 0.6rem;
    align-items: baseline;
    font-family: "JetBrains Mono", "SFMono-Regular", Consolas, monospace;
    font-size: 0.78rem;
    font-weight: 700;
  }

  .stat-added {
    color: #286b4c;
  }

  .stat-removed {
    color: #a13c22;
  }

  .diff-note {
    border: 1px solid rgba(156, 86, 50, 0.32);
    border-radius: 10px;
    background: rgba(255, 241, 214, 0.7);
    color: #73583d;
    font-size: 0.84rem;
    margin: 0.75rem 0 0;
    padding: 0.6rem 0.85rem;
  }

  .diff-blocks {
    display: grid;
    gap: 0.6rem;
    margin-top: 0.75rem;
  }

  .diff-skip {
    color: #73583d;
    font-family: "Avenir Next", "Gill Sans", sans-serif;
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.05em;
    padding: 0.15rem 0.4rem;
    text-align: center;
    text-transform: uppercase;
  }

  .diff-block {
    border: 1px solid rgba(72, 49, 31, 0.14);
    border-radius: 12px;
    overflow: hidden;
  }

  .diff-block-header {
    background: #3a2c1f;
    color: #d8c6a8;
    font-family: "JetBrains Mono", "SFMono-Regular", Consolas, monospace;
    font-size: 0.76rem;
    padding: 0.45rem 1rem;
  }

  pre {
    width: 100%;
    max-height: 66vh;
    overflow: auto;
    background: #241b13;
    color: #fff8e6;
    font-family: "JetBrains Mono", "SFMono-Regular", Consolas, monospace;
    font-size: 0.86rem;
    line-height: 1.55;
    margin: 0;
    padding: 0.6rem 0;
    white-space: pre-wrap;
  }

  pre > span {
    display: block;
    min-height: 1.55em;
    padding: 0 1rem 0 0.4rem;
  }

  pre > span.added {
    background: rgba(64, 128, 90, 0.28);
    color: #a7f0ba;
  }

  pre > span.removed {
    background: rgba(150, 62, 40, 0.3);
    color: #ffb4a2;
  }

  .lineno {
    display: inline-block;
    width: 3.2em;
    color: rgba(255, 248, 230, 0.42);
    text-align: right;
    padding-right: 0.6em;
    user-select: none;
  }

  .marker {
    display: inline-block;
    width: 1.1em;
    user-select: none;
  }

  @media (max-width: 800px) {
    .review-header {
      display: grid;
    }

    .approve {
      justify-self: start;
    }

    .history li {
      grid-template-columns: 1fr;
    }
  }
</style>
