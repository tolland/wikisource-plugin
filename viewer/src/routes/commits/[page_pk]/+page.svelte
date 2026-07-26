<script lang="ts">
  import { goto } from '$app/navigation';
  import { page as routePage } from '$app/state';
  import { onMount } from 'svelte';
  import { approvePendingCommit, cancelPendingCommit, listPendingCommits } from '$lib/api';
  import ActionButton from '$lib/components/ActionButton.svelte';
  import DiffView from '$lib/components/DiffView.svelte';
  import JournalList from '$lib/components/JournalList.svelte';
  import Notice from '$lib/components/Notice.svelte';
  import { buildLineDiff } from '$lib/diff';
  import { formatDateTime, lineCount } from '$lib/format';
  import type { Commit, PendingCommitPage } from '$lib/types';

  let item: PendingCommitPage | null = $state(null);
  let loading = $state(true);
  let action: 'approve' | 'force' | 'cancel' | null = $state(null);
  let error = $state('');
  let lastCommit: Commit | null = $state(null);

  function pagePk(): number {
    return Number(routePage.params.page_pk);
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
    <Notice>{error}</Notice>
  {/if}

  {#if lastCommit}
    <Notice kind={lastCommit.status === 'success' ? 'success' : 'error'}>
      <strong class="commit-status">{lastCommit.status}</strong>
      {#if lastCommit.result_revid}
        <span>revision {lastCommit.result_revid}</span>
      {/if}
      {#if lastCommit.error_message}
        <span>{lastCommit.error_message}</span>
      {/if}
    </Notice>
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
          <ActionButton
            variant="approve"
            onclick={() => void approvePage()}
            disabled={action !== null}
          >
            {action === 'approve' ? 'Pushing...' : 'Approve page'}
          </ActionButton>
          {#if canForceOverwrite}
            <ActionButton
              variant="danger"
              onclick={() => void approvePage(true)}
              disabled={action !== null}
            >
              {action === 'force' ? 'Overwriting...' : 'Force overwrite'}
            </ActionButton>
          {/if}
          <ActionButton variant="ghost" onclick={() => void cancelPage()} disabled={action !== null}>
            {action === 'cancel' ? 'Cancelling...' : 'Cancel'}
          </ActionButton>
        </div>
      </header>

      <JournalList journals={item.journals} />

      <section class="diff">
        <div class="section-title">
          <p class="eyebrow">Final change vs original</p>
          {#if diff}
            <span class="diff-stats">
              <span class="stat-added">+{diff.added.toLocaleString()}</span>
              <span class="stat-removed">-{diff.removed.toLocaleString()}</span>
              <span>{formatDateTime(item.latest_saved_at)}</span>
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
          <DiffView {diff} />
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

  .commit-status {
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

  .diff {
    margin-top: 1.4rem;
  }

  .section-title {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 1rem;
  }

  .section-title span {
    color: #73583d;
    font-family: "Avenir Next", "Gill Sans", sans-serif;
    font-size: 0.76rem;
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

  @media (max-width: 800px) {
    .review-header {
      display: grid;
    }
  }
</style>
