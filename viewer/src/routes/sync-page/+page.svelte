<script lang="ts">
  import { onMount } from 'svelte';
  import { page as routePage } from '$app/state';
  import { listSites, nextChange, pushChange } from '$lib/api';
  import ActionButton from '$lib/components/ActionButton.svelte';
  import Notice from '$lib/components/Notice.svelte';
  import PageHeading from '$lib/components/PageHeading.svelte';
  import SiteSelect from '$lib/components/SiteSelect.svelte';
  import TextField from '$lib/components/TextField.svelte';
  import type { ChangePushResult, ChangeReview, Site } from '$lib/types';

  let sites: Site[] = $state([]);
  let sourcePk: number | null = $state(null);
  let targetPk: number | null = $state(null);
  let sourceTitle = $state('');
  let targetTitle = $state('');
  let change: ChangeReview | null = $state(null);
  let result: ChangePushResult | null = $state(null);
  let loading = $state(true);
  let calculating = $state(false);
  let pushing = $state(false);
  let noChange = $state(false);
  let error = $state('');

  const sourceSite = $derived(sites.find((site) => site.pk === sourcePk) ?? null);
  const targetSite = $derived(sites.find((site) => site.pk === targetPk) ?? null);

  onMount(async () => {
    try {
      sites = await listSites();
      sourcePk = sites[0]?.pk ?? null;
      targetPk = sites[1]?.pk ?? sites[0]?.pk ?? null;
      sourceTitle = routePage.url.searchParams.get('title') ?? '';
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to load sites';
    } finally {
      loading = false;
    }
  });

  function siteLabel(site: Site | null): string {
    return site?.label ?? '';
  }

  async function calculate(): Promise<void> {
    if (!sourceTitle || !siteLabel(sourceSite) || !siteLabel(targetSite)) return;
    calculating = true;
    error = '';
    noChange = false;
    result = null;
    try {
      change = await nextChange({
        source_site: siteLabel(sourceSite),
        target_site: siteLabel(targetSite),
        source_title: sourceTitle,
        target_title: targetTitle || sourceTitle
      });
      noChange = change === null;
    } catch (err) {
      change = null;
      error = err instanceof Error ? err.message : 'Could not calculate the next change';
    } finally {
      calculating = false;
    }
  }

  async function push(): Promise<void> {
    if (!change) return;
    pushing = true;
    error = '';
    try {
      result = await pushChange(change.pk);
    } catch (err) {
      error = err instanceof Error ? err.message : 'The push failed';
    } finally {
      pushing = false;
    }
  }

  function swap(): void {
    [sourcePk, targetPk] = [targetPk, sourcePk];
    [sourceTitle, targetTitle] = [targetTitle || sourceTitle, sourceTitle];
    change = null;
    result = null;
    noChange = false;
  }
</script>

<PageHeading eyebrow="One revision, reviewed" title="Push one exact change">
  <p class="description">
    Calculate the next source revision, inspect the frozen body and diff, then make one
    conditional MediaWiki write. This screen stops after the result.
  </p>
</PageHeading>

{#if error}<Notice>{error}</Notice>{/if}

{#if loading}
  <p class="muted">Loading...</p>
{:else if !change && !result}
  <section class="controls" aria-label="Change direction and page">
    <div class="side">
      <SiteSelect {sites} label="Source site" bind:value={sourcePk} />
      <TextField label="Source page" bind:value={sourceTitle} placeholder="Page:Foo.pdf/12" />
    </div>
    <button type="button" class="swap" onclick={swap} title="Reverse direction">&rarr;&nbsp;&larr;</button>
    <div class="side">
      <SiteSelect {sites} label="Target site" bind:value={targetPk} />
      <TextField label="Target page (if different)" bind:value={targetTitle} placeholder="same title" />
    </div>
  </section>
  <ActionButton disabled={calculating || !sourceTitle} onclick={calculate}>
    {calculating ? 'Calculating...' : 'Show next exact change'}
  </ActionButton>
  {#if noChange}<Notice>There is no next change for this page.</Notice>{/if}
{/if}

{#if change && !result}
  <section class="summary">
    <div>
      <span>Source</span>
      <strong>{change.source.site} · {change.source.title}</strong>
      <p>MediaWiki revision {change.source.revid} · local row {change.source.revision_pk}</p>
      <p>{change.source.contributor ?? 'unknown contributor'}{change.source.comment ? ` — ${change.source.comment}` : ''}</p>
    </div>
    <div>
      <span>Target · {change.intent}</span>
      <strong>{change.target.site} · {change.target.title}</strong>
      <p>{change.target.base_revid ? `Base revision ${change.target.base_revid}` : 'Create new page'}</p>
      <a href={change.target.url} target="_blank" rel="noreferrer">Open current target</a>
    </div>
  </section>

  {#if change.transformations.length}
    <section class="checks">
      <h2>Transformations</h2>
      <ul>{#each change.transformations as item}<li>{item}</li>{/each}</ul>
    </section>
  {/if}

  <section class="review">
    <h2>Exact submitted body</h2>
    <pre>{change.submitted_body}</pre>
  </section>
  <section class="review">
    <h2>Diff against current target</h2>
    <pre>{change.diff || 'No textual difference.'}</pre>
  </section>

  <section class="checks" class:blocked={change.blockers.length > 0}>
    <h2>Blocking safety checks</h2>
    {#if change.blockers.length}
      <ul>{#each change.blockers as blocker}<li>{blocker}</li>{/each}</ul>
    {:else}
      <p>Page/revision correspondence, cached history, source head and target base checks passed.</p>
    {/if}
  </section>

  <div class="push-row">
    <ActionButton disabled={pushing || change.blockers.length > 0} onclick={push}>
      {pushing ? 'Pushing...' : 'Push this change'}
    </ActionButton>
    <small>Pressing this button is approval. It performs exactly one write.</small>
  </div>
{/if}

{#if result}
  <section class="result" class:bad={result.status === 'conflict' || result.status === 'error'}>
    <span>MediaWiki result</span>
    <h2>{result.status.replace('_', ' ')}</h2>
    {#if result.error}<p>{result.error}</p>{/if}
    {#if result.new_target_revid}<p>New target revision: {result.new_target_revid}</p>{/if}
    {#if result.target_revision_url}
      <p><a href={result.target_revision_url} target="_blank" rel="noreferrer">Inspect the permanent target revision</a></p>
    {/if}
    <dl>
      <dt>Submitted edit summary</dt><dd>{result.edit_summary ?? 'none'}</dd>
      <dt>Verification refetch</dt><dd>{result.verification_refetch}</dd>
      <dt>Revision correspondence</dt><dd>{result.correspondence_materialized ? 'materialized' : 'pending'}</dd>
    </dl>
  </section>
  <ActionButton onclick={calculate}>Check next change</ActionButton>
{/if}

<style>
  .description, .muted, small, p { color: #73583d; }
  .controls, .summary { display: grid; grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr); gap: 1rem; align-items: center; margin: 1.5rem 0; }
  .side, .summary > div, .checks, .review, .result { border: 1px solid rgba(72,49,31,.18); border-radius: 18px; background: rgba(255,252,240,.7); padding: 1rem; }
  .side { display: grid; gap: .75rem; }
  .swap { border: 1px solid rgba(72,49,31,.24); border-radius: 99px; background: #fffaf0; color: #9c5632; padding: .7rem; cursor: pointer; }
  .summary { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .summary span, .result > span { color: #73583d; font-size: .72rem; letter-spacing: .08em; text-transform: uppercase; }
  .summary strong { display: block; overflow-wrap: anywhere; margin: .25rem 0; }
  .summary p { margin: .25rem 0; }
  .checks, .review, .result { margin: 1rem 0; }
  .checks h2, .review h2, .result h2 { margin: 0 0 .6rem; font-size: 1rem; }
  .checks.blocked, .result.bad { border-color: rgba(178,69,47,.5); background: rgba(255,238,233,.76); }
  pre { max-height: 34rem; overflow: auto; margin: 0; border-radius: 12px; background: #241b13; color: #fff8e6; padding: 1rem; white-space: pre-wrap; overflow-wrap: anywhere; }
  .push-row { display: flex; align-items: center; gap: 1rem; margin: 1.25rem 0; }
  dl { display: grid; grid-template-columns: max-content 1fr; gap: .4rem 1rem; }
  dt { font-weight: 700; } dd { margin: 0; }
  a { color: #9c5632; }
  @media (max-width: 760px) { .controls, .summary { grid-template-columns: 1fr; } .swap { justify-self: start; } }
</style>
