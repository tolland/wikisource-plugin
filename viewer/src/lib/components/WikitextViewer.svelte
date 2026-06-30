<script lang="ts">
  let { content = '', stub = false }: { content?: string | null; stub?: boolean } = $props();
</script>

<div class="wikitext" class:stub>
  <pre>{content ?? ''}</pre>
</div>

<style>
  .wikitext {
    min-height: 55vh;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    border: 1px solid rgba(72, 49, 31, 0.18);
    border-radius: 24px;
    background: rgba(255, 252, 240, 0.82);
    box-shadow: 0 24px 70px rgba(62, 44, 30, 0.18);
    padding: clamp(1rem, 3vw, 2rem);
    font-family: "Berkeley Mono", "SFMono-Regular", Consolas, monospace;
    font-size: 0.95rem;
    line-height: 1.65;
  }

  .wikitext.stub {
    color: #73583d;
    font-style: italic;
  }

  pre {
    margin: 0;
    white-space: inherit;
    overflow-wrap: inherit;
    font: inherit;
  }
</style>
