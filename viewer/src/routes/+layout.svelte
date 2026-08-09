<script lang="ts">
  import '../app.css';
  import type { Snippet } from 'svelte';
  import NavRail from '$lib/components/NavRail.svelte';

  let { children }: { children: Snippet } = $props();

  const navItems = [
    { href: '/', label: 'Workspace' },
    { href: '/sites', label: 'Sites' },
    { href: '/fetch', label: 'Fetch' },
    { href: '/commits', label: 'Commits' },
    { href: '/pages', label: 'Pages' },
    { href: '/indexes', label: 'Indexes' },
    { href: '/links', label: 'Links' },
    { href: '/locator-index', label: 'Locator index' },
    { href: '/sync', label: 'Sync' },
    { href: '/vfs', label: 'VFS' }
  ];
</script>

<svelte:head>
  <title>Wikisource Local Editor</title>
</svelte:head>

<div class="app-shell">
  <NavRail items={navItems} />

  <main class="route-stage">
    {@render children?.()}
  </main>
</div>

<style>
  .app-shell {
    display: grid;
    grid-template-columns: 17rem minmax(0, 1fr);
    min-height: 100vh;
  }

  .route-stage {
    min-width: 0;
    padding: clamp(1rem, 3vw, 3rem);
  }

  @media (max-width: 760px) {
    .app-shell {
      grid-template-columns: 1fr;
    }
  }
</style>
