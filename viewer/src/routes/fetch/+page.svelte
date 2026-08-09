<script lang="ts">
  import { onMount } from 'svelte';
  import { createFetch, listSites } from '$lib/api';
  import ActionButton from '$lib/components/ActionButton.svelte';
  import FormRow from '$lib/components/FormRow.svelte';
  import Notice from '$lib/components/Notice.svelte';
  import PageHeading from '$lib/components/PageHeading.svelte';
  import SelectField from '$lib/components/SelectField.svelte';
  import SiteSelect from '$lib/components/SiteSelect.svelte';
  import TextField from '$lib/components/TextField.svelte';
  import { siteLabel } from '$lib/format';
  import type { FetchKind, FetchResponse, Site } from '$lib/types';

  let title = $state('Index:');
  let sites: Site[] = $state([]);
  let selectedSitePk: number | null = $state(null);
  let kind: FetchKind = $state('single');
  let depth = $state(0);
  let revisions = $state(1);
  let loadingSites = $state(true);
  let loading = $state(false);
  let error = $state('');
  let result: FetchResponse | null = $state(null);

  const selectedSite = $derived(sites.find((site) => site.pk === selectedSitePk) ?? null);

  async function loadSites(): Promise<void> {
    loadingSites = true;
    error = '';
    try {
      sites = await listSites();
      selectedSitePk = sites[0]?.pk ?? null;
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to load sites';
    } finally {
      loadingSites = false;
    }
  }

  async function submitFetch(): Promise<void> {
    // The site is named by its registered label, not by family/code/api_url:
    // nothing conjures a site from a fetch request's parameters, so a fetch
    // against an unregistered wiki is a 404 rather than a new Site row.
    const label = selectedSite?.label;
    if (!label) {
      error = 'Register a site first -- a fetch names a registered wiki by label.';
      return;
    }
    loading = true;
    error = '';
    result = null;
    try {
      result = await createFetch({ title, label, kind, depth, revisions });
    } catch (err) {
      error = err instanceof Error ? err.message : 'Fetch request failed';
    } finally {
      loading = false;
    }
  }

  onMount(loadSites);
</script>

<PageHeading eyebrow="Checkout" title="Fetch wikitext into the local cache.">
  <p class="description">
    This creates a `FetchRequest`, drains the Python worker inline, and writes
    the fetched page snapshot into SQLite.
  </p>
</PageHeading>

<form class="fetch-form" onsubmit={(event) => { event.preventDefault(); void submitFetch(); }}>
  <TextField label="Title" bind:value={title} required placeholder="Index:Example.djvu" />

  {#if loadingSites}
    <p class="state">Loading sites...</p>
  {:else if sites.length > 1}
    <SiteSelect {sites} bind:value={selectedSitePk} />
  {:else if sites.length === 1}
    <div class="site-summary">
      <span>Site</span>
      <strong>{siteLabel(sites[0])}</strong>
      <small>{sites[0].api_url ?? `${sites[0].family}:${sites[0].code}`}</small>
    </div>
  {:else}
    <Notice>No sites registered. Add one on the Sites page before fetching.</Notice>
  {/if}

  <FormRow>
    <SelectField label="Kind" bind:value={kind}>
      <option value="single">single</option>
      <option value="index">index</option>
    </SelectField>
    <TextField label="Depth" type="number" min="0" max="3" bind:value={depth} />
    <TextField label="Revisions" type="number" min="1" max="500" bind:value={revisions} />
  </FormRow>

  <p class="hint">
    <strong>Revisions</strong> is how far back from the head to store. 1 is a normal
    fetch -- the head is all the editor and the VFS need. More fills in history for
    the cross-site anchor search, which cannot find a match at the head when one side
    was imported from an older revision of the other. Index fan-out children inherit
    it.
  </p>

  <div class="submit-row">
    <ActionButton type="submit" disabled={loading}>
      {loading ? 'Fetching...' : 'Fetch into cache'}
    </ActionButton>
  </div>
</form>

{#if error}
  <Notice>{error}</Notice>
{/if}

{#if result}
  <section class="result">
    <p class="eyebrow">Fetch result</p>
    <h2>{result.request.status}</h2>
    <dl>
      <div>
        <dt>Request</dt>
        <dd>#{result.request.pk} for {result.request.title}</dd>
      </div>
      <div>
        <dt>Progress</dt>
        <dd>{result.request.progress_done ?? 0} / {result.request.progress_total ?? 0}</dd>
      </div>
      <div>
        <dt>Cached page</dt>
        <dd>{result.page ? `${result.page.namespace_role} #${result.page.pk}` : 'not written'}</dd>
      </div>
    </dl>
    {#if result.request.error_message}
      <Notice>{result.request.error_message}</Notice>
    {/if}
  </section>
{/if}

<style>
  .hint {
    max-width: 46rem;
    color: #73583d;
    font-size: 0.84rem;
  }

  .description {
    color: #594430;
    font-size: 1.1rem;
    line-height: 1.55;
  }

  .fetch-form,
  .result {
    border: 1px solid rgba(72, 49, 31, 0.18);
    border-radius: 24px;
    background: rgba(255, 252, 240, 0.72);
    box-shadow: 0 20px 60px rgba(62, 44, 30, 0.12);
    margin-top: 1.5rem;
    max-width: 48rem;
    padding: 1.3rem;
  }

  .fetch-form {
    display: grid;
    gap: 1rem;
  }

  .site-summary {
    border: 1px solid rgba(72, 49, 31, 0.16);
    border-radius: 14px;
    background: rgba(255, 253, 245, 0.68);
    display: grid;
    gap: 0.25rem;
    padding: 0.85rem 0.95rem;
  }

  .site-summary strong,
  .site-summary small {
    display: block;
  }

  .site-summary small {
    color: #73583d;
    font-family: "Avenir Next", "Gill Sans", sans-serif;
    font-size: 0.82rem;
  }

  .site-summary span,
  dt {
    color: #73583d;
    font-family: "Avenir Next", "Gill Sans", sans-serif;
    font-size: 0.74rem;
    font-weight: 800;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }

  .submit-row {
    justify-self: start;
  }

  dl {
    display: grid;
    gap: 0.8rem;
    margin: 1rem 0 0;
  }

  dl div {
    border-top: 1px solid rgba(72, 49, 31, 0.14);
    padding-top: 0.8rem;
  }

  dd {
    margin: 0.2rem 0 0;
  }
</style>
