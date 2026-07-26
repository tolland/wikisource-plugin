<script lang="ts">
  import type { Snippet } from 'svelte';

  let { children }: { children: Snippet } = $props();
</script>

<div class="form-row">{@render children()}</div>

<style>
  .form-row {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 1rem;
  }

  @media (max-width: 680px) {
    .form-row {
      grid-template-columns: 1fr;
    }
  }
</style>
