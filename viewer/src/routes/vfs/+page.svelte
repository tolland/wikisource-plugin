<script lang="ts">
  import { onMount } from 'svelte';
  import { listVfsChildren, readVfsContent } from '$lib/api';
  import WikitextViewer from '$lib/components/WikitextViewer.svelte';
  import type { VfsNode } from '$lib/types';

  interface SelectedFile {
    node: VfsNode;
    content: string;
    revid?: number | null;
    stub?: boolean;
  }

  let pathParts: string[] = $state([]);
  let children: VfsNode[] = $state([]);
  let selectedFile: SelectedFile | null = $state(null);
  let loading = $state(false);
  let error = $state('');

  function currentPath(): string {
    return pathParts.length === 0 ? '/' : `/${pathParts.join('/')}`;
  }

  function breadcrumbParts(): { label: string; parts: string[] }[] {
    const crumbs: { label: string; parts: string[] }[] = [{ label: '/', parts: [] }];
    for (let i = 0; i < pathParts.length; i += 1) {
      crumbs.push({ label: pathParts[i], parts: pathParts.slice(0, i + 1) });
    }
    return crumbs;
  }

  async function navigate(parts: string[]): Promise<void> {
    loading = true;
    error = '';
    selectedFile = null;
    try {
      const path = parts.length === 0 ? '/' : `/${parts.join('/')}`;
      const data = await listVfsChildren(path);
      pathParts = parts;
      children = data.children;
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to list VFS children';
    } finally {
      loading = false;
    }
  }

  async function openFile(node: VfsNode): Promise<void> {
    if (node.kind === 'directory') {
      const parts = node.path.replace(/^\//, '').split('/').filter(Boolean);
      await navigate(parts);
      return;
    }

    loading = true;
    error = '';
    selectedFile = null;
    try {
      const data = await readVfsContent(node.path);
      selectedFile = {
        node,
        content: atob(data.content_base64),
        revid: data.revid
      };
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to read VFS content';
      if (message.startsWith('501')) {
        selectedFile = {
          node,
          content: '(binary blob streaming is not implemented yet)',
          stub: true
        };
      } else {
        error = message;
      }
    } finally {
      loading = false;
    }
  }

  onMount(() => {
    void navigate([]);
  });
</script>

<section class="vfs-shell">
  <aside class="vfs-tree">
    <div class="tree-header">
      <p class="eyebrow">Editor projection</p>
      <h1>VFS</h1>
      <nav class="breadcrumb" aria-label="Path">
        {#each breadcrumbParts() as crumb, i}
          {#if i > 0}<span class="sep">/</span>{/if}
          <button
            class="crumb"
            class:current={i === breadcrumbParts().length - 1}
            onclick={() => navigate(crumb.parts)}
          >
            {crumb.label}
          </button>
        {/each}
      </nav>
    </div>

    {#if error}
      <div class="notice">{error}</div>
    {/if}

    {#if loading && !selectedFile}
      <p class="state">Loading {currentPath()}...</p>
    {:else if children.length === 0}
      <p class="state">Empty directory.</p>
    {:else}
      <ul class="node-list">
        {#each children as node}
          <li>
            <button
              class="node-btn"
              class:dir={node.kind === 'directory'}
              class:file={node.kind === 'file'}
              class:active={selectedFile?.node.path === node.path}
              onclick={() => openFile(node)}
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
    {/if}
  </aside>

  <section class="vfs-content">
    {#if selectedFile}
      <article>
        <header>
          <p class="eyebrow">{selectedFile.node.name}</p>
          <h2 class="file-title">{selectedFile.node.path}</h2>
          <div class="meta">
            {#if selectedFile.revid}
              <span>Revision {selectedFile.revid}</span>
            {/if}
            {#if selectedFile.node.length}
              <span>{selectedFile.node.length.toLocaleString()} bytes</span>
            {/if}
          </div>
        </header>
        <WikitextViewer content={selectedFile.content} stub={selectedFile.stub} />
      </article>
    {:else if !loading}
      <div class="empty">Select a file to read its wikitext.</div>
    {/if}
  </section>
</section>

<style>
  .vfs-shell {
    display: grid;
    grid-template-columns: minmax(20rem, 32rem) minmax(0, 1fr);
    gap: clamp(1rem, 3vw, 2rem);
  }

  .vfs-tree {
    border: 1px solid rgba(72, 49, 31, 0.18);
    border-radius: 24px;
    background: rgba(255, 248, 230, 0.72);
    padding: 1.4rem;
    overflow-y: auto;
  }

  .tree-header {
    margin-bottom: 1.25rem;
  }

  .tree-header h1 {
    font-size: clamp(2.6rem, 6vw, 4.75rem);
  }

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

  .vfs-content {
    min-width: 0;
  }

  .file-title {
    font-size: clamp(1rem, 2.5vw, 1.8rem);
    word-break: break-all;
    max-width: 100%;
  }

  header {
    margin-bottom: 1.5rem;
  }

  @media (max-width: 920px) {
    .vfs-shell {
      grid-template-columns: 1fr;
    }
  }
</style>
