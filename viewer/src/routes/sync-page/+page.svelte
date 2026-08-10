<script lang="ts">
  import { onMount } from 'svelte';
  import { page as routePage } from '$app/state';
  import { listSites, stagePageBatch, syncPageReport } from '$lib/api';
  import { goto } from '$app/navigation';
  import ActionButton from '$lib/components/ActionButton.svelte';
  import Notice from '$lib/components/Notice.svelte';
  import PageHeading from '$lib/components/PageHeading.svelte';
  import SiteSelect from '$lib/components/SiteSelect.svelte';
  import TextField from '$lib/components/TextField.svelte';
  import type { PageSyncReport, Site, SyncVerdict } from '$lib/types';

  /**
   * `sync-page --from Page:X [--to Page:Y]`: the embarrassment-risk workflow,
   * scoped to one page and its revisions.
   *
   * The `/sync` route's counterpart, deliberately narrower. That page fans a
   * whole work out into a list; this one asks about exactly the page named and
   * nothing else -- no scan check, no sibling pages, no index. Staging still
   * produces an ordinary batch (of one promotion), so approval and the push
   * itself happen on the same `/sync/batches/[pk]` screen a work-level run
   * uses -- a batch of one page is still a batch.
   */

  let sites: Site[] = $state([]);
  let sourcePk: number | null = $state(null);
  let targetPk: number | null = $state(null);
  let sourceTitle = $state('');
  let targetTitle = $state('');

  let report: PageSyncReport | null = $state(null);
  let loading = $state(true);
  let running = $state(false);
  let staging = $state(false);
  let batchLabel = $state('');
  let error = $state('');

  const sourceSite = $derived(sites.find((site) => site.pk === sourcePk) ?? null);
  const targetSite = $derived(sites.find((site) => site.pk === targetPk) ?? null);

  const VERDICTS: Record<SyncVerdict, { label: string; tone: string; note: string }> = {
    create: {
      label: 'create',
      tone: 'go',
      note: 'The target has no such page, or only an untranscribed placeholder.'
    },
    push: {
      label: 'push',
      tone: 'go',
      note: 'The source has moved past the anchor; the target has not.'
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
      note: 'The target has this page and the source does not.'
    },
    unknown: {
      label: 'unknown',
      tone: 'warn',
      note: 'A side has not been fetched. A fetch, not a verdict.'
    }
  };

  function label(site: Site | null): string | null {
    return site?.label ?? null;
  }

  async function load(): Promise<void> {
    loading = true;
    error = '';
    try {
      sites = await listSites();
      sourcePk = sites[0]?.pk ?? null;
      targetPk = sites[1]?.pk ?? sites[0]?.pk ?? null;
      const requested = routePage.url.searchParams.get('title');
      if (requested) sourceTitle = requested;
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to load sites';
    } finally {
      loading = false;
    }
  }

  async function run(): Promise<void> {
    if (!sourceTitle) return;
    running = true;
    error = '';
    try {
      report = await syncPageReport({
        source_label: label(sourceSite),
        target_label: label(targetSite),
        source_title: sourceTitle,
        target_title: targetTitle || null
      });
    } catch (err) {
      error = err instanceof Error ? err.message : 'The report failed';
      report = null;
    } finally {
      running = false;
    }
  }

  async function stage(): Promise<void> {
    staging = true;
    error = '';
    try {
      const batch = await stagePageBatch({
        source_label: label(sourceSite),
        target_label: label(targetSite),
        source_title: sourceTitle,
        target_title: targetTitle || null,
        label: batchLabel || null
      });
      await goto(`/sync/batches/${batch.pk}`);
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to stage the page';
    } finally {
      staging = false;
    }
  }

  function swap(): void {
    [sourcePk, targetPk] = [targetPk, sourcePk];
    [sourceTitle, targetTitle] = [targetTitle || sourceTitle, sourceTitle];
    report = null;
  }

  onMount(load);
</script>

<PageHeading eyebrow="One page, reviewed" title="Promote a page">
  <p class="description">
    What pushing a single page would change &mdash; nothing else fetched, staged
    or written alongside it. The screen this exists for: a page that should go
    back to the public wiki on its own, without waiting on the rest of the work.
  </p>
</PageHeading>

{#if error}
  <Notice>{error}</Notice>
{/if}

{#if loading}
  <p class="state">Loading...</p>
{:else}
  <section class="controls" aria-label="Direction">
    <div class="side">
      <SiteSelect {sites} label="From (source)" bind:value={sourcePk} />
      <TextField label="Page title" bind:value={sourceTitle} placeholder="Page:Foo.djvu/1" />
    </div>

    <button type="button" class="swap" onclick={swap} title="Reverse the direction">
      &rarr;&nbsp;&larr;
    </button>

    <div class="side">
      <SiteSelect {sites} label="To (target)" bind:value={targetPk} />
      <TextField
        label="Page title (only if it differs)"
        bind:value={targetTitle}
        placeholder="same title"
      />
    </div>
  </section>

  <div class="run-row">
    <ActionButton disabled={running || !sourceTitle} onclick={run}>
      {running ? 'Comparing...' : 'Run the report'}
    </ActionButton>
    <span class="hint">
      The target does not have to exist &mdash; that reports as <code>create</code>.
    </span>
  </div>
{/if}

{#if report}
  <section class="sides" aria-label="Both sides">
    <div class="side-card">
      <p class="eyebrow">Source &middot; {report.source_site}</p>
      <strong>{report.page.source_title ?? sourceTitle}</strong>
      <small>revision {report.page.source_revid ?? '—'}</small>
    </div>
    <div class="side-card" class:missing={!report.page.target_title}>
      <p class="eyebrow">Target &middot; {report.target_site}</p>
      <strong>{report.page.target_title ?? (targetTitle || sourceTitle)}</strong>
      {#if report.page.target_revid}
        <small>revision {report.page.target_revid}</small>
      {:else}
        <small class="absent">no page on the target side &mdash; this would be created</small>
      {/if}
    </div>
  </section>

  <section class="verdict" aria-label="Verdict">
    <span class="chip {VERDICTS[report.page.verdict]?.tone ?? 'warn'}">
      {VERDICTS[report.page.verdict]?.label ?? report.page.verdict}
    </span>
    <p>{report.page.detail ?? VERDICTS[report.page.verdict]?.note ?? ''}</p>
    {#if report.page.anchor_source_revid}
      <small class="anchor">
        anchor {report.page.anchor_source_revid} &harr; {report.page.anchor_target_revid}
      </small>
    {/if}
    {#if report.page.linkable}
      <small class="linkable">
        A matching revision pair exists but is not linked &mdash; link it first
        (Links) before this can be pushed.
      </small>
    {/if}
  </section>

  {#if report.page.actionable}
    <section class="stage" aria-label="Stage this page">
      <h2>Stage this page</h2>
      <p>
        Freezes the body, base revision and anchor into one reviewable
        promotion. Nothing is pushed until it is approved on the next screen.
      </p>
      <div class="row">
        <TextField label="Name this run (optional)" bind:value={batchLabel} />
        <ActionButton disabled={staging} onclick={stage}>
          {staging ? 'Staging...' : 'Stage this page'}
        </ActionButton>
      </div>
    </section>
  {:else}
    <Notice>Not writable in this direction: {VERDICTS[report.page.verdict]?.note ?? report.page.verdict}</Notice>
  {/if}

  <p class="footnote">
    This is a report. Nothing has been written to {report.target_site}. See
    <a href="/sync/batches">pending and past runs</a> for anything already staged.
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

  .verdict {
    border: 1px solid rgba(72, 49, 31, 0.18);
    border-radius: 18px;
    margin: 1rem 0;
    padding: 0.9rem 1.1rem;
  }

  .verdict p {
    margin: 0.5rem 0 0;
    color: #73583d;
    font-size: 0.88rem;
  }

  .verdict .anchor,
  .verdict .linkable {
    display: block;
    margin-top: 0.4rem;
    color: #73583d;
    font-size: 0.78rem;
  }

  .verdict .linkable {
    color: #7d5510;
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

  .stage {
    border: 1px solid rgba(40, 107, 76, 0.34);
    border-radius: 20px;
    background: rgba(229, 246, 235, 0.5);
    margin: 1rem 0 1.5rem;
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

  .stage .row {
    display: flex;
    flex-wrap: wrap;
    gap: 0.6rem;
    align-items: end;
  }

  .footnote {
    margin-top: 1.5rem;
    color: #73583d;
    font-size: 0.84rem;
  }

  .footnote a {
    color: #9c5632;
  }

  @media (max-width: 860px) {
    .controls {
      grid-template-columns: 1fr;
    }
  }
</style>
