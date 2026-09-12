<script lang="ts">
  import { previewBatch } from '$lib/api';
  import DiffView from '$lib/components/DiffView.svelte';
  import { buildLineDiff } from '$lib/diff';
  import type { Batch, PromotionRow, PromotionStatus, SyncPage, SyncRequest, SyncVerdict } from '$lib/types';

  let {
    row,
    request = null,
    selected = false,
    selectable = false,
    disabled = false,
    expanded = false,
    ontoggle,
    onexpand
  }: {
    row: SyncPage;
    request?: SyncRequest | null;
    selected?: boolean;
    selectable?: boolean;
    disabled?: boolean;
    expanded?: boolean;
    ontoggle?: (row: SyncPage) => void;
    onexpand?: (expanded: boolean) => void;
  } = $props();

  let isExpanded = $state(false);
  let previewBatchData: Batch | null = $state(null);
  let loadingPreview = $state(false);
  let previewError = $state('');

  // Sync isExpanded when parent prop changes
  $effect(() => {
    isExpanded = expanded;
  });

  // When expanding an actionable row, automatically fetch preview if not already loaded
  $effect(() => {
    if (isExpanded && row.actionable && row.page_number != null && request != null && !previewBatchData && !loadingPreview && !previewError) {
      void fetchPreview();
    }
  });

  const VERDICTS: Record<SyncVerdict, { label: string; tone: string; note: string }> = {
    create: {
      label: 'create',
      tone: 'go',
      note: 'The target has no such page, or only an untranscribed placeholder.'
    },
    push: {
      label: 'push',
      tone: 'go',
      note: 'Source revisions sit above the anchor; the target is still at it.'
    },
    behind: {
      label: 'behind',
      tone: 'in',
      note: 'Linked, and the target has moved on. Real work, in the other direction.'
    },
    in_sync: { label: 'in sync', tone: 'quiet', note: 'The anchor names both heads.' },
    diverged: {
      label: 'diverged',
      tone: 'bad',
      note: 'Both sides moved after their last agreement. Needs a person.'
    },
    unlinked: {
      label: 'unlinked',
      tone: 'warn',
      note: 'No asserted link, so there is no base to write onto. Not writable today.'
    },
    source_missing: {
      label: 'target only',
      tone: 'in',
      note: 'A page the target has and the source does not.'
    },
    unknown: {
      label: 'unknown',
      tone: 'warn',
      note: 'A side has not been fetched. A fetch, not a verdict.'
    }
  };

  const STATUSES: Record<PromotionStatus, { label: string; tone: string }> = {
    staged: { label: 'staged', tone: 'quiet' },
    pushed: { label: 'pushed', tone: 'go' },
    conflict: { label: 'conflict', tone: 'warn' },
    error: { label: 'error', tone: 'bad' },
    skipped: { label: 'skipped', tone: 'quiet' }
  };

  const diffs = $derived.by(() => {
    const result = new Map<number, ReturnType<typeof buildLineDiff>>();
    for (const p of previewBatchData?.promotions ?? []) {
      if (p.submitted_body != null) {
        result.set(p.pk, buildLineDiff(p.base_body ?? '', p.submitted_body));
      }
    }
    return result;
  });

  async function fetchPreview(): Promise<void> {
    if (!request || row.page_number == null) return;
    loadingPreview = true;
    previewError = '';
    try {
      previewBatchData = await previewBatch({
        ...request,
        page_number: row.page_number
      });
    } catch (err) {
      previewError = err instanceof Error ? err.message : 'Failed to calculate diff preview';
    } finally {
      loadingPreview = false;
    }
  }

  function toggleExpand(): void {
    const next = !isExpanded;
    isExpanded = next;
    onexpand?.(next);
  }
</script>

<article
  class="sync-card"
  class:selected
  class:actionable={row.actionable}
  class:expanded={isExpanded}
>
  <header class="card-summary">
    <div class="header-left">
      {#if selectable && row.actionable && row.page_number != null}
        <label class="select-box">
          <input
            type="checkbox"
            checked={selected}
            {disabled}
            onchange={() => ontoggle?.(row)}
            aria-label={`Select page ${row.page_number}`}
          />
        </label>
      {/if}

      <div class="page-num">
        <strong>#{row.page_number ?? '?'}</strong>
      </div>

      <span class="chip {VERDICTS[row.verdict]?.tone ?? 'warn'}">
        {VERDICTS[row.verdict]?.label ?? row.verdict}
      </span>

      <div class="title-group">
        <span class="title">{row.source_title ?? row.target_title}</span>
        {#if row.target_title && row.source_title && row.target_title !== row.source_title}
          <span class="target-title">&rarr; {row.target_title}</span>
        {/if}
        {#if row.linkable}
          <span class="chip warn linkable-badge">linkable</span>
        {/if}
      </div>
    </div>

    <div class="header-right">
      <div class="revs">
        <span>r{row.source_revid ?? '-'} &rarr; r{row.target_revid ?? 'none'}</span>
        {#if row.anchor_source_revid}
          <small class="anchor-note">
            anchor {row.anchor_source_revid} &harr; {row.anchor_target_revid}
          </small>
        {/if}
      </div>

      {#if row.pair_pk}
        <a class="drill" href={`/links/pairs/${row.pair_pk}`}>Revisions</a>
      {/if}

      <button
        type="button"
        class="toggle-btn"
        onclick={toggleExpand}
        aria-expanded={isExpanded}
        aria-label={isExpanded ? 'Collapse page details' : 'Expand page details'}
      >
        <span class="toggle-label">{isExpanded ? 'Hide diff' : 'Show diff'}</span>
        <span class="toggle-icon">{isExpanded ? '▲' : '▼'}</span>
      </button>
    </div>
  </header>

  {#if isExpanded}
    <div class="card-body">
      {#if row.actionable}
        {#if loadingPreview}
          <div class="loading-box">
            <span class="spinner"></span>
            Calculating staged diff preview...
          </div>
        {:else if previewError}
          <div class="error-box">
            <p>{previewError}</p>
            <button type="button" class="retry-btn" onclick={fetchPreview}>Retry</button>
          </div>
        {:else if previewBatchData && previewBatchData.promotions.length > 0}
          <div class="promotions-wrapper">
            <p class="diff-intro">
              Preview of {previewBatchData.promotions.length} revision{previewBatchData.promotions.length === 1 ? '' : 's'} that will be staged for this page.
              Each revision shows the changes replayed in sequence.
            </p>

            {#each previewBatchData.promotions as promotion, index (promotion.pk)}
              {@const diff = diffs.get(promotion.pk)}
              <div class="promotion-box">
                <header class="promotion-header">
                  <div>
                    <p class="revision-title">
                      Revision {index + 1} of {previewBatchData.promotions.length}
                      <span class="source-revid">source r{promotion.source_revid}</span>
                    </p>
                    <p class="revision-meta">
                      {promotion.intent}
                      &middot; base {promotion.base_revid ?? (promotion.predecessor_promotion_pk ? 'previous result' : 'new page')}
                      {#if promotion.result_revid != null}&middot; result r{promotion.result_revid}{/if}
                      &middot; {promotion.body_length.toLocaleString()} characters
                    </p>
                    <p class="comment">Edit summary: {promotion.comment || '(empty)'}</p>
                  </div>
                  <div class="promotion-badges">
                    <span class="chip {STATUSES[promotion.status]?.tone ?? 'quiet'}">
                      {STATUSES[promotion.status]?.label ?? promotion.status}
                    </span>
                  </div>
                </header>

                {#if promotion.error_message}
                  <p class="why">{promotion.error_message}</p>
                {/if}
                {#if promotion.submitted_body != null && promotion.base_body == null && promotion.intent === 'update'}
                  <p class="why">The cached target anchor body is unavailable; the whole submitted body is shown as added.</p>
                {/if}
                {#if promotion.submitted_body == null}
                  <p class="why">Diff body is unavailable.</p>
                {/if}

                {#if diff}
                  <div class="diff-summary">
                    <span class="added">+{diff.added.toLocaleString()}</span>
                    <span class="removed">-{diff.removed.toLocaleString()}</span>
                    <span>{diff.unchanged.toLocaleString()} unchanged lines</span>
                  </div>
                  <DiffView {diff} />
                {/if}
              </div>
            {/each}
          </div>
        {:else if previewBatchData && previewBatchData.promotions.length === 0}
          <div class="empty-preview">
            No source revisions found after the current anchor to stage.
          </div>
        {/if}
      {:else}
        <div class="non-actionable-box">
          <p class="verdict-note">
            <strong>{VERDICTS[row.verdict]?.label ?? row.verdict}:</strong>
            {row.detail ?? VERDICTS[row.verdict]?.note ?? 'No staging available for this page.'}
          </p>
          {#if row.linkable}
            <p class="linkable-note">
              This unlinked page has matching content. Open the tracked work to confirm the proposal.
            </p>
          {/if}
          {#if row.pair_pk}
            <p>
              <a class="drill" href={`/links/pairs/${row.pair_pk}`}>Open revision ladder comparison &rarr;</a>
            </p>
          {/if}
        </div>
      {/if}
    </div>
  {/if}
</article>

<style>
  .sync-card {
    border: 1px solid rgba(72, 49, 31, 0.16);
    border-radius: 14px;
    background: rgba(255, 252, 240, 0.72);
    box-shadow: 0 4px 14px rgba(62, 44, 30, 0.04);
    margin-bottom: 0.75rem;
    transition: border-color 160ms ease, box-shadow 160ms ease, background 160ms ease;
    overflow: hidden;
  }

  .sync-card:hover {
    border-color: rgba(156, 86, 50, 0.4);
  }

  .sync-card.selected {
    border-color: #9c5632;
    background: rgba(255, 248, 235, 0.94);
    box-shadow: 0 0 0 2px rgba(156, 86, 50, 0.2), 0 8px 20px rgba(62, 44, 30, 0.08);
  }

  .sync-card.expanded {
    border-color: rgba(156, 86, 50, 0.5);
    background: rgba(255, 253, 245, 0.96);
  }

  .card-summary {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: 0.75rem 1rem;
    padding: 0.75rem 1rem;
  }

  .header-left {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.65rem 0.85rem;
    min-width: 0;
    flex: 1 1 20rem;
  }

  .select-box {
    display: inline-flex;
    align-items: center;
    cursor: pointer;
  }

  .select-box input[type="checkbox"] {
    width: 1.1rem;
    height: 1.1rem;
    accent-color: #286b4c;
    cursor: pointer;
  }

  .page-num {
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 0.88rem;
    color: #73583d;
    min-width: 2.2rem;
  }

  .title-group {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 0.4rem 0.6rem;
    min-width: 0;
  }

  .title {
    font-weight: 700;
    font-size: 0.95rem;
    overflow-wrap: anywhere;
  }

  .target-title {
    color: #73583d;
    font-size: 0.85rem;
    overflow-wrap: anywhere;
  }

  .linkable-badge {
    font-size: 0.65rem;
    padding: 0.15rem 0.45rem;
  }

  .header-right {
    display: flex;
    align-items: center;
    gap: 0.75rem 1rem;
    margin-left: auto;
  }

  .revs {
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 0.78rem;
    color: #73583d;
    text-align: right;
    white-space: nowrap;
  }

  .anchor-note {
    display: block;
    color: #8a6a45;
    font-size: 0.72rem;
  }

  .drill {
    color: #9c5632;
    font-family: "Avenir Next", "Gill Sans", sans-serif;
    font-size: 0.74rem;
    font-weight: 700;
    text-decoration: none;
    text-transform: uppercase;
    white-space: nowrap;
  }

  .drill:hover {
    text-decoration: underline;
  }

  .toggle-btn {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    border: 1px solid rgba(72, 49, 31, 0.2);
    border-radius: 8px;
    background: rgba(255, 252, 240, 0.9);
    color: #73583d;
    cursor: pointer;
    font-family: "Avenir Next", "Gill Sans", sans-serif;
    font-size: 0.74rem;
    font-weight: 700;
    letter-spacing: 0.03em;
    padding: 0.35rem 0.65rem;
    text-transform: uppercase;
    transition: background 140ms ease, border-color 140ms ease, color 140ms ease;
  }

  .toggle-btn:hover {
    background: rgba(255, 244, 219, 0.95);
    border-color: #9c5632;
    color: #9c5632;
  }

  .toggle-icon {
    font-size: 0.65rem;
  }

  .card-body {
    border-top: 1px solid rgba(72, 49, 31, 0.1);
    padding: 1rem;
    background: rgba(255, 250, 240, 0.5);
  }

  .loading-box {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    color: #73583d;
    font-size: 0.86rem;
    padding: 0.5rem 0;
  }

  .spinner {
    width: 1rem;
    height: 1rem;
    border: 2px solid rgba(156, 86, 50, 0.2);
    border-top-color: #9c5632;
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }

  @keyframes spin {
    to {
      transform: rotate(360deg);
    }
  }

  .error-box {
    color: #7f2f22;
    background: rgba(255, 238, 233, 0.7);
    border: 1px solid rgba(178, 69, 47, 0.3);
    border-radius: 8px;
    padding: 0.75rem 1rem;
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 1rem;
  }

  .error-box p {
    margin: 0;
    font-size: 0.84rem;
  }

  .retry-btn {
    border: 1px solid rgba(178, 69, 47, 0.4);
    border-radius: 6px;
    background: white;
    color: #7f2f22;
    cursor: pointer;
    font-weight: 700;
    font-size: 0.74rem;
    padding: 0.25rem 0.6rem;
    text-transform: uppercase;
  }

  .promotions-wrapper {
    display: grid;
    gap: 1rem;
  }

  .diff-intro {
    margin: 0 0 0.25rem;
    color: #73583d;
    font-size: 0.84rem;
  }

  .promotion-box {
    border: 1px solid rgba(72, 49, 31, 0.16);
    border-radius: 12px;
    background: rgba(255, 252, 240, 0.8);
    padding: 0.85rem 1rem;
  }

  .promotion-header {
    display: flex;
    justify-content: space-between;
    gap: 1rem;
  }

  .revision-title {
    margin: 0;
    font-family: "Avenir Next", "Gill Sans", sans-serif;
    font-weight: 700;
    font-size: 0.9rem;
  }

  .source-revid {
    margin-left: 0.5rem;
    color: #9c5632;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 0.8rem;
  }

  .revision-meta,
  .comment {
    margin: 0.2rem 0 0;
    color: #73583d;
    font-size: 0.78rem;
  }

  .comment {
    overflow-wrap: anywhere;
  }

  .why {
    margin: 0.6rem 0;
    color: #7d5510;
    font-size: 0.8rem;
  }

  .diff-summary {
    display: flex;
    gap: 0.75rem;
    margin: 0.6rem 0;
    color: #73583d;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 0.76rem;
  }

  .diff-summary .added {
    color: #286b4c;
    font-weight: 700;
  }

  .diff-summary .removed {
    color: #a13c22;
    font-weight: 700;
  }

  .empty-preview,
  .non-actionable-box {
    color: #73583d;
    font-size: 0.84rem;
    line-height: 1.4;
  }

  .non-actionable-box p {
    margin: 0.3rem 0;
  }

  .chip {
    display: inline-flex;
    gap: 0.4rem;
    align-items: baseline;
    border: 1px solid;
    border-radius: 999px;
    font-family: "Avenir Next", "Gill Sans", sans-serif;
    font-size: 0.7rem;
    font-weight: 700;
    letter-spacing: 0.04em;
    padding: 0.2rem 0.6rem;
    text-transform: uppercase;
    white-space: nowrap;
  }

  .chip.go {
    border-color: rgba(40, 107, 76, 0.42);
    background: rgba(229, 246, 235, 0.72);
    color: #24543f;
  }

  .chip.in {
    border-color: rgba(61, 95, 146, 0.42);
    background: rgba(232, 240, 252, 0.72);
    color: #2f4a74;
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
</style>
