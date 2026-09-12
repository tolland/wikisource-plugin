<script lang="ts">
  import { formatDateTime } from '$lib/format';
  import type { PendingCommitPage } from '$lib/types';

  let {
    item,
    selected = false,
    selectable = false,
    disabled = false,
    ontoggle
  }: {
    item: PendingCommitPage;
    selected?: boolean;
    selectable?: boolean;
    disabled?: boolean;
    ontoggle?: (item: PendingCommitPage) => void;
  } = $props();

  const isConflicted = $derived(
    item.current_revid != null && item.current_revid !== item.base_revid
  );
  const isNewPage = $derived(item.current_revid == null);
</script>

<article class="staged-card" class:selected class:conflicted={isConflicted}>
  <div class="card-header">
    {#if selectable}
      <label class="select-box">
        <input
          type="checkbox"
          checked={selected}
          {disabled}
          onchange={() => ontoggle?.(item)}
          aria-label={`Select ${item.title}`}
        />
      </label>
    {/if}
    <div class="badges">
      {#if isConflicted}
        <span class="chip bad">Conflict</span>
      {:else if isNewPage}
        <span class="chip quiet">New page</span>
      {:else}
        <span class="chip go">Uncontroversial</span>
      {/if}
    </div>
  </div>

  <a class="title" href={`/commits/${item.page_pk}`}>{item.title}</a>

  <div class="meta">
    <span>{item.pending_count} save{item.pending_count === 1 ? '' : 's'}</span>
    <span>base r{item.base_revid}</span>
    {#if item.current_revid}
      <span>cache r{item.current_revid}</span>
    {/if}
    <span>{formatDateTime(item.latest_saved_at)}</span>
  </div>

  <div class="card-footer">
    <a class="review-link" href={`/commits/${item.page_pk}`}>Review diff &rarr;</a>
  </div>
</article>

<style>
  .staged-card {
    border: 1px solid rgba(72, 49, 31, 0.18);
    border-radius: 14px;
    background: rgba(255, 252, 240, 0.74);
    box-shadow: 0 14px 34px rgba(62, 44, 30, 0.08);
    color: inherit;
    display: flex;
    flex-direction: column;
    gap: 0.65rem;
    min-height: 9.5rem;
    padding: 1rem;
    transition: border-color 160ms ease, transform 160ms ease, background-color 160ms ease;
  }

  .staged-card:hover {
    border-color: rgba(156, 86, 50, 0.58);
    transform: translateY(-1px);
  }

  .staged-card.selected {
    border-color: #9c5632;
    background: rgba(255, 246, 230, 0.96);
    box-shadow: 0 0 0 2px rgba(156, 86, 50, 0.28), 0 14px 34px rgba(62, 44, 30, 0.1);
  }

  .staged-card.conflicted {
    border-color: rgba(178, 69, 47, 0.35);
  }

  .card-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.5rem;
  }

  .select-box {
    display: inline-flex;
    align-items: center;
    cursor: pointer;
  }

  .select-box input[type="checkbox"] {
    cursor: pointer;
    width: 1.15rem;
    height: 1.15rem;
    accent-color: #9c5632;
  }

  .badges {
    display: flex;
    gap: 0.4rem;
    margin-left: auto;
  }

  .chip {
    display: inline-flex;
    gap: 0.4rem;
    align-items: center;
    border: 1px solid rgba(72, 49, 31, 0.22);
    border-radius: 999px;
    padding: 0.2rem 0.55rem;
    font-family: "Avenir Next", "Gill Sans", sans-serif;
    font-size: 0.68rem;
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

  .title {
    font-size: 1.15rem;
    font-weight: 800;
    line-height: 1.25;
    overflow-wrap: anywhere;
    color: inherit;
    text-decoration: none;
  }

  .title:hover {
    color: #9c5632;
    text-decoration: underline;
  }

  .meta {
    margin-top: auto;
    font-weight: 700;
    letter-spacing: 0.04em;
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem 0.75rem;
    font-size: 0.72rem;
    color: #73583d;
  }

  .card-footer {
    display: flex;
    justify-content: flex-end;
    margin-top: 0.25rem;
    padding-top: 0.4rem;
    border-top: 1px solid rgba(72, 49, 31, 0.08);
  }

  .review-link {
    font-family: "Avenir Next", "Gill Sans", sans-serif;
    font-size: 0.75rem;
    font-weight: 700;
    color: #7d4428;
    text-decoration: none;
    letter-spacing: 0.04em;
    text-transform: uppercase;
  }

  .review-link:hover {
    color: #9c5632;
  }
</style>
