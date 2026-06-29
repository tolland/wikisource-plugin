<script>
  // Current path in the VFS tree (array of segments for breadcrumb)
  let pathParts = $state([]);
  let children = $state([]);
  let selectedFile = $state(null);  // { node, content }
  let loading = $state(false);
  let error = $state('');

  const VFS_BASE = '/api/vfs';

  function currentPath() {
    return pathParts.length === 0 ? '/' : '/' + pathParts.join('/');
  }

  async function navigate(parts) {
    loading = true;
    error = '';
    selectedFile = null;
    try {
      const path = parts.length === 0 ? '/' : '/' + parts.join('/');
      const res = await fetch(`${VFS_BASE}/children?path=${encodeURIComponent(path)}`);
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
      const data = await res.json();
      pathParts = parts;
      children = data.children;
    } catch (err) {
      error = err.message;
    } finally {
      loading = false;
    }
  }

  async function openFile(node) {
    if (node.kind === 'directory') {
      // Derive path parts from node.path
      const parts = node.path.replace(/^\//, '').split('/').filter(Boolean);
      await navigate(parts);
      return;
    }
    loading = true;
    error = '';
    selectedFile = null;
    try {
      const res = await fetch(`${VFS_BASE}/content?path=${encodeURIComponent(node.path)}`);
      if (!res.ok) {
        if (res.status === 501) {
          selectedFile = { node, content: '(binary blob — streaming not yet implemented)', stub: true };
          return;
        }
        throw new Error(`${res.status} ${res.statusText}`);
      }
      const data = await res.json();
      const content = atob(data.content_base64);
      selectedFile = { node, content, revid: data.revid };
    } catch (err) {
      error = err.message;
    } finally {
      loading = false;
    }
  }

  function breadcrumbParts() {
    // Returns [{label, parts}, ...] for each crumb
    const crumbs = [{ label: '/', parts: [] }];
    for (let i = 0; i < pathParts.length; i++) {
      crumbs.push({ label: pathParts[i], parts: pathParts.slice(0, i + 1) });
    }
    return crumbs;
  }

  // Kick off at root
  navigate([]);
</script>

<div class="vfs-shell">
  <div class="vfs-tree">
    <div class="tree-header">
      <p class="eyebrow">VFS browser</p>
      <nav class="breadcrumb" aria-label="Path">
        {#each breadcrumbParts() as crumb, i}
          {#if i > 0}<span class="sep">/</span>{/if}
          <button
            class="crumb"
            class:current={i === breadcrumbParts().length - 1}
            onclick={() => navigate(crumb.parts)}
          >{crumb.label}</button>
        {/each}
      </nav>
    </div>

    {#if error}
      <div class="notice">{error}</div>
    {/if}

    {#if loading}
      <p class="state">Loading…</p>
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
              class:active={selectedFile?.node?.path === node.path}
              onclick={() => openFile(node)}
            >
              <span class="icon">{node.kind === 'directory' ? '📁' : '📄'}</span>
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
  </div>

  <div class="vfs-content">
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
        <div class="wikitext" class:stub={selectedFile.stub}>{selectedFile.content}</div>
      </article>
    {:else if !loading}
      <div class="empty">Select a file to read its wikitext.</div>
    {/if}
  </div>
</div>

<style>
  .vfs-shell {
    display: grid;
    grid-template-columns: minmax(20rem, 32rem) minmax(0, 1fr);
    min-height: 100%;
  }

  .vfs-tree {
    border-right: 1px solid rgba(72, 49, 31, 0.22);
    background: rgba(255, 248, 230, 0.72);
    backdrop-filter: blur(10px);
    padding: 1.5rem;
    overflow-y: auto;
  }

  .tree-header {
    margin-bottom: 1.25rem;
  }

  .breadcrumb {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.1rem;
    margin-top: 0.5rem;
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

  .crumb:hover { text-decoration: underline; }
  .crumb.current { color: #241b13; cursor: default; font-weight: 600; }

  .sep { color: #73583d; user-select: none; }

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

  .node-btn:hover, .node-btn.active {
    border-color: #9c5632;
    background: #fff7e6;
    transform: translateY(-1px);
  }

  .icon { flex-shrink: 0; font-style: normal; }

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
    padding: clamp(1rem, 4vw, 4rem);
    overflow: auto;
  }

  .file-title {
    font-size: clamp(1rem, 2.5vw, 1.8rem);
    word-break: break-all;
    max-width: 100%;
  }

  .wikitext.stub {
    color: #73583d;
    font-style: italic;
  }

  @media (max-width: 860px) {
    .vfs-shell { grid-template-columns: 1fr; }
    .vfs-tree { border-right: 0; border-bottom: 1px solid rgba(72, 49, 31, 0.22); }
  }
</style>
