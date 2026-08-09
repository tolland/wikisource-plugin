<script lang="ts">
  import { onMount } from 'svelte';
  import { page as routePage } from '$app/state';
  import { fetchSyncAssets, listIndexCandidates, listSites, syncReport } from '$lib/api';
  import ActionButton from '$lib/components/ActionButton.svelte';
  import Notice from '$lib/components/Notice.svelte';
  import PageHeading from '$lib/components/PageHeading.svelte';
  import SelectField from '$lib/components/SelectField.svelte';
  import SiteSelect from '$lib/components/SiteSelect.svelte';
  import type { Site, SyncPage, SyncReport, SyncVerdict } from '$lib/types';

  /**
   * `sync --from Index:X [--to Index:Y]`, with somewhere to look at the answer.
   *
   * Directional, and the direction is the first control on the page: the same
   * two wikis and the same work produce opposite reports depending on which
   * way round they are read, and a page that hid that would be answering a
   * different question from the one asked.
   *
   * Read-only, deliberately and visibly. Nothing here writes to either wiki or
   * to the local model -- not even the pairings it reads -- so the report can
   * be re-run as often as it takes without consequences.
   */

  let sites: Site[] = $state([]);
  let sourcePk: number | null = $state(null);
  let targetPk: number | null = $state(null);
  let sourceIndexes: string[] = $state([]);
  let targetIndexes: string[] = $state([]);
  let indexTitle = $state('');
  let targetIndexTitle = $state('');
  let show: 'actionable' | 'all' | 'problems' = $state('actionable');

  let report: SyncReport | null = $state(null);
  let loading = $state(true);
  let running = $state(false);
  let fetching = $state(false);
  let error = $state('');
  let message = $state('');

  const sourceSite = $derived(sites.find((site) => site.pk === sourcePk) ?? null);
  const targetSite = $derived(sites.find((site) => site.pk === targetPk) ?? null);

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
    pull: {
      label: 'pull',
      tone: 'in',
      note: 'The target has moved on and the source has not. Work in the other direction.'
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
      note: 'Both sides hold content, but nothing says which revisions correspond.'
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

  function label(site: Site | null): string | null {
    return site?.label ?? null;
  }

  async function loadIndexes(which: 'source' | 'target'): Promise<void> {
    const pk = which === 'source' ? sourcePk : targetPk;
    if (pk === null) return;
    const titles = (await listIndexCandidates(pk)).indexes.map((item) => item.title);
    if (which === 'source') {
      sourceIndexes = titles;
      if (!indexTitle) indexTitle = titles[0] ?? '';
    } else {
      targetIndexes = titles;
    }
  }

  async function load(): Promise<void> {
    loading = true;
    error = '';
    try {
      sites = await listSites();
      sourcePk = sites[0]?.pk ?? null;
      targetPk = sites[1]?.pk ?? sites[0]?.pk ?? null;
      await Promise.all([loadIndexes('source'), loadIndexes('target')]);
      const requested = routePage.url.searchParams.get('index');
      if (requested) indexTitle = requested;
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to load sites';
    } finally {
      loading = false;
    }
  }

  async function run(): Promise<void> {
    if (!indexTitle) return;
    running = true;
    error = '';
    try {
      report = await syncReport({
        source_label: label(sourceSite),
        target_label: label(targetSite),
        index_title: indexTitle,
        // Empty means "the same title on both sides", which is the common case.
        target_index_title: targetIndexTitle || null
      });
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
    fetching = true;
    error = '';
    message = '';
    try {
      const result = await fetchSyncAssets({
        source_label: label(sourceSite),
        target_label: label(targetSite),
        index_title: indexTitle,
        target_index_title: targetIndexTitle || null
      });
      message = result.queued.length
        ? `Queued ${result.queued.map((item) => `${item.title} on ${item.label}`).join(', ')}. ${result.note}`
        : 'Nothing to fetch: both assets are already held.';
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to queue the assets';
    } finally {
      fetching = false;
    }
  }

  function swap(): void {
    [sourcePk, targetPk] = [targetPk, sourcePk];
    [sourceIndexes, targetIndexes] = [targetIndexes, sourceIndexes];
    [indexTitle, targetIndexTitle] = [targetIndexTitle || indexTitle, indexTitle];
    report = null;
  }

  onMount(load);
</script>

<PageHeading eyebrow="Dry run" title="Sync report">
  <p class="description">
    What copying a work from one wiki to the other would change &mdash; page by page,
    with the scan check first. Nothing here writes to either wiki, or to the local
    model.
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
  <section class="controls" aria-label="Direction">
    <div class="side">
      <SiteSelect
        {sites}
        label="From (source)"
        bind:value={sourcePk}
        onchange={() => loadIndexes('source')}
      />
      <SelectField label="Index" bind:value={indexTitle}>
        {#each sourceIndexes as title}
          <option value={title}>{title}</option>
        {/each}
      </SelectField>
    </div>

    <button type="button" class="swap" onclick={swap} title="Reverse the direction">
      &rarr;&nbsp;&larr;
    </button>

    <div class="side">
      <SiteSelect
        {sites}
        label="To (target)"
        bind:value={targetPk}
        onchange={() => loadIndexes('target')}
      />
      <SelectField label="Index (only if the title differs)" bind:value={targetIndexTitle}>
        <option value="">same title</option>
        {#each targetIndexes as title}
          <option value={title}>{title}</option>
        {/each}
      </SelectField>
    </div>
  </section>

  <div class="run-row">
    <ActionButton disabled={running || !indexTitle} onclick={run}>
      {running ? 'Comparing...' : 'Run the report'}
    </ActionButton>
    <span class="hint">
      The target index does not have to exist &mdash; that is the case this is most
      useful for, and every page then reports <code>create</code>.
    </span>
  </div>
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

  <section class="summary" aria-label="Verdicts">
    {#each Object.entries(report.counts) as [verdict, count]}
      <span class="chip {VERDICTS[verdict as SyncVerdict]?.tone ?? 'warn'}">
        {VERDICTS[verdict as SyncVerdict]?.label ?? verdict}
        <strong>{count}</strong>
      </span>
    {/each}
    <span class="total">{report.actionable} page(s) a push would write</span>
  </section>

  <div class="filter">
    <SelectField label="Show" bind:value={show}>
      <option value="actionable">what would be written</option>
      <option value="problems">what needs a person</option>
      <option value="all">every page</option>
    </SelectField>
    {#if report.work_pk}
      <a class="drill" href={`/links/${report.work_pk}`}>Open the tracked work &rarr;</a>
    {/if}
  </div>

  {#if visible.length === 0}
    <p class="state">Nothing in this view.</p>
  {:else}
    <table class="pages">
      <thead>
        <tr>
          <th scope="col">#</th>
          <th scope="col">Verdict</th>
          <th scope="col">Page</th>
          <th scope="col">Revisions</th>
          <th scope="col"></th>
        </tr>
      </thead>
      <tbody>
        {#each visible as row}
          <tr>
            <td>{row.page_number ?? '?'}</td>
            <td>
              <span class="chip {VERDICTS[row.verdict]?.tone ?? 'warn'}">
                {VERDICTS[row.verdict]?.label ?? row.verdict}
              </span>
            </td>
            <td class="title">
              {row.source_title ?? row.target_title}
              <small>{row.detail ?? VERDICTS[row.verdict]?.note ?? ''}</small>
            </td>
            <td class="revs">
              {row.source_revid ?? '-'} &rarr; {row.target_revid ?? 'none'}
              {#if row.anchor_source_revid}
                <small>
                  anchor {row.anchor_source_revid} &harr; {row.anchor_target_revid}
                </small>
              {/if}
            </td>
            <td>
              {#if row.pair_pk}
                <a class="drill" href={`/links/pairs/${row.pair_pk}`}>Revisions</a>
              {/if}
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}

  <p class="footnote">
    This is a report. Nothing has been written to {report.target.site}, and nothing to
    the local model &mdash; pairing the work is a separate, deliberate act on the
    <a href="/links">Links</a> page.
  </p>
{/if}

<style>
  .description,
  .state,
  .hint {
    color: #73583d;
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

  .filter {
    display: flex;
    flex-wrap: wrap;
    gap: 1rem;
    align-items: end;
    margin-bottom: 1rem;
  }

  .pages {
    width: 100%;
    border-collapse: collapse;
  }

  .pages th,
  .pages td {
    border-bottom: 1px solid rgba(72, 49, 31, 0.14);
    padding: 0.55rem 0.5rem;
    text-align: left;
    vertical-align: top;
  }

  .pages th {
    color: #73583d;
    font-family: "Avenir Next", "Gill Sans", sans-serif;
    font-size: 0.72rem;
    letter-spacing: 0.06em;
    text-transform: uppercase;
  }

  .pages .title {
    overflow-wrap: anywhere;
  }

  .pages small {
    display: block;
    margin-top: 0.2rem;
    color: #73583d;
    font-size: 0.76rem;
  }

  .pages .revs {
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 0.8rem;
    white-space: nowrap;
  }

  .drill {
    color: #9c5632;
    font-family: "Avenir Next", "Gill Sans", sans-serif;
    font-size: 0.76rem;
    font-weight: 700;
    text-transform: uppercase;
    white-space: nowrap;
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
