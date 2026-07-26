<script lang="ts">
  import { onMount } from 'svelte';
  import { listPendingCommits } from '$lib/api';
  import ActionButton from '$lib/components/ActionButton.svelte';
  import Notice from '$lib/components/Notice.svelte';
  import PageHeading from '$lib/components/PageHeading.svelte';
  import StagedPageCard from '$lib/components/StagedPageCard.svelte';
  import type { PendingCommitPage } from '$lib/types';

  let pending: PendingCommitPage[] = $state([]);
  let loading = $state(true);
  let error = $state('');

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

<PageHeading
  eyebrow="Review"
  title="Staged edits"
  count={loading ? 'Loading' : `${pending.length} page${pending.length === 1 ? '' : 's'}`}
/>

{#if error}
  <Notice>{error}</Notice>
{/if}

<div class="toolbar">
  <ActionButton onclick={() => void loadPending()} disabled={loading}>
    {loading ? 'Refreshing...' : 'Refresh'}
  </ActionButton>
</div>

{#if loading}
  <div class="empty">Loading staged edits...</div>
{:else if pending.length === 0}
  <div class="empty">No staged edits are waiting for review.</div>
{:else}
  <section class="staged-grid" aria-label="Staged pages">
    {#each pending as item}
      <StagedPageCard {item} />
    {/each}
  </section>
{/if}

<style>
  .toolbar {
    margin: 1.25rem 0;
  }

  .staged-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(20rem, 1fr));
    gap: 0.85rem;
  }
</style>
