<script lang="ts" generics="T">
  import type { Snippet } from 'svelte';

  let {
    label,
    value = $bindable(),
    onchange,
    children
  }: {
    label: string;
    value?: T;
    onchange?: () => void;
    children: Snippet;
  } = $props();
</script>

<label>
  <span>{label}</span>
  <select bind:value {onchange}>
    {@render children()}
  </select>
</label>

<style>
  label {
    display: grid;
    gap: 0.4rem;
  }

  span {
    color: #73583d;
    font-family: "Avenir Next", "Gill Sans", sans-serif;
    font-size: 0.74rem;
    font-weight: 800;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }

  select {
    width: 100%;
    border: 1px solid rgba(72, 49, 31, 0.24);
    border-radius: 12px;
    background: #fffdf5;
    color: #241b13;
    font: inherit;
    padding: 0.8rem 0.9rem;
  }
</style>
