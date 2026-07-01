<script lang="ts">
  import { onMount } from 'svelte';
  import { listPendingCommits } from '$lib/api';
  import type { PendingCommitPage } from '$lib/types';

  let pending: PendingCommitPage[] = $state([]);
  let loading = $state(true);
  let error = $state('');

  function formatDate(value: string): string {
    return new Intl.DateTimeFormat(undefined, {
      dateStyle: 'medium',
      timeStyle: 'short'
    }).format(new Date(value));
  }

  async function loadPending(): Promise<void> {
    loading = true;
    error = '';
    try {
      pending = await listPendingCommits();
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to load staged edits';
    } finally {
      loading = false;
    }
  }

  onMount(loadPending);
</script>

<section class="page-heading">
  <p class="eyebrow">Review</p>
  <h1>Staged edits</h1>
  <p class="count">
    {loading ? 'Loading' : `${pending.length} page${pending.length === 1 ? '' : 's'}`}
  </p>
</section>

{#if error}
  <div class="notice">{error}</div>
{/if}

<div class="toolbar">
  <button type="button" onclick={() => loadPending()} disabled={loading}>
    {loading ? 'Refreshing...' : 'Refresh'}
  </button>
</div>

{#if loading}
  <div class="empty">Loading staged edits...</div>
{:else if pending.length === 0}
  <div class="empty">No staged edits are waiting for review.</div>
{:else}
  <section class="staged-grid" aria-label="Staged pages">
    {#each pending as item}
      <a class="staged-page" href={`/commits/${item.page_pk}`}>
        <span class="title">{item.title}</span>
        <span class="meta">
          <span>{item.pending_count} save{item.pending_count === 1 ? '' : 's'}</span>
          <span>base r{item.base_revid}</span>
          {#if item.current_revid}
            <span>cache r{item.current_revid}</span>
          {/if}
          <span>{formatDate(item.latest_saved_at)}</span>
        </span>
      </a>
    {/each}
  </section>
{/if}

<style>
  .page-heading {
    max-width: 64rem;
  }

  .page-heading h1 {
    font-size: clamp(2.6rem, 6vw, 5rem);
  }

  .toolbar {
    margin: 1.25rem 0;
  }

  button {
    cursor: pointer;
    border: 0;
    border-radius: 12px;
    background: #9c5632;
    color: #fff8e6;
    font-family: "Avenir Next", "Gill Sans", sans-serif;
    font-size: 0.78rem;
    font-weight: 800;
    letter-spacing: 0.06em;
    padding: 0.8rem 1rem;
    text-transform: uppercase;
  }

  button:disabled {
    cursor: progress;
    opacity: 0.62;
  }

  .staged-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(20rem, 1fr));
    gap: 0.85rem;
  }

  .staged-page {
    border: 1px solid rgba(72, 49, 31, 0.18);
    border-radius: 14px;
    background: rgba(255, 252, 240, 0.74);
    box-shadow: 0 14px 34px rgba(62, 44, 30, 0.08);
    color: inherit;
    display: grid;
    gap: 0.75rem;
    min-height: 9rem;
    padding: 1rem;
    text-decoration: none;
    transition: border-color 160ms ease, transform 160ms ease;
  }

  .staged-page:hover {
    border-color: rgba(156, 86, 50, 0.58);
    transform: translateY(-1px);
  }

  .title {
    font-size: 1.2rem;
    font-weight: 800;
    line-height: 1.25;
    overflow-wrap: anywhere;
  }

  .meta {
    align-self: end;
    display: flex;
    flex-wrap: wrap;
    gap: 0.45rem 0.75rem;
    color: #73583d;
    font-family: "Avenir Next", "Gill Sans", sans-serif;
    font-size: 0.74rem;
    font-weight: 700;
    letter-spacing: 0.04em;
    text-transform: uppercase;
  }
</style>
