<script lang="ts">
  import { onMount } from 'svelte';
  import { listVfsChildren, readVfsContent } from '$lib/api';
  import Notice from '$lib/components/Notice.svelte';
  import PageHeading from '$lib/components/PageHeading.svelte';
  import PathBreadcrumb from '$lib/components/PathBreadcrumb.svelte';
  import VfsNodeList from '$lib/components/VfsNodeList.svelte';
  import WikitextArticle from '$lib/components/WikitextArticle.svelte';
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
      <PageHeading eyebrow="Editor projection" title="VFS" />
      <PathBreadcrumb parts={pathParts} onnavigate={(parts) => void navigate(parts)} />
    </div>

    {#if error}
      <Notice>{error}</Notice>
    {/if}

    {#if loading && !selectedFile}
      <p class="state">Loading {currentPath()}...</p>
    {:else if children.length === 0}
      <p class="state">Empty directory.</p>
    {:else}
      <VfsNodeList
        nodes={children}
        selectedPath={selectedFile?.node.path ?? null}
        onopen={(node) => void openFile(node)}
      />
    {/if}
  </aside>

  <section class="vfs-content">
    {#if selectedFile}
      <WikitextArticle
        eyebrow={selectedFile.node.name}
        title={selectedFile.node.path}
        titleSize="compact"
        content={selectedFile.content}
        stub={selectedFile.stub}
      >
        {#snippet meta()}
          {#if selectedFile?.revid}
            <span>Revision {selectedFile.revid}</span>
          {/if}
          {#if selectedFile?.node.length}
            <span>{selectedFile.node.length.toLocaleString()} bytes</span>
          {/if}
        {/snippet}
      </WikitextArticle>
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

  .vfs-content {
    min-width: 0;
  }

  @media (max-width: 920px) {
    .vfs-shell {
      grid-template-columns: 1fr;
    }
  }
</style>
