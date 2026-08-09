<script lang="ts">
  import { onMount } from 'svelte';
  import { page } from '$app/state';
  import { assertRung, getPairRevisions, retractRung } from '$lib/api';
  import ActionButton from '$lib/components/ActionButton.svelte';
  import Notice from '$lib/components/Notice.svelte';
  import PageHeading from '$lib/components/PageHeading.svelte';
  import type { PairRevisions, RevisionMatch, RevisionRow } from '$lib/types';

  /**
   * Level 3: both histories, and every revision pair that holds the same content.
   *
   * This is the view that unsticks a `quality_differs` page. The anchor search
   * compares each head against the other side's history one side at a time and
   * stops there, so a page where *both* sides have moved on since they last
   * agreed gets no proposal -- even though the agreeing pair is sitting in the
   * two histories. Matching is by `comparable_sha1`, the same predicate the
   * search uses, so anything shown as a match here is a real one.
   *
   * The digest is also what the colour coding is: revisions sharing a digest
   * get the same swatch, which makes "these two are the same content" readable
   * at a glance across two columns of near-identical wikitext.
   */

  const pairPk = Number(page.params.pair_pk);

  let data: PairRevisions | null = $state(null);
  let loading = $state(true);
  let busy = $state(false);
  let error = $state('');
  let message = $state('');
  let localPick: number | null = $state(null);
  let remotePick: number | null = $state(null);

  /** Digest -> swatch index, assigned in the order digests first appear. */
  const swatches = $derived.by(() => {
    const map = new Map<string, number>();
    for (const row of [...(data?.local ?? []), ...(data?.remote ?? [])]) {
      if (row.comparable_sha1 && !map.has(row.comparable_sha1)) {
        map.set(row.comparable_sha1, map.size % 8);
      }
    }
    return map;
  });

  /** Only digests present on *both* sides say anything; the rest are noise. */
  const shared = $derived.by(() => {
    const local = new Set((data?.local ?? []).map((row) => row.comparable_sha1));
    return new Set(
      (data?.remote ?? [])
        .map((row) => row.comparable_sha1)
        .filter((digest) => digest && local.has(digest))
    );
  });

  const picked = $derived.by(() => {
    if (localPick === null || remotePick === null) return null;
    return (
      data?.matches.find(
        (match) => match.local_revid === localPick && match.remote_revid === remotePick
      ) ?? null
    );
  });

  function swatch(row: RevisionRow): string {
    if (!row.comparable_sha1 || !shared.has(row.comparable_sha1)) return '';
    return `swatch-${swatches.get(row.comparable_sha1)}`;
  }

  async function load(): Promise<void> {
    loading = true;
    error = '';
    try {
      data = await getPairRevisions(pairPk);
      const best = data.matches.find((match) => !match.linked) ?? data.matches[0];
      localPick = best?.local_revid ?? null;
      remotePick = best?.remote_revid ?? null;
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to load the revisions';
    } finally {
      loading = false;
    }
  }

  async function link(force: boolean): Promise<void> {
    if (localPick === null || remotePick === null) return;
    busy = true;
    error = '';
    message = '';
    try {
      await assertRung(pairPk, {
        local_revid: localPick,
        remote_revid: remotePick,
        origin: 'manual',
        force
      });
      message = `Linked ${localPick} ↔ ${remotePick}.`;
      await load();
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to link those revisions';
    } finally {
      busy = false;
    }
  }

  async function unlink(linkPk: number): Promise<void> {
    busy = true;
    error = '';
    message = '';
    try {
      await retractRung(linkPk);
      message = `Retracted rung ${linkPk}; the page pairing is kept.`;
      await load();
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to retract that rung';
    } finally {
      busy = false;
    }
  }

  function choose(match: RevisionMatch): void {
    localPick = match.local_revid;
    remotePick = match.remote_revid;
  }

  function when(row: RevisionRow): string {
    return row.timestamp ? row.timestamp.slice(0, 10) : '';
  }

  onMount(load);
</script>

{#if loading}
  <p class="state">Loading...</p>
{:else if data}
  <PageHeading eyebrow="Revision correspondence" title={data.local_title}>
    <p class="other">{data.remote_title}</p>
  </PageHeading>

  {#if error}
    <Notice>{error}</Notice>
  {/if}
  {#if message}
    <Notice kind="success">{message}</Notice>
  {/if}

  <section class="matches" aria-label="Matching revision pairs">
    <h2>Same content</h2>
    {#if data.matches.length === 0}
      <p class="state">
        No revision pair holds the same content.
        {#if !data.local_history_complete || !data.remote_history_complete}
          The history is incomplete on
          {#if !data.local_history_complete && !data.remote_history_complete}
            both sides
          {:else if !data.local_history_complete}
            this side
          {:else}
            the other side
          {/if}
          -- fetch more before concluding the pages never agreed.
        {:else}
          Both histories are complete back to the first revision, so these two pages
          were written independently. Nothing to link: reconciling them is an edit.
        {/if}
      </p>
    {:else}
      <ul class="match-list">
        {#each data.matches as match}
          <li>
            <button
              type="button"
              class:selected={picked === match}
              onclick={() => choose(match)}
            >
              <span class="pair">{match.local_revid} &harr; {match.remote_revid}</span>
              <small>
                {#if match.is_heads}
                  both heads -- nothing to replay
                {:else}
                  {match.local_ahead_by} local / {match.remote_ahead_by} remote revision(s)
                  newer
                {/if}
              </small>
            </button>
            {#if match.linked && match.link_pk}
              <ActionButton variant="ghost" disabled={busy} onclick={() => unlink(match.link_pk!)}>
                Retract
              </ActionButton>
            {:else}
              <span class="unlinked">not linked</span>
            {/if}
          </li>
        {/each}
      </ul>
    {/if}
  </section>

  <section class="link-bar" aria-label="Link a revision pair">
    <span class="chosen">
      {#if localPick !== null && remotePick !== null}
        {localPick} &harr; {remotePick}
      {:else}
        Pick one revision in each column
      {/if}
    </span>
    <ActionButton
      disabled={busy || localPick === null || remotePick === null || Boolean(picked?.linked)}
      onclick={() => link(false)}
    >
      Link these revisions
    </ActionButton>
    {#if localPick !== null && remotePick !== null && !picked}
      <span class="hint">
        These two do not hold the same content -- linking would make every later
        comparison lie.
        <button type="button" class="force" disabled={busy} onclick={() => link(true)}>
          Assert anyway
        </button>
      </span>
    {/if}
  </section>

  <section class="histories">
    <div class="history">
      <h2>{data.local_site}</h2>
      {#if !data.local_history_complete}
        <p class="incomplete">History incomplete -- older revisions exist that we do not hold.</p>
      {/if}
      <ul>
        {#each data.local as row}
          <li>
            <button
              type="button"
              class="revision {swatch(row)}"
              class:selected={localPick === row.revid}
              onclick={() => (localPick = row.revid)}
            >
              <span class="revid">
                {row.revid}
                {#if row.is_head}<em>head</em>{/if}
              </span>
              <span class="meta">
                {#if row.level !== null && row.level !== undefined}level {row.level}{/if}
                {#if row.user}&middot; {row.user}{/if}
                {#if when(row)}&middot; {when(row)}{/if}
              </span>
              {#if row.linked_to.length}
                <span class="linked">linked</span>
              {/if}
            </button>
          </li>
        {/each}
      </ul>
    </div>

    <div class="history">
      <h2>{data.remote_site}</h2>
      {#if !data.remote_history_complete}
        <p class="incomplete">History incomplete -- older revisions exist that we do not hold.</p>
      {/if}
      <ul>
        {#each data.remote as row}
          <li>
            <button
              type="button"
              class="revision {swatch(row)}"
              class:selected={remotePick === row.revid}
              onclick={() => (remotePick = row.revid)}
            >
              <span class="revid">
                {row.revid}
                {#if row.is_head}<em>head</em>{/if}
              </span>
              <span class="meta">
                {#if row.level !== null && row.level !== undefined}level {row.level}{/if}
                {#if row.user}&middot; {row.user}{/if}
                {#if when(row)}&middot; {when(row)}{/if}
              </span>
              {#if row.linked_to.length}
                <span class="linked">linked</span>
              {/if}
            </button>
          </li>
        {/each}
      </ul>
    </div>
  </section>

  <p class="legend">
    A coloured bar marks revisions whose content matches something on the other side --
    same words, same proofreading level, whoever is named in the pagequality tag.
  </p>
{:else}
  <Notice>{error || 'No such pairing.'}</Notice>
{/if}

<style>
  .state,
  .other {
    color: #73583d;
  }

  h2 {
    margin: 0 0 0.6rem;
    font-size: 1rem;
  }

  .matches {
    margin: 1.25rem 0;
  }

  .match-list {
    display: grid;
    gap: 0.5rem;
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .match-list li {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    gap: 0.75rem;
    align-items: center;
  }

  .match-list button {
    width: 100%;
    cursor: pointer;
    border: 1px solid rgba(87, 58, 37, 0.2);
    border-radius: 14px;
    background: rgba(255, 252, 240, 0.64);
    color: inherit;
    padding: 0.6rem 0.9rem;
    text-align: left;
  }

  .match-list button.selected {
    border-color: #9c5632;
    background: #fff7e6;
  }

  .pair {
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-weight: 700;
  }

  .match-list small {
    display: block;
    margin-top: 0.2rem;
    color: #73583d;
  }

  .unlinked {
    color: #7d5510;
    font-family: "Avenir Next", "Gill Sans", sans-serif;
    font-size: 0.74rem;
    text-transform: uppercase;
  }

  .link-bar {
    display: flex;
    flex-wrap: wrap;
    gap: 0.75rem 1rem;
    align-items: center;
    border-top: 1px solid rgba(72, 49, 31, 0.14);
    border-bottom: 1px solid rgba(72, 49, 31, 0.14);
    margin-bottom: 1.5rem;
    padding: 1rem 0;
  }

  .chosen {
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-weight: 700;
  }

  .hint {
    color: #7f2f22;
    font-size: 0.84rem;
  }

  .force {
    border: 0;
    background: none;
    color: #7f2f22;
    cursor: pointer;
    font: inherit;
    text-decoration: underline;
  }

  .histories {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: clamp(1rem, 3vw, 2rem);
  }

  .history ul {
    display: grid;
    gap: 0.4rem;
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .incomplete {
    color: #7d5510;
    font-size: 0.82rem;
  }

  .revision {
    display: grid;
    width: 100%;
    grid-template-columns: minmax(0, 1fr) auto;
    gap: 0.2rem 0.6rem;
    cursor: pointer;
    border: 1px solid rgba(87, 58, 37, 0.2);
    border-left: 6px solid transparent;
    border-radius: 12px;
    background: rgba(255, 252, 240, 0.64);
    color: inherit;
    padding: 0.55rem 0.8rem;
    text-align: left;
  }

  .revision.selected {
    border-color: #9c5632;
    background: #fff7e6;
  }

  .revid {
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-weight: 700;
  }

  .revid em {
    margin-left: 0.4rem;
    color: #9c5632;
    font-family: "Avenir Next", "Gill Sans", sans-serif;
    font-size: 0.68rem;
    font-style: normal;
    text-transform: uppercase;
  }

  .meta {
    grid-column: 1 / -1;
    color: #73583d;
    font-size: 0.78rem;
  }

  .linked {
    color: #24543f;
    font-family: "Avenir Next", "Gill Sans", sans-serif;
    font-size: 0.68rem;
    text-transform: uppercase;
  }

  /* Content-identity swatches. Hue only -- the border is the signal, and the
     row stays readable for anyone who cannot separate these colours. */
  .swatch-0 { border-left-color: #2f6f4f; }
  .swatch-1 { border-left-color: #9c5632; }
  .swatch-2 { border-left-color: #3d5f92; }
  .swatch-3 { border-left-color: #8a4f7d; }
  .swatch-4 { border-left-color: #6f7326; }
  .swatch-5 { border-left-color: #b0781a; }
  .swatch-6 { border-left-color: #2f6f6f; }
  .swatch-7 { border-left-color: #7f2f22; }

  .legend {
    margin-top: 1.25rem;
    color: #73583d;
    font-size: 0.84rem;
  }

  @media (max-width: 860px) {
    .histories {
      grid-template-columns: 1fr;
    }
  }
</style>
