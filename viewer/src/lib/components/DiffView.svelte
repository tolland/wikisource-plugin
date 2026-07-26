<script lang="ts">
  import type { LineDiff } from '$lib/diff';

  let { diff }: { diff: LineDiff } = $props();
</script>

{#if diff.blocks.length === 0}
  <div class="empty">The submitted text is identical to the original.</div>
{:else}
  <div class="diff-blocks" aria-label="Staged wikitext diff">
    {#each diff.blocks as block}
      {#if block.skippedBefore > 0}
        <div class="diff-skip">
          {block.skippedBefore.toLocaleString()} unchanged line{block.skippedBefore === 1
            ? ''
            : 's'} hidden
        </div>
      {/if}
      <div class="diff-block">
        <div class="diff-block-header">
          @@ -{block.oldStart},{block.oldLines} +{block.newStart},{block.newLines} @@
        </div>
        <pre>{#each block.rows as row}<span class={row.kind}><span class="lineno">{row.oldNo ?? ''}</span><span class="lineno">{row.newNo ?? ''}</span><span class="marker">{row.kind === 'added' ? '+' : row.kind === 'removed' ? '-' : ' '}</span>{row.text || ' '}</span>{'\n'}{/each}</pre>
      </div>
    {/each}
  </div>
{/if}

<style>
  .diff-blocks {
    display: grid;
    gap: 0.6rem;
    margin-top: 0.75rem;
  }

  .diff-skip {
    color: #73583d;
    font-family: "Avenir Next", "Gill Sans", sans-serif;
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.05em;
    padding: 0.15rem 0.4rem;
    text-align: center;
    text-transform: uppercase;
  }

  .diff-block {
    border: 1px solid rgba(72, 49, 31, 0.14);
    border-radius: 12px;
    overflow: hidden;
  }

  .diff-block-header {
    background: #3a2c1f;
    color: #d8c6a8;
    font-family: "JetBrains Mono", "SFMono-Regular", Consolas, monospace;
    font-size: 0.76rem;
    padding: 0.45rem 1rem;
  }

  pre {
    width: 100%;
    max-height: 66vh;
    overflow: auto;
    background: #241b13;
    color: #fff8e6;
    font-family: "JetBrains Mono", "SFMono-Regular", Consolas, monospace;
    font-size: 0.86rem;
    line-height: 1.55;
    margin: 0;
    padding: 0.6rem 0;
    white-space: pre-wrap;
  }

  pre > span {
    display: block;
    min-height: 1.55em;
    padding: 0 1rem 0 0.4rem;
  }

  pre > span.added {
    background: rgba(64, 128, 90, 0.28);
    color: #a7f0ba;
  }

  pre > span.removed {
    background: rgba(150, 62, 40, 0.3);
    color: #ffb4a2;
  }

  .lineno {
    display: inline-block;
    width: 3.2em;
    color: rgba(255, 248, 230, 0.42);
    text-align: right;
    padding-right: 0.6em;
    user-select: none;
  }

  .marker {
    display: inline-block;
    width: 1.1em;
    user-select: none;
  }
</style>
