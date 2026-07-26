<script lang="ts">
  import { formatDateTime } from '$lib/format';
  import type { PendingCommitJournal } from '$lib/types';

  let { journals }: { journals: PendingCommitJournal[] } = $props();
</script>

<section class="history">
  <p class="eyebrow">Local saves</p>
  <ol>
    {#each journals as journal}
      <li>
        <strong>#{journal.pk}</strong>
        <span>{formatDateTime(journal.saved_at)}</span>
        <span>#{journal.base_revid}</span>
        <small>{journal.body.length.toLocaleString()} chars</small>
      </li>
    {/each}
  </ol>
</section>

<style>
  .history {
    margin-top: 1.4rem;
  }

  ol {
    display: grid;
    gap: 0.45rem;
    list-style: none;
    margin: 0.7rem 0 0;
    padding: 0;
  }

  li {
    border-top: 1px solid rgba(72, 49, 31, 0.12);
    display: grid;
    grid-template-columns: 5rem minmax(0, 1fr) minmax(0, 1fr) auto;
    gap: 0.75rem;
    padding-top: 0.5rem;
  }

  li > :nth-child(2) {
    justify-self: start;
  }

  li > :nth-child(3) {
    justify-self: end;
  }

  span,
  small {
    color: #73583d;
    font-family: "Avenir Next", "Gill Sans", sans-serif;
    font-size: 0.76rem;
  }

  @media (max-width: 800px) {
    li {
      grid-template-columns: 1fr;
    }
  }
</style>
