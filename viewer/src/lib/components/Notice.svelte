<script lang="ts">
  import type { Snippet } from 'svelte';

  let {
    kind = 'error',
    children
  }: {
    kind?: 'error' | 'success';
    children: Snippet;
  } = $props();
</script>

<div class="notice-box {kind}">{@render children()}</div>

<style>
  .notice-box {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem 1rem;
    border: 1px solid;
    border-radius: 16px;
    margin-bottom: 1rem;
    padding: 1rem;
  }

  .error {
    border-color: #b2452f;
    border-style: dashed;
    background: rgba(255, 252, 240, 0.5);
    color: #7f2f22;
  }

  .success {
    border-color: rgba(40, 107, 76, 0.34);
    background: rgba(229, 246, 235, 0.72);
    color: #24543f;
  }
</style>
