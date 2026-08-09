<script lang="ts">
  import Notice from '$lib/components/Notice.svelte';
  import type { IndexPageSummary } from '$lib/types';

  /**
   * Collapsible card tray for picking one Index: work. Expanded, it's a grid
   * of cards spanning the full content width (rather than a permanent
   * sidebar list) -- worthwhile screen space to give up only while a work is
   * actually being chosen. Clicking a card selects it and collapses the tray
   * to a one-line summary, so the caller's content area gets the width back
   * for whatever it does with the selection.
   */
  let {
    works,
    selected = $bindable(null),
    loading = false,
    error = ''
  }: {
    works: IndexPageSummary[];
    selected?: IndexPageSummary | null;
    loading?: boolean;
    error?: string;
  } = $props();

  let expanded = $state(true);

  function choose(work: IndexPageSummary): void {
    selected = work;
    expanded = false;
  }
</script>

<div class="work-picker">
  {#if error}
    <Notice>{error}</Notice>
  {/if}

  {#if !expanded && selected}
    <button type="button" class="summary-bar" onclick={() => (expanded = true)}>
      <span class="summary-title">{selected.title}</span>
      <span class="summary-meta">
        {selected.family}/{selected.code}
        {#if selected.page_count}
          · {selected.page_count} pages
        {/if}
      </span>
      <span class="change">change</span>
    </button>
  {:else if loading}
    <p class="state">Loading Index pages...</p>
  {:else if works.length === 0}
    <p class="state">No records found with content_model "proofread-index".</p>
  {:else}
    <div class="card-grid" role="listbox" aria-label="Works">
      {#each works as work}
        <button
          type="button"
          class="card"
          class:active={selected?.pk === work.pk}
          role="option"
          aria-selected={selected?.pk === work.pk}
          onclick={() => choose(work)}
        >
          <span class="title">{work.title}</span>
          <small>
            {work.family}/{work.code}
            {#if work.page_count} · {work.page_count} pages{/if}
          </small>
        </button>
      {/each}
    </div>
  {/if}
</div>

<style>
  .work-picker {
    margin-bottom: 1.4rem;
  }

  .state {
    color: #73583d;
  }

  .summary-bar {
    display: flex;
    align-items: baseline;
    gap: 0.75rem;
    width: 100%;
    cursor: pointer;
    border: 1px solid rgba(87, 58, 37, 0.2);
    border-radius: 16px;
    background: rgba(255, 252, 240, 0.64);
    color: inherit;
    padding: 0.75rem 1.1rem;
    text-align: left;
  }

  .summary-bar:hover {
    border-color: #9c5632;
    background: #fff7e6;
  }

  .summary-title {
    font-weight: 700;
  }

  .summary-meta {
    color: #73583d;
    font-size: 0.85rem;
    font-family: 'Avenir Next', 'Gill Sans', sans-serif;
  }

  .change {
    margin-left: auto;
    color: #9c5632;
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }

  .card-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(15rem, 1fr));
    gap: 0.75rem;
  }

  .card {
    cursor: pointer;
    border: 1px solid rgba(87, 58, 37, 0.2);
    border-radius: 18px;
    background: rgba(255, 252, 240, 0.64);
    color: inherit;
    padding: 1rem;
    text-align: left;
    transition:
      transform 160ms ease,
      border-color 160ms ease,
      background 160ms ease;
  }

  .card:hover,
  .card.active {
    transform: translateY(-1px);
    border-color: #9c5632;
    background: #fff7e6;
  }

  .card span,
  .card small {
    display: block;
  }

  .title {
    font-weight: 700;
  }

  .card small {
    margin-top: 0.45rem;
    color: #73583d;
    font-family: 'Avenir Next', 'Gill Sans', sans-serif;
  }
</style>
