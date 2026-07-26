<script lang="ts">
  import type { Snippet } from 'svelte';

  let {
    eyebrow,
    title,
    count = '',
    children
  }: {
    eyebrow: string;
    title: string;
    count?: string;
    children?: Snippet;
  } = $props();
</script>

<header class="page-heading">
  <p class="eyebrow">{eyebrow}</p>
  <h1>{title}</h1>
  {#if count}
    <p class="count">{count}</p>
  {/if}
  {@render children?.()}
</header>

<style>
  .page-heading {
    max-width: 64rem;
  }

  h1 {
    letter-spacing: -0.04em;
  }
</style>
