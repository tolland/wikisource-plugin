<script lang="ts">
  import { onMount } from 'svelte';
  import { approvePendingCommit, listPendingCommits } from '$lib/api';
  import ActionButton from '$lib/components/ActionButton.svelte';
  import Notice from '$lib/components/Notice.svelte';
  import PageHeading from '$lib/components/PageHeading.svelte';
  import SelectField from '$lib/components/SelectField.svelte';
  import StagedPageCard from '$lib/components/StagedPageCard.svelte';
  import type { PendingCommitPage } from '$lib/types';

  let pending: PendingCommitPage[] = $state([]);
  let loading = $state(true);
  let approving = $state(false);
  let progress = $state<{ current: number; total: number; title: string } | null>(null);
  let error = $state('');
  let message = $state('');
  let selectedPagePks: number[] = $state([]);
  let filter: 'all' | 'uncontroversial' | 'conflicted' = $state('all');
  let failures: { title: string; error: string }[] = $state([]);

  function isConflicted(item: PendingCommitPage): boolean {
    return item.current_revid != null && item.current_revid !== item.base_revid;
  }

  function isUncontroversial(item: PendingCommitPage): boolean {
    return !isConflicted(item);
  }

  const uncontroversialPages = $derived(pending.filter(isUncontroversial));
  const conflictedPages = $derived(pending.filter(isConflicted));

  const visible = $derived.by((): PendingCommitPage[] => {
    if (filter === 'uncontroversial') return uncontroversialPages;
    if (filter === 'conflicted') return conflictedPages;
    return pending;
  });

  const allVisibleSelected = $derived(
    visible.length > 0 && visible.every((p) => selectedPagePks.includes(p.page_pk))
  );

  const selectedCount = $derived(selectedPagePks.length);

  async function loadPending(): Promise<void> {
    loading = true;
    error = '';
    try {
      pending = await listPendingCommits();
      const currentPks = new Set(pending.map((p) => p.page_pk));
      selectedPagePks = selectedPagePks.filter((pk) => currentPks.has(pk));
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to load staged edits';
    } finally {
      loading = false;
    }
  }

  function togglePage(pagePk: number): void {
    selectedPagePks = selectedPagePks.includes(pagePk)
      ? selectedPagePks.filter((pk) => pk !== pagePk)
      : [...selectedPagePks, pagePk];
  }

  function selectUncontroversial(): void {
    const unconflictedPks = uncontroversialPages.map((p) => p.page_pk);
    selectedPagePks = [...new Set([...selectedPagePks, ...unconflictedPks])];
  }

  function toggleVisible(): void {
    const visiblePks = visible.map((p) => p.page_pk);
    if (allVisibleSelected) {
      selectedPagePks = selectedPagePks.filter((pk) => !visiblePks.includes(pk));
    } else {
      selectedPagePks = [...new Set([...selectedPagePks, ...visiblePks])];
    }
  }

  function clearSelection(): void {
    selectedPagePks = [];
  }

  async function approveSelected(): Promise<void> {
    if (selectedPagePks.length === 0 || approving) return;

    approving = true;
    error = '';
    message = '';
    failures = [];

    const toApprove = pending.filter((item) => selectedPagePks.includes(item.page_pk));
    let successes = 0;
    const batchFailures: { title: string; error: string }[] = [];
    const succeededPks: number[] = [];

    for (let i = 0; i < toApprove.length; i++) {
      const item = toApprove[i];
      progress = { current: i + 1, total: toApprove.length, title: item.title };

      try {
        const commit = await approvePendingCommit(item.page_pk);
        if (commit.status === 'success') {
          successes++;
          succeededPks.push(item.page_pk);
        } else {
          batchFailures.push({
            title: item.title,
            error: commit.error_message || `Commit returned status: ${commit.status}`
          });
        }
      } catch (err) {
        batchFailures.push({
          title: item.title,
          error: err instanceof Error ? err.message : 'Unknown error during commit'
        });
      }
    }

    selectedPagePks = selectedPagePks.filter((pk) => !succeededPks.includes(pk));
    progress = null;
    approving = false;
    failures = batchFailures;

    if (batchFailures.length === 0) {
      message = `Successfully approved and pushed ${successes} page${successes === 1 ? '' : 's'}.`;
    } else if (successes > 0) {
      message = `Approved and pushed ${successes} page${successes === 1 ? '' : 's'}. ${batchFailures.length} page${batchFailures.length === 1 ? '' : 's'} failed.`;
    } else {
      error = `Failed to approve selected page${toApprove.length === 1 ? '' : 's'}.`;
    }

    await loadPending();
  }

  onMount(loadPending);
</script>

<PageHeading
  eyebrow="Review"
  title="Staged edits"
  count={loading ? 'Loading' : `${pending.length} page${pending.length === 1 ? '' : 's'}`}
/>

{#if error}
  <Notice kind="error">{error}</Notice>
{/if}

{#if message}
  <Notice kind="success">{message}</Notice>
{/if}

{#if failures.length > 0}
  <div class="failures-box">
    <strong>Failed commits ({failures.length}):</strong>
    <ul>
      {#each failures as failure}
        <li><strong>{failure.title}:</strong> {failure.error}</li>
      {/each}
    </ul>
  </div>
{/if}

{#if approving && progress}
  <div class="progress-box">
    Pushing {progress.current} of {progress.total}: <strong>{progress.title}</strong>...
  </div>
{/if}

<div class="controls-panel">
  <div class="summary-chips">
    <span class="chip quiet">Total: <strong>{pending.length}</strong></span>
    <span class="chip go">Uncontroversial: <strong>{uncontroversialPages.length}</strong></span>
    {#if conflictedPages.length > 0}
      <span class="chip bad">Conflicted: <strong>{conflictedPages.length}</strong></span>
    {/if}
    {#if selectedCount > 0}
      <span class="chip in">Selected: <strong>{selectedCount}</strong></span>
    {/if}
  </div>

  <div class="toolbar">
    <div class="action-buttons">
      {#if uncontroversialPages.length > 0}
        <ActionButton
          variant="secondary"
          onclick={selectUncontroversial}
          disabled={loading || approving}
        >
          Select uncontroversial ({uncontroversialPages.length})
        </ActionButton>
      {/if}

      {#if pending.length > 0}
        <ActionButton
          variant="ghost"
          onclick={toggleVisible}
          disabled={loading || approving || visible.length === 0}
        >
          {allVisibleSelected ? 'Deselect visible' : 'Select all visible'}
        </ActionButton>

        {#if selectedCount > 0}
          <ActionButton
            variant="ghost"
            onclick={clearSelection}
            disabled={loading || approving}
          >
            Clear selection
          </ActionButton>
        {/if}
      {/if}

      <ActionButton
        variant="approve"
        onclick={() => void approveSelected()}
        disabled={loading || approving || selectedCount === 0}
      >
        {approving
          ? `Pushing (${progress?.current ?? 0}/${progress?.total ?? selectedCount})...`
          : selectedCount > 0
            ? `Approve ${selectedCount} selected`
            : 'Approve selected'}
      </ActionButton>

      <ActionButton
        variant="ghost"
        onclick={() => void loadPending()}
        disabled={loading || approving}
      >
        {loading ? 'Refreshing...' : 'Refresh'}
      </ActionButton>
    </div>

    {#if pending.length > 0}
      <div class="filter-box">
        <SelectField label="Filter" bind:value={filter}>
          <option value="all">All pages ({pending.length})</option>
          <option value="uncontroversial">Uncontroversial ({uncontroversialPages.length})</option>
          <option value="conflicted">Conflicted ({conflictedPages.length})</option>
        </SelectField>
      </div>
    {/if}
  </div>
</div>

{#if loading}
  <div class="empty">Loading staged edits...</div>
{:else if pending.length === 0}
  <div class="empty">No staged edits are waiting for review.</div>
{:else if visible.length === 0}
  <div class="empty">No staged edits match the selected filter.</div>
{:else}
  <section class="staged-grid" aria-label="Staged pages">
    {#each visible as item (item.page_pk)}
      <StagedPageCard
        {item}
        selectable={true}
        selected={selectedPagePks.includes(item.page_pk)}
        disabled={approving}
        ontoggle={() => togglePage(item.page_pk)}
      />
    {/each}
  </section>
{/if}

<style>
  .controls-panel {
    display: flex;
    flex-direction: column;
    gap: 0.85rem;
    margin: 1.25rem 0;
    padding: 1rem;
    border: 1px solid rgba(72, 49, 31, 0.14);
    border-radius: 16px;
    background: rgba(255, 252, 240, 0.55);
  }

  .summary-chips {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    align-items: center;
  }

  .chip {
    display: inline-flex;
    gap: 0.4rem;
    align-items: center;
    border: 1px solid rgba(72, 49, 31, 0.22);
    border-radius: 999px;
    padding: 0.25rem 0.65rem;
    font-family: "Avenir Next", "Gill Sans", sans-serif;
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.04em;
    text-transform: uppercase;
  }

  .chip.go {
    border-color: rgba(40, 107, 76, 0.42);
    background: rgba(229, 246, 235, 0.72);
    color: #24543f;
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

  .chip.in {
    border-color: rgba(61, 95, 146, 0.42);
    background: rgba(232, 240, 252, 0.72);
    color: #2d4875;
  }

  .toolbar {
    display: flex;
    flex-wrap: wrap;
    justify-content: space-between;
    align-items: flex-end;
    gap: 0.75rem;
  }

  .action-buttons {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    align-items: center;
  }

  .filter-box {
    min-width: 14rem;
  }

  .progress-box {
    margin-bottom: 1rem;
    padding: 0.85rem 1.25rem;
    border: 1px solid rgba(40, 107, 76, 0.35);
    border-radius: 14px;
    background: rgba(229, 246, 235, 0.8);
    color: #24543f;
    font-size: 0.88rem;
    animation: enter 160ms ease;
  }

  .failures-box {
    margin-bottom: 1rem;
    padding: 0.85rem 1.25rem;
    border: 1px dashed #b2452f;
    border-radius: 14px;
    background: rgba(255, 238, 233, 0.76);
    color: #7f2f22;
    font-size: 0.85rem;
  }

  .failures-box ul {
    margin: 0.5rem 0 0 1.25rem;
    padding: 0;
  }

  .failures-box li {
    margin-bottom: 0.25rem;
  }

  .staged-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(20rem, 1fr));
    gap: 0.85rem;
  }
</style>
