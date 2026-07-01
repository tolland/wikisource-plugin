<script lang="ts">
  import '../app.css';
  import { page } from '$app/state';
  import type { Snippet } from 'svelte';

  let { children }: { children: Snippet } = $props();

  const navItems = [
    { href: '/', label: 'Workspace' },
    { href: '/sites', label: 'Sites' },
    { href: '/fetch', label: 'Fetch' },
    { href: '/commits', label: 'Commits' },
    { href: '/pages', label: 'Pages' },
    { href: '/indexes', label: 'Indexes' },
    { href: '/vfs', label: 'VFS' }
  ];

  function active(href: string): boolean {
    if (href === '/') return page.url.pathname === '/';
    return page.url.pathname.startsWith(href);
  }
</script>

<svelte:head>
  <title>Wikisource Local Editor</title>
</svelte:head>

<div class="app-shell">
  <aside class="rail">
    <a class="brand" href="/">
      <span class="brand-mark">WS</span>
      <span>
        <strong>Proofread cache</strong>
        <small>local editing workspace</small>
      </span>
    </a>

    <nav aria-label="Primary">
      {#each navItems as item}
        <a href={item.href} class:active={active(item.href)}>{item.label}</a>
      {/each}
    </nav>
  </aside>

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

  .rail {
    position: sticky;
    top: 0;
    align-self: start;
    min-height: 100vh;
    border-right: 1px solid rgba(72, 49, 31, 0.22);
    background: rgba(255, 248, 230, 0.78);
    backdrop-filter: blur(10px);
    padding: 1.4rem;
  }

  .brand {
    display: grid;
    grid-template-columns: 2.6rem minmax(0, 1fr);
    gap: 0.75rem;
    align-items: center;
    color: inherit;
    text-decoration: none;
  }

  .brand-mark {
    display: grid;
    width: 2.6rem;
    height: 2.6rem;
    place-items: center;
    border-radius: 999px;
    background: #9c5632;
    color: #fff8e6;
    font-family: "Avenir Next", "Gill Sans", sans-serif;
    font-size: 0.78rem;
    font-weight: 800;
    letter-spacing: 0.08em;
  }

  .brand strong,
  .brand small {
    display: block;
  }

  .brand small {
    margin-top: 0.16rem;
    color: #73583d;
    font-family: "Avenir Next", "Gill Sans", sans-serif;
    font-size: 0.74rem;
  }

  nav {
    display: grid;
    gap: 0.45rem;
    margin-top: 2rem;
  }

  nav a {
    border: 1px solid transparent;
    border-radius: 14px;
    color: #73583d;
    font-family: "Avenir Next", "Gill Sans", sans-serif;
    font-size: 0.82rem;
    font-weight: 700;
    letter-spacing: 0.06em;
    padding: 0.8rem 0.9rem;
    text-decoration: none;
    text-transform: uppercase;
  }

  nav a:hover,
  nav a.active {
    border-color: rgba(156, 86, 50, 0.38);
    background: rgba(255, 252, 240, 0.74);
    color: #9c5632;
  }

  .route-stage {
    min-width: 0;
    padding: clamp(1rem, 3vw, 3rem);
  }

  @media (max-width: 760px) {
    .app-shell {
      grid-template-columns: 1fr;
    }

    .rail {
      position: static;
      min-height: auto;
      border-right: 0;
      border-bottom: 1px solid rgba(72, 49, 31, 0.22);
    }

    nav {
      grid-template-columns: repeat(auto-fit, minmax(4.5rem, 1fr));
      gap: 0.35rem;
    }

    nav a {
      padding-inline: 0.5rem;
      text-align: center;
    }
  }
</style>
