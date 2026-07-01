<script lang="ts">
  import { goto } from '$app/navigation';
  import { page as routePage } from '$app/state';
  import { onMount } from 'svelte';
  import { approvePendingCommit, listPendingCommits } from '$lib/api';
  import type { Commit, PendingCommitPage } from '$lib/types';

  type DiffKind = 'same' | 'added' | 'removed';

  interface DiffLine {
    kind: DiffKind;
    text: string;
    index: number;
  }

  let item: PendingCommitPage | null = $state(null);
  let loading = $state(true);
  let approving = $state(false);
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

  function diffLines(staged: PendingCommitPage): DiffLine[] {
    if (staged.journals.length < 2) {
      return staged.submitted_body.split('\n').map((text, index) => ({
        kind: 'same',
        text,
        index
      }));
    }

    const before = staged.journals[0].body.split('\n');
    const after = staged.submitted_body.split('\n');
    const rows: DiffLine[] = [];
    const total = Math.max(before.length, after.length);
    for (let index = 0; index < total; index += 1) {
      const oldLine = before[index];
      const newLine = after[index];
      if (oldLine === newLine) {
        rows.push({ kind: 'same', text: newLine ?? '', index });
      } else {
        if (oldLine !== undefined) rows.push({ kind: 'removed', text: oldLine, index });
        if (newLine !== undefined) rows.push({ kind: 'added', text: newLine, index });
      }
    }
    return rows;
  }

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

  async function approvePage(): Promise<void> {
    if (!item) return;

    approving = true;
    error = '';
    lastCommit = null;
    try {
      lastCommit = await approvePendingCommit(item.page_pk);
      if (lastCommit.status === 'success') {
        await goto('/commits');
      } else {
        await loadPage();
      }
    } catch (err) {
      error = err instanceof Error ? err.message : 'Commit failed';
    } finally {
      approving = false;
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
        <button class="approve" type="button" onclick={() => approvePage()} disabled={approving}>
          {approving ? 'Pushing...' : 'Approve page'}
        </button>
      </header>

      <section class="history">
        <p class="eyebrow">Local saves</p>
        <ol>
          {#each item.journals as journal}
            <li>
              <strong>#{journal.pk}</strong>
              <span>{formatDate(journal.saved_at)}</span>
              <small>{journal.body.length.toLocaleString()} chars</small>
            </li>
          {/each}
        </ol>
      </section>

      <section class="diff">
        <div class="section-title">
          <p class="eyebrow">{item.journals.length > 1 ? 'Save diff' : 'Submitted text'}</p>
          <span>{formatDate(item.latest_saved_at)}</span>
        </div>
        <pre aria-label="Staged wikitext">{#each diffLines(item) as row}<span class={row.kind}>{row.kind === 'added' ? '+ ' : row.kind === 'removed' ? '- ' : '  '}{row.text || ' '}</span>{'\n'}{/each}</pre>
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

  .approve {
    cursor: pointer;
    border: 0;
    border-radius: 12px;
    background: #286b4c;
    color: #fffdf5;
    font-family: "Avenir Next", "Gill Sans", sans-serif;
    font-size: 0.78rem;
    font-weight: 800;
    letter-spacing: 0.06em;
    padding: 0.8rem 0.95rem;
    text-transform: uppercase;
    white-space: nowrap;
  }

  .approve:disabled {
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
    grid-template-columns: 5rem minmax(0, 1fr) auto;
    gap: 0.75rem;
    padding-top: 0.5rem;
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

  pre {
    width: 100%;
    max-height: 66vh;
    overflow: auto;
    border: 1px solid rgba(72, 49, 31, 0.14);
    border-radius: 12px;
    background: #241b13;
    color: #fff8e6;
    font-family: "JetBrains Mono", "SFMono-Regular", Consolas, monospace;
    font-size: 0.86rem;
    line-height: 1.55;
    margin: 0.75rem 0 0;
    padding: 1rem;
    white-space: pre-wrap;
  }

  pre span {
    display: block;
    min-height: 1.55em;
  }

  pre span.added {
    color: #a7f0ba;
  }

  pre span.removed {
    color: #ffb4a2;
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
