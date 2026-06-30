<script lang="ts">
  import { createFetch } from '$lib/api';
  import type { FetchKind, FetchResponse } from '$lib/types';

  let title = $state('Index:');
  let family = $state('wikisource');
  let code = $state('en');
  let apiUrl = $state('https://en.wikisource.org/w/api.php');
  let kind: FetchKind = $state('single');
  let depth = $state(0);
  let loading = $state(false);
  let error = $state('');
  let result: FetchResponse | null = $state(null);

  async function submitFetch(): Promise<void> {
    loading = true;
    error = '';
    result = null;
    try {
      result = await createFetch({
        title,
        family,
        code,
        api_url: apiUrl || null,
        kind,
        depth
      });
    } catch (err) {
      error = err instanceof Error ? err.message : 'Fetch request failed';
    } finally {
      loading = false;
    }
  }
</script>

<section class="page-heading">
  <p class="eyebrow">Checkout</p>
  <h1>Fetch wikitext into the local cache.</h1>
  <p>
    This creates a `FetchRequest`, drains the Python worker inline, and writes
    the fetched page snapshot into SQLite.
  </p>
</section>

<form class="fetch-form" onsubmit={(event) => { event.preventDefault(); void submitFetch(); }}>
  <label>
    <span>Title</span>
    <input bind:value={title} required placeholder="Index:Example.djvu" />
  </label>

  <div class="form-row">
    <label>
      <span>Family</span>
      <input bind:value={family} required />
    </label>
    <label>
      <span>Code</span>
      <input bind:value={code} required />
    </label>
  </div>

  <label>
    <span>API URL</span>
    <input bind:value={apiUrl} placeholder="https://en.wikisource.org/w/api.php" />
  </label>

  <div class="form-row">
    <label>
      <span>Kind</span>
      <select bind:value={kind}>
        <option value="single">single</option>
        <option value="index">index</option>
      </select>
    </label>
    <label>
      <span>Depth</span>
      <input type="number" min="0" max="3" bind:value={depth} />
    </label>
  </div>

  <button type="submit" disabled={loading}>{loading ? 'Fetching...' : 'Fetch into cache'}</button>
</form>

{#if error}
  <div class="notice">{error}</div>
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
      <div class="notice">{result.request.error_message}</div>
    {/if}
  </section>
{/if}

<style>
  .page-heading {
    max-width: 56rem;
  }

  .page-heading h1 {
    font-size: clamp(2.5rem, 6vw, 5.8rem);
    letter-spacing: -0.05em;
  }

  .page-heading p {
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

  .form-row {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 1rem;
  }

  label {
    display: grid;
    gap: 0.4rem;
  }

  label span,
  dt {
    color: #73583d;
    font-family: "Avenir Next", "Gill Sans", sans-serif;
    font-size: 0.74rem;
    font-weight: 800;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }

  input,
  select {
    border: 1px solid rgba(72, 49, 31, 0.24);
    border-radius: 12px;
    background: #fffdf5;
    color: #241b13;
    font: inherit;
    padding: 0.8rem 0.9rem;
  }

  button {
    justify-self: start;
    border: 0;
    border-radius: 999px;
    background: #9c5632;
    color: #fff8e6;
    cursor: pointer;
    font-family: "Avenir Next", "Gill Sans", sans-serif;
    font-weight: 800;
    letter-spacing: 0.06em;
    padding: 0.85rem 1.2rem;
    text-transform: uppercase;
  }

  button:disabled {
    cursor: wait;
    opacity: 0.62;
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

  @media (max-width: 680px) {
    .form-row {
      grid-template-columns: 1fr;
    }
  }
</style>
