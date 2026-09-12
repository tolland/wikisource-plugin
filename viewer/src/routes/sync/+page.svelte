<script lang="ts">
  import { onMount } from 'svelte';
  import { page as routePage } from '$app/state';
  import {
    fetchSyncAssets,
    listWorks,
    stageManyBatches,
    syncReport
  } from '$lib/api';
  import ActionButton from '$lib/components/ActionButton.svelte';
  import Notice from '$lib/components/Notice.svelte';
  import PageHeading from '$lib/components/PageHeading.svelte';
  import SelectField from '$lib/components/SelectField.svelte';
  import SyncPageCard from '$lib/components/SyncPageCard.svelte';
  import TextField from '$lib/components/TextField.svelte';
  import type {
    SyncPage,
    SyncReport,
    SyncRequest,
    SyncVerdict,
    WorkSummary
  } from '$lib/types';

  /**
   * `sync --from Index:X [--to Index:Y]`, with somewhere to look at the answer.
   *
   * Directional, and the direction is the first control on the page: the same
   * two wikis and the same work produce opposite reports depending on which
   * way round they are read, and a page that hid that would be answering a
   * different question from the one asked.
   *
   * Running the report is read-only. Staging selected results only freezes
   * local batches; pushing remains a separate, explicit action.
   */

  let works: WorkSummary[] = $state([]);
  let selectedWorkPk: number | null = $state(null);
  let reversed = $state(false);
  let show: 'actionable' | 'all' | 'problems' = $state('actionable');

  let report: SyncReport | null = $state(null);
  let loading = $state(true);
  let running = $state(false);
  let fetching = $state(false);
  let staging = $state(false);
  let selectedPages: number[] = $state([]);
  let expandedPages: number[] = $state([]);
  let batchLabel = $state('');
  let error = $state('');
  let message = $state('');

  const selectedWork = $derived(
    works.find((work) => work.pk === selectedWorkPk) ?? null
  );
  const selectedRequest = $derived.by((): SyncRequest | null => {
    if (selectedWork === null) return null;
    return reversed
      ? {
          source_label: selectedWork.remote_site,
          target_label: selectedWork.local_site,
          index_title: selectedWork.remote_title,
          target_index_title: selectedWork.local_title
        }
      : {
          source_label: selectedWork.local_site,
          target_label: selectedWork.remote_site,
          index_title: selectedWork.local_title,
          target_index_title: selectedWork.remote_title
        };
  });

  /** Label, tone, and what the verdict means for whoever is reading. */
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

  const visible = $derived.by((): SyncPage[] => {
    if (report === null) return [];
    if (show === 'actionable') return report.pages.filter((row) => row.actionable);
    if (show === 'problems') {
      return report.pages.filter(
        (row) => !row.actionable && row.verdict !== 'in_sync'
      );
    }
    return report.pages;
  });
  const selectableVisible = $derived(
    visible.filter((row) => row.actionable && row.page_number != null)
  );
  const allVisibleSelected = $derived(
    selectableVisible.length > 0 &&
      selectableVisible.every((row) => selectedPages.includes(row.page_number as number))
  );

  async function load(): Promise<void> {
    loading = true;
    error = '';
    try {
      works = (await listWorks()).works;
      const requestedWork = Number(routePage.url.searchParams.get('work'));
      const requestedIndex = routePage.url.searchParams.get('index');
      selectedWorkPk =
        works.find((work) => work.pk === requestedWork)?.pk ??
        works.find(
          (work) =>
            work.local_title === requestedIndex || work.remote_title === requestedIndex
        )?.pk ??
        works[0]?.pk ??
        null;
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to load tracked works';
    } finally {
      loading = false;
    }
  }

  async function run(): Promise<void> {
    if (selectedRequest === null) return;
    running = true;
    error = '';
    try {
      report = await syncReport(selectedRequest);
      selectedPages = [];
      expandedPages = [];
    } catch (err) {
      error = err instanceof Error ? err.message : 'The report failed';
      report = null;
    } finally {
      running = false;
    }
  }

  async function fetchAssets(): Promise<void> {
    // The answer to "the scan check could not run" and "is the work even
    // there": both are questions nobody has asked the wiki yet. Queued only --
    // draining stays the separate, throttled step.
    if (selectedRequest === null) return;
    fetching = true;
    error = '';
    message = '';
    try {
      const result = await fetchSyncAssets(selectedRequest);
      message = result.queued.length
        ? `Queued ${result.queued.map((item) => `${item.title} on ${item.label}`).join(', ')}. ${result.note}`
        : 'Nothing to fetch: both assets are already held.';
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to queue the assets';
    } finally {
      fetching = false;
    }
  }

  async function stageSelected(): Promise<void> {
    if (selectedRequest === null || selectedPages.length === 0) return;
    staging = true;
    error = '';
    message = '';
    try {
      const result = await stageManyBatches({
        ...selectedRequest,
        page_numbers: [...selectedPages].sort((a, b) => a - b),
        label: batchLabel || null
      });
      message = `Staged ${result.batches.length} batch(es). Open Batches to review or push them individually.`;
      selectedPages = [];
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to stage the selected batches';
    } finally {
      staging = false;
    }
  }

  function togglePage(pageNumber: number): void {
    selectedPages = selectedPages.includes(pageNumber)
      ? selectedPages.filter((value) => value !== pageNumber)
      : [...selectedPages, pageNumber];
  }

  function toggleVisible(): void {
    const visibleNumbers = selectableVisible.map((row) => row.page_number as number);
    selectedPages = allVisibleSelected
      ? selectedPages.filter((value) => !visibleNumbers.includes(value))
      : [...new Set([...selectedPages, ...visibleNumbers])];
  }

  function toggleExpandedPage(pageNumber: number, isExpanded: boolean): void {
    if (isExpanded) {
      if (!expandedPages.includes(pageNumber)) {
        expandedPages = [...expandedPages, pageNumber];
      }
    } else {
      expandedPages = expandedPages.filter((num) => num !== pageNumber);
    }
  }

  function expandAllVisible(): void {
    const visibleNumbers = visible
      .map((row) => row.page_number)
      .filter((num): num is number => num != null);
    expandedPages = [...new Set([...expandedPages, ...visibleNumbers])];
  }

  function collapseAllVisible(): void {
    const visibleNumbers = new Set(
      visible.map((row) => row.page_number).filter((num): num is number => num != null)
    );
    expandedPages = expandedPages.filter((num) => !visibleNumbers.has(num));
  }

  function swap(): void {
    reversed = !reversed;
    report = null;
    selectedPages = [];
    expandedPages = [];
    message = '';
  }

  function chooseWork(): void {
    reversed = false;
    report = null;
    selectedPages = [];
    expandedPages = [];
    message = '';
  }

  onMount(load);
</script>

<PageHeading eyebrow="Dry run" title="Sync report">
  <p class="description">
    What copying a work from one wiki to the other would change &mdash; page by page,
    with the scan check first. Running the report writes nothing; staging only
    creates local batches and never writes to either wiki.
  </p>
  <p class="description">
    Pushing back to a public wiki one page at a time, without waiting on the
    rest of the work? Use <a href="/sync-page">Promote a page</a> instead. See
    <a href="/sync/batches">every staged run</a> for what is pending or errored.
  </p>
</PageHeading>

{#if error}
  <Notice>{error}</Notice>
{/if}
{#if message}
  <Notice kind="success">{message}</Notice>
{/if}

{#if loading}
  <p class="state">Loading...</p>
{:else}
  {#if works.length === 0}
    <p class="state">
      No Index links exist yet. <a href="/links">Link the two Index pages</a> before
      running a work-level sync report.
    </p>
  {:else}
    <section class="work-picker" aria-label="Tracked work">
      <SelectField label="Index link" bind:value={selectedWorkPk} onchange={chooseWork}>
        {#each works as work}
          <option value={work.pk}>
            #{work.pk} · {work.local_title} ↔ {work.remote_title}
          </option>
        {/each}
      </SelectField>
      {#if selectedWork}
        <a class="drill" href={`/links/${selectedWork.pk}`}>Open tracked work &rarr;</a>
      {/if}
    </section>

    {#if selectedRequest}
      <section class="controls" aria-label="Direction">
        <div class="side">
          <p class="eyebrow">From (source) · {selectedRequest.source_label}</p>
          <strong>{selectedRequest.index_title}</strong>
        </div>

        <button type="button" class="swap" onclick={swap} title="Reverse the direction">
          &rarr;&nbsp;&larr;
        </button>

        <div class="side">
          <p class="eyebrow">To (target) · {selectedRequest.target_label}</p>
          <strong>{selectedRequest.target_index_title}</strong>
        </div>
      </section>

      <div class="run-row">
        <ActionButton disabled={running} onclick={run}>
          {running ? 'Comparing...' : 'Run the report'}
        </ActionButton>
        <span class="hint">
          Direction belongs to this report, not to Index link #{selectedWorkPk}. Reverse it
          to compare or stage the same tracked work the other way.
        </span>
      </div>
    {/if}
  {/if}
{/if}

{#if report}
  <section class="sides" aria-label="Both sides">
    {#each [report.source, report.target] as side, i}
      <div class="side-card" class:missing={!side.exists}>
        <p class="eyebrow">{i === 0 ? 'Source' : 'Target'} &middot; {side.site}</p>
        <strong>{side.index_title}</strong>
        {#if side.exists}
          <small>
            {side.cached_pages} page(s) cached
            {#if side.placeholder_pages}
              &middot; {side.placeholder_pages} untranscribed
            {/if}
          </small>
        {:else}
          <small class="absent">does not exist &mdash; the index itself would be created</small>
        {/if}
      </div>
    {/each}
  </section>

  <section class="assets" aria-label="Assets">
    <p class="eyebrow">Assets</p>
    <p class="lead">
      A work is not only its pages. The index and the scan behind it are the two
      things a sync has to account for first.
    </p>
    <ul>
      {#each report.assets as asset}
        <li>
          <span class="chip {VERDICTS[asset.verdict]?.tone ?? 'warn'}">{asset.kind}</span>
          <span class="asset-body">
            <strong>{asset.source_title}</strong>
            {#if asset.target_title !== asset.source_title}
              <em>&rarr; {asset.target_title}</em>
            {/if}
            <small>{asset.detail}</small>
            <small class="held">
              held: {asset.source_cached ? report.source.site : '—'} /
              {asset.target_cached ? report.target.site : '—'}
            </small>
          </span>
        </li>
      {/each}
    </ul>

    {#if report.fetch_plan.length}
      <div class="plan">
        <p>
          {report.fetch_plan.length} fetch(es) would settle what this report cannot
          answer:
        </p>
        <ul class="plan-list">
          {#each report.fetch_plan as item}
            <li><code>{item.title}</code> on {item.label} &mdash; {item.reason}</li>
          {/each}
        </ul>
        <ActionButton disabled={fetching} onclick={fetchAssets}>
          {fetching ? 'Queueing...' : 'Fetch the index and scan'}
        </ActionButton>
        <small>
          Queued only &mdash; run a drain from the Fetch page, then re-run this report.
          A scan hosted on Commons is followed automatically.
        </small>
      </div>
    {/if}
  </section>

  <section class="scan {report.scan.status}" aria-label="Scan check">
    <p class="eyebrow">Scan check</p>
    <p>{report.scan.detail}</p>
    {#if report.scan.source_sha1 || report.scan.target_sha1}
      <dl>
        <div>
          <dt>{report.source.site}</dt>
          <dd>{report.scan.source_file ?? '-'} {report.scan.source_sha1?.slice(0, 12) ?? ''}</dd>
        </div>
        <div>
          <dt>{report.target.site}</dt>
          <dd>{report.scan.target_file ?? '-'} {report.scan.target_sha1?.slice(0, 12) ?? ''}</dd>
        </div>
      </dl>
    {/if}
  </section>

  {#each report.blockers as blocker}
    <Notice>{blocker}</Notice>
  {/each}
  {#each report.advisories as advisory}
    <div class="advisory">
      <p>{advisory}</p>
      {#if report.work_pk}
        <a class="drill" href={`/links/${report.work_pk}`}>Open the work to propose &rarr;</a>
      {/if}
    </div>
  {/each}

  <section class="summary" aria-label="Verdicts">
    {#each Object.entries(report.counts) as [verdict, count]}
      <span class="chip {VERDICTS[verdict as SyncVerdict]?.tone ?? 'warn'}">
        {VERDICTS[verdict as SyncVerdict]?.label ?? verdict}
        <strong>{count}</strong>
      </span>
    {/each}
    <span class="total">
      {report.actionable} page(s) a push would write
      {#if report.linkable}
        &middot; {report.linkable} more once linked
      {/if}
    </span>
  </section>

  {#if report.actionable > 0}
    <section class="stage" aria-label="Stage selected pages">
      <h2>Stage selected pages</h2>
      <p>
        Select one or more writable rows below. Each page becomes its own batch, with
        source revisions replayed in order onto that target page. This report is for
        choosing pages; each batch shows the exact revision-by-revision diff before
        anything is pushed.
      </p>
      <div class="stage-actions">
        <TextField label="Batch label prefix (optional)" bind:value={batchLabel} />
        <ActionButton disabled={staging || selectedPages.length === 0} onclick={stageSelected}>
          {staging ? 'Staging...' : `Stage ${selectedPages.length} selected`}
        </ActionButton>
        <a class="drill" href="/sync/batches">Open Batches &rarr;</a>
      </div>
    </section>
  {/if}

  <div class="filter-bar">
    <div class="filter-left">
      <SelectField label="Show" bind:value={show}>
        <option value="actionable">what would be written ({report.actionable})</option>
        <option value="problems">what needs a person</option>
        <option value="all">every page ({report.pages.length})</option>
      </SelectField>
    </div>

    <div class="filter-actions">
      {#if selectableVisible.length > 0}
        <ActionButton
          variant="ghost"
          onclick={toggleVisible}
          disabled={staging}
        >
          {allVisibleSelected ? 'Deselect visible' : 'Select all visible'}
        </ActionButton>
      {/if}

      {#if visible.length > 0}
        <ActionButton
          variant="ghost"
          onclick={expandAllVisible}
        >
          Expand all
        </ActionButton>
        <ActionButton
          variant="ghost"
          onclick={collapseAllVisible}
        >
          Collapse all
        </ActionButton>
      {/if}

      {#if report.work_pk}
        <a class="drill link-btn" href={`/links/${report.work_pk}`}>Open the tracked work &rarr;</a>
      {/if}
    </div>
  </div>

  {#if visible.length === 0}
    <p class="state">Nothing in this view.</p>
  {:else}
    <section class="pages-list" aria-label="Sync report pages">
      {#each visible as row (row.page_number ?? row.source_title ?? row.target_title)}
        <SyncPageCard
          {row}
          request={selectedRequest}
          selectable={true}
          selected={row.page_number != null && selectedPages.includes(row.page_number)}
          disabled={staging}
          expanded={row.page_number != null && expandedPages.includes(row.page_number)}
          ontoggle={() => row.page_number != null && togglePage(row.page_number)}
          onexpand={(exp) => row.page_number != null && toggleExpandedPage(row.page_number, exp)}
        />
      {/each}
    </section>
  {/if}

  <p class="footnote">
    Nothing on this page writes to {report.target.site}. Staging freezes selected
    rows as local batches; pushing happens from each batch. This report uses tracked
    Index link #{report.work_pk}; reversing it does not change that correspondence.
  </p>
{/if}

<style>
  .description a {
    color: #9c5632;
  }

  .description,
  .state,
  .hint {
    color: #73583d;
  }

  .state a {
    color: #9c5632;
  }

  .work-picker {
    display: flex;
    flex-wrap: wrap;
    gap: 0.75rem 1rem;
    align-items: end;
    margin-top: 1.5rem;
  }

  .controls {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
    gap: 1rem;
    align-items: center;
    margin: 1.5rem 0 1rem;
  }

  .side {
    display: grid;
    gap: 0.75rem;
    border: 1px solid rgba(72, 49, 31, 0.18);
    border-radius: 20px;
    background: rgba(255, 248, 230, 0.72);
    padding: 1rem;
  }

  .swap {
    cursor: pointer;
    border: 1px solid rgba(72, 49, 31, 0.24);
    border-radius: 999px;
    background: rgba(255, 252, 240, 0.9);
    color: #9c5632;
    font-size: 0.9rem;
    padding: 0.7rem 0.8rem;
  }

  .run-row {
    display: flex;
    flex-wrap: wrap;
    gap: 0.75rem 1rem;
    align-items: center;
    margin-bottom: 1.75rem;
  }

  .hint {
    font-size: 0.86rem;
  }

  .sides {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(18rem, 1fr));
    gap: 1rem;
  }

  .side-card {
    border: 1px solid rgba(72, 49, 31, 0.18);
    border-radius: 18px;
    background: rgba(255, 252, 240, 0.64);
    padding: 0.9rem 1.1rem;
  }

  .side-card.missing {
    border-style: dashed;
    border-color: rgba(176, 120, 20, 0.5);
  }

  .side-card strong,
  .side-card small {
    display: block;
    overflow-wrap: anywhere;
  }

  .side-card small {
    margin-top: 0.3rem;
    color: #73583d;
    font-size: 0.8rem;
  }

  .absent {
    color: #7d5510;
  }

  .eyebrow {
    margin: 0 0 0.3rem;
    color: #73583d;
    font-family: "Avenir Next", "Gill Sans", sans-serif;
    font-size: 0.7rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }

  .scan {
    border: 1px solid;
    border-radius: 18px;
    margin: 1rem 0;
    padding: 0.9rem 1.1rem;
  }

  .scan p {
    margin: 0;
  }

  .scan.ok {
    border-color: rgba(40, 107, 76, 0.4);
    background: rgba(229, 246, 235, 0.6);
  }

  .scan.unverifiable {
    border-color: rgba(176, 120, 20, 0.45);
    background: rgba(255, 244, 219, 0.7);
  }

  .scan.mismatch {
    border-color: rgba(178, 69, 47, 0.5);
    background: rgba(255, 238, 233, 0.72);
  }

  .scan dl {
    display: grid;
    gap: 0.2rem;
    margin: 0.6rem 0 0;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 0.78rem;
  }

  .scan dl div {
    display: flex;
    gap: 0.6rem;
  }

  .scan dt {
    min-width: 9rem;
    color: #73583d;
  }

  .scan dd {
    margin: 0;
    overflow-wrap: anywhere;
  }

  .assets {
    border: 1px solid rgba(72, 49, 31, 0.18);
    border-radius: 18px;
    margin: 1rem 0;
    padding: 0.9rem 1.1rem;
  }

  .assets .lead {
    margin: 0 0 0.7rem;
    color: #73583d;
    font-size: 0.86rem;
  }

  .assets ul {
    display: grid;
    gap: 0.6rem;
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .assets li {
    display: grid;
    grid-template-columns: auto minmax(0, 1fr);
    gap: 0.7rem;
    align-items: start;
  }

  .asset-body strong,
  .asset-body em,
  .asset-body small {
    display: block;
    overflow-wrap: anywhere;
  }

  .asset-body em {
    color: #73583d;
    font-style: normal;
    font-size: 0.84rem;
  }

  .asset-body small {
    margin-top: 0.2rem;
    color: #73583d;
    font-size: 0.78rem;
  }

  .asset-body .held {
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  }

  .plan {
    border-top: 1px solid rgba(72, 49, 31, 0.14);
    margin-top: 0.9rem;
    padding-top: 0.9rem;
  }

  .plan p {
    margin: 0 0 0.4rem;
    color: #73583d;
    font-size: 0.86rem;
  }

  .plan-list {
    display: grid;
    gap: 0.25rem;
    margin: 0 0 0.75rem;
    color: #73583d;
    font-size: 0.82rem;
  }

  .plan small {
    display: block;
    margin-top: 0.6rem;
    color: #8a6a45;
    font-size: 0.78rem;
  }

  .summary {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    align-items: center;
    margin: 1rem 0;
  }

  .total {
    color: #73583d;
    font-size: 0.86rem;
  }

  .chip {
    display: inline-flex;
    gap: 0.4rem;
    align-items: baseline;
    border: 1px solid;
    border-radius: 999px;
    font-family: "Avenir Next", "Gill Sans", sans-serif;
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.04em;
    padding: 0.28rem 0.68rem;
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

  .advisory {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem 1rem;
    align-items: center;
    justify-content: space-between;
    border: 1px solid rgba(176, 120, 20, 0.45);
    border-radius: 16px;
    background: rgba(255, 244, 219, 0.7);
    margin-bottom: 1rem;
    padding: 0.9rem 1.1rem;
    color: #7d5510;
  }

  .advisory p {
    margin: 0;
    font-size: 0.88rem;
  }

  .stage {
    border: 1px solid rgba(40, 107, 76, 0.34);
    border-radius: 20px;
    background: rgba(229, 246, 235, 0.5);
    margin-bottom: 1.5rem;
    padding: 1.1rem 1.2rem;
  }

  .stage h2 {
    margin: 0 0 0.4rem;
    font-size: 1rem;
  }

  .stage p {
    margin: 0 0 0.8rem;
    max-width: 50rem;
    color: #24543f;
    font-size: 0.88rem;
  }

  .stage-actions {
    display: flex;
    flex-wrap: wrap;
    gap: 0.75rem 1rem;
    align-items: end;
  }

  .filter-bar {
    display: flex;
    flex-wrap: wrap;
    gap: 1rem;
    align-items: end;
    justify-content: space-between;
    margin-bottom: 1.2rem;
    padding-bottom: 0.5rem;
    border-bottom: 1px solid rgba(72, 49, 31, 0.12);
  }

  .filter-left {
    min-width: 14rem;
  }

  .filter-actions {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.6rem 0.85rem;
  }

  .link-btn {
    margin-left: 0.5rem;
  }

  .pages-list {
    display: flex;
    flex-direction: column;
    margin-top: 0.5rem;
  }

  .drill {
    color: #9c5632;
    font-family: "Avenir Next", "Gill Sans", sans-serif;
    font-size: 0.76rem;
    font-weight: 700;
    text-decoration: none;
    text-transform: uppercase;
    white-space: nowrap;
  }

  .drill:hover {
    text-decoration: underline;
  }

  .footnote {
    margin-top: 1.5rem;
    color: #73583d;
    font-size: 0.84rem;
  }

  @media (max-width: 860px) {
    .controls {
      grid-template-columns: 1fr;
    }
  }
</style>
