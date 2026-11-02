<script lang="ts">
  import { onMount } from 'svelte';
  import { listSites, listPageTrees, createPageTree, reportPageTree, fetchPageTree, selectPageTree } from '$lib/api';
  import type { Site, PageTree, PageTreeReport } from '$lib/types';
  import SiteSelect from '$lib/components/SiteSelect.svelte';
  import TextField from '$lib/components/TextField.svelte';
  import ActionButton from '$lib/components/ActionButton.svelte';
  import Notice from '$lib/components/Notice.svelte';
  import PageHeading from '$lib/components/PageHeading.svelte';

  let sites: Site[] = $state([]);
  let trees: PageTree[] = $state([]);
  let sourcePk: number | null = $state(null);
  let targetPk: number | null = $state(null);
  let sourceRoot = $state('');
  let targetRoot = $state('');
  let selectedPk: number | null = $state(null);
  let reverse = $state(false);
  let report: PageTreeReport | null = $state(null);
  let selected: string[] = $state([]);
  let revisions = $state(50);
  let busy = $state(false);
  let error = $state('');
  let message = $state('');
  const selectedRows = $derived.by(() => report?.rows.filter(row => row.page.source_title && selected.includes(row.page.source_title)) ?? []);
  const canConfirm = $derived(selectedRows.length > 0 && selectedRows.every(row => row.proposal?.proposable));
  const canStage = $derived(selectedRows.length > 0 && selectedRows.every(row => row.page.actionable));

  async function perform(action: () => Promise<void>): Promise<void> {
    busy = true;
    error = '';
    message = '';
    try { await action(); }
    catch (err) { error = err instanceof Error ? err.message : 'Action failed'; }
    finally { busy = false; }
  }

  async function refresh(): Promise<void> {
    if (selectedPk == null) return;
    report = await reportPageTree(selectedPk, reverse);
    selected = [];
  }

  async function save(): Promise<void> {
    const source = sites.find(site => site.pk === sourcePk);
    const target = sites.find(site => site.pk === targetPk);
    if (!source?.label || !target?.label) return;
    await perform(async () => {
      const tree = await createPageTree({ source_label: source.label!, target_label: target.label!, source_root: sourceRoot, target_root: targetRoot });
      trees = await listPageTrees();
      selectedPk = tree.pk;
      reverse = false;
      await refresh();
      message = 'Root mapping saved. Review the descendant mappings before creating their page pairs.';
    });
  }

  async function apply(action: 'pairs' | 'confirm' | 'batches'): Promise<void> {
    if (selectedPk == null) return;
    await perform(async () => {
      await selectPageTree(selectedPk!, action, reverse, selected);
      await refresh();
      message = action === 'batches' ? 'Selected changes staged. Open Batches to inspect the revision diffs before pushing.' : action === 'confirm' ? 'Selected matching revision anchors confirmed.' : 'Selected page pairs saved.';
    });
  }

  function clearReport(): void { report = null; selected = []; message = ''; }
  function toggle(title: string): void {
    selected = selected.includes(title) ? selected.filter(value => value !== title) : [...selected, title];
  }

  onMount(() => perform(async () => {
    [sites, trees] = await Promise.all([listSites(), listPageTrees()]);
    sourcePk = sites[0]?.pk ?? null;
    targetPk = sites[1]?.pk ?? null;
    selectedPk = trees[0]?.pk ?? null;
    if (selectedPk != null) await refresh();
  }));
</script>

<PageHeading eyebrow="Cross-site" title="Page trees">
  <p>Map any root page and its subpages to another namespace or root title.
    Descendants match by the path after the root, including nested subpages.</p>
</PageHeading>

{#if error}<Notice>{error}</Notice>{/if}
{#if message}<Notice kind="success">{message}</Notice>{/if}

<section aria-label="Create a page tree mapping">
  <h2>New root mapping</h2>
  <div class="columns">
    <div>
      <SiteSelect {sites} label="Source site" bind:value={sourcePk} />
      <TextField label="Source root title" bind:value={sourceRoot} placeholder="The Principles of Psychology (James)" />
    </div>
    <div>
      <SiteSelect {sites} label="Target site" bind:value={targetPk} />
      <TextField label="Target root title" bind:value={targetRoot} placeholder="Book:The Principles of Psychology (James)" />
    </div>
  </div>
  <ActionButton disabled={busy || !sourceRoot.trim() || !targetRoot.trim() || sourcePk === targetPk} onclick={save}>Save root mapping</ActionButton>
</section>

<section aria-label="Saved page tree mappings">
  <h2>Saved mappings</h2>
  <label>Root pair
    <select bind:value={selectedPk} onchange={clearReport} disabled={busy}>
      <option value={null}>Choose a mapping</option>
      {#each trees as tree}
        <option value={tree.pk}>{tree.source_label}: {tree.source_root} ↔ {tree.target_label}: {tree.target_root}</option>
      {/each}
    </select>
  </label>
  <label><input type="checkbox" bind:checked={reverse} onchange={clearReport} disabled={busy} /> Reverse direction</label>
  <div class="actions">
    <label>History revisions per page <input type="number" min="1" max="1000" bind:value={revisions} /></label>
    <ActionButton disabled={busy || selectedPk == null || !Number.isInteger(revisions) || revisions < 1 || revisions > 1000} onclick={() => perform(async () => {
      const result = await fetchPageTree(selectedPk!, reverse, revisions);
      message = `Queued ${result.queued} fetches. Drain them from Fetch, then run the report. After first discovery, fetch again to check newly mapped counterpart titles.`;
    })}>Fetch trees and counterparts</ActionButton>
    <ActionButton disabled={busy || selectedPk == null} onclick={() => perform(refresh)}>Run report</ActionButton>
    <a href="/fetch">Open Fetch</a>
  </div>
</section>

{#if report}
  <section aria-label="Page tree sync report">
    <h2>{report.tree.source_label} → {report.tree.target_label}</h2>
    <p>{report.tree.source_root} → {report.tree.target_root}</p>
    <p>{report.note}</p>
    <p>Select mappings to save page pairs, confirm matching revision anchors, or stage writable changes.
      Saving a page pair asserts correspondence; confirming an anchor asserts matching content.</p>
    <div class="actions">
      <ActionButton disabled={busy || selected.length === 0} onclick={() => apply('pairs')}>Pair selected pages</ActionButton>
      <ActionButton disabled={busy || !canConfirm} onclick={() => apply('confirm')}>Confirm selected anchors</ActionButton>
      <ActionButton disabled={busy || !canStage} onclick={() => apply('batches')}>Stage selected changes</ActionButton>
      <a href="/sync/batches">Review Batches and diffs →</a>
    </div>
    <div class="actions">
      <ActionButton variant="ghost" disabled={busy} onclick={() => { selected = report!.rows.flatMap(row => row.page.actionable && row.page.source_title ? [row.page.source_title] : []); }}>Select writable pages</ActionButton>
      <ActionButton variant="ghost" disabled={busy} onclick={() => { selected = report!.rows.flatMap(row => row.proposal?.proposable && row.page.source_title ? [row.page.source_title] : []); }}>Select matching anchors</ActionButton>
      <ActionButton variant="ghost" disabled={busy} onclick={() => { selected = []; }}>Clear selection</ActionButton>
    </div>
    {#if report.rows.length === 0}<p>No cached revisions in either tree. Fetch the roots with their subpages first.</p>{/if}
    {#each report.rows as row (row.path)}
      <article>
        <label>
          <input type="checkbox" checked={selected.includes(row.page.source_title ?? '')} disabled={busy} onchange={() => row.page.source_title && toggle(row.page.source_title)} />
          <strong>{row.path || '(root)'}</strong> · {row.page.verdict}
        </label>
        <p>{row.page.source_title} → {row.page.target_title}</p>
        <p>r{row.page.source_revid ?? '—'} → r{row.page.target_revid ?? '—'} · {row.page.detail}</p>
        {#if row.page.pair_pk}<a href={`/links/pairs/${row.page.pair_pk}`}>Inspect page pair and revisions →</a>{/if}
        {#if row.proposal}
          <p>Anchor proposal: {row.proposal.outcome} · r{row.proposal.local_revid ?? '—'} ↔ r{row.proposal.remote_revid ?? '—'}</p>
          {#if row.proposal.detail}<p>{row.proposal.detail}</p>{/if}
        {/if}
      </article>
    {/each}
  </section>
{/if}

<style>
  section { margin-top: 1.5rem; padding: 1.2rem; border: 1px solid #cdbca8; border-radius: 16px; }
  h2 { font-size: 1.1rem; margin-top: 0; }
  .columns { display: grid; grid-template-columns: repeat(auto-fit, minmax(16rem, 1fr)); gap: 1rem; margin-bottom: 1rem; }
  .columns > div { display: grid; gap: 1rem; }
  .actions { display: flex; flex-wrap: wrap; gap: 0.8rem; align-items: end; margin: 1rem 0; }
  select { display: block; max-width: 100%; margin: 0.5rem 0 1rem; }
  article { padding: 1rem 0; border-top: 1px solid #cdbca8; overflow-wrap: anywhere; }
  p { color: #73583d; }
</style>
