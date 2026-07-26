<script lang="ts">
  import type { Snippet } from 'svelte';
  import WikitextViewer from '$lib/components/WikitextViewer.svelte';

  let {
    eyebrow,
    title,
    content,
    stub = false,
    titleSize = 'display',
    meta
  }: {
    eyebrow: string;
    title: string;
    content?: string | null;
    stub?: boolean;
    titleSize?: 'display' | 'compact';
    meta?: Snippet;
  } = $props();
</script>

<article>
  <header>
    <p class="eyebrow">{eyebrow}</p>
    <h2 class:compact={titleSize === 'compact'}>{title}</h2>
    {#if meta}
      <div class="meta">{@render meta()}</div>
    {/if}
  </header>
  <WikitextViewer {content} {stub} />
</article>

<style>
  article {
    animation: enter 260ms ease both;
  }

  header {
    margin-bottom: 1.5rem;
  }

  h2 {
    word-break: break-word;
  }

  h2.compact {
    font-size: clamp(1rem, 2.5vw, 1.8rem);
    word-break: break-all;
    max-width: 100%;
  }
</style>
