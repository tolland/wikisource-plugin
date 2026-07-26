<script lang="ts">
  let {
    parts,
    onnavigate
  }: {
    parts: string[];
    onnavigate: (parts: string[]) => void;
  } = $props();

  const crumbs = $derived.by(() => {
    const items: { label: string; parts: string[] }[] = [{ label: '/', parts: [] }];
    for (let i = 0; i < parts.length; i += 1) {
      items.push({ label: parts[i], parts: parts.slice(0, i + 1) });
    }
    return items;
  });
</script>

<nav class="breadcrumb" aria-label="Path">
  {#each crumbs as crumb, i}
    {#if i > 0}<span class="sep">/</span>{/if}
    <button
      class="crumb"
      class:current={i === crumbs.length - 1}
      onclick={() => onnavigate(crumb.parts)}
    >
      {crumb.label}
    </button>
  {/each}
</nav>

<style>
  .breadcrumb {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.1rem;
    margin-top: 0.8rem;
    font-family: "Berkeley Mono", "SFMono-Regular", Consolas, monospace;
    font-size: 0.8rem;
  }

  .crumb {
    background: none;
    border: none;
    cursor: pointer;
    color: #9c5632;
    padding: 0.1rem 0.2rem;
    border-radius: 4px;
    font: inherit;
    max-width: 14rem;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .crumb:hover {
    text-decoration: underline;
  }

  .crumb.current {
    color: #241b13;
    cursor: default;
    font-weight: 600;
  }

  .sep {
    color: #73583d;
    user-select: none;
  }
</style>
