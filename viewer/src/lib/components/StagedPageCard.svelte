<script lang="ts">
  import { formatDateTime } from '$lib/format';
  import type { PendingCommitPage } from '$lib/types';

  let { item }: { item: PendingCommitPage } = $props();
</script>

<a class="staged-page" href={`/commits/${item.page_pk}`}>
  <span class="title">{item.title}</span>
  <span class="meta">
    <span>{item.pending_count} save{item.pending_count === 1 ? '' : 's'}</span>
    <span>base r{item.base_revid}</span>
    {#if item.current_revid}
      <span>cache r{item.current_revid}</span>
    {/if}
    <span>{formatDateTime(item.latest_saved_at)}</span>
  </span>
</a>

<style>
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
    margin-top: 0;
    font-weight: 700;
    letter-spacing: 0.04em;
  }
</style>
