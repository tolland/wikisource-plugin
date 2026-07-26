<script lang="ts">
  import type { Snippet } from 'svelte';

  let {
    variant = 'primary',
    type = 'button',
    disabled = false,
    onclick,
    children
  }: {
    variant?: 'primary' | 'secondary' | 'ghost' | 'approve' | 'danger';
    type?: 'button' | 'submit';
    disabled?: boolean;
    onclick?: () => void;
    children: Snippet;
  } = $props();
</script>

<button class={variant} {type} {disabled} {onclick}>{@render children()}</button>

<style>
  button {
    cursor: pointer;
    border: 0;
    border-radius: 12px;
    font-family: "Avenir Next", "Gill Sans", sans-serif;
    font-size: 0.78rem;
    font-weight: 800;
    letter-spacing: 0.06em;
    padding: 0.8rem 0.95rem;
    text-transform: uppercase;
    white-space: nowrap;
  }

  button:disabled {
    cursor: progress;
    opacity: 0.62;
  }

  .primary {
    background: #9c5632;
    color: #fff8e6;
  }

  .secondary {
    background: rgba(156, 86, 50, 0.12);
    color: #7d4428;
  }

  .ghost {
    border: 1px solid rgba(72, 49, 31, 0.24);
    background: rgba(255, 252, 240, 0.78);
    color: #73583d;
  }

  .approve {
    background: #286b4c;
    color: #fffdf5;
  }

  .danger {
    background: #7f2f22;
    color: #fff8e6;
  }
</style>
