<script lang="ts">
  import type { VfsNode } from '$lib/types';

  let {
    nodes,
    selectedPath = null,
    onopen
  }: {
    nodes: VfsNode[];
    selectedPath?: string | null;
    onopen: (node: VfsNode) => void;
  } = $props();
</script>

<ul class="node-list">
  {#each nodes as node}
    <li>
      <button
        class="node-btn"
        class:active={selectedPath === node.path}
        onclick={() => onopen(node)}
      >
        <span class="icon">{node.kind === 'directory' ? 'DIR' : 'WT'}</span>
        <span class="node-name">{node.name}</span>
        {#if node.kind === 'file' && node.length != null}
          <small class="node-meta">{node.length.toLocaleString()} B</small>
        {/if}
        {#if node.revid}
          <small class="node-meta">r{node.revid}</small>
        {/if}
      </button>
    </li>
  {/each}
</ul>

<style>
  .node-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: 0.4rem;
  }

  .node-btn {
    width: 100%;
    display: flex;
    align-items: baseline;
    gap: 0.5rem;
    cursor: pointer;
    border: 1px solid rgba(87, 58, 37, 0.18);
    border-radius: 12px;
    background: rgba(255, 252, 240, 0.6);
    color: inherit;
    padding: 0.65rem 0.9rem;
    text-align: left;
    font: inherit;
    transition: border-color 120ms, background 120ms, transform 120ms;
  }

  .node-btn:hover,
  .node-btn.active {
    border-color: #9c5632;
    background: #fff7e6;
    transform: translateY(-1px);
  }

  .icon {
    flex-shrink: 0;
    color: #9c5632;
    font-family: "Avenir Next", "Gill Sans", sans-serif;
    font-size: 0.68rem;
    font-weight: 900;
    letter-spacing: 0.08em;
  }

  .node-name {
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-weight: 600;
    font-size: 0.88rem;
  }

  .node-meta {
    flex-shrink: 0;
    color: #73583d;
    font-family: "Avenir Next", "Gill Sans", sans-serif;
    font-size: 0.7rem;
  }
</style>
