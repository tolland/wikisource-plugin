<script lang="ts">
  import SelectField from '$lib/components/SelectField.svelte';
  import { siteLabel } from '$lib/format';
  import type { Site } from '$lib/types';

  let {
    sites,
    value = $bindable(null),
    label = 'Site',
    onchange
  }: {
    sites: Site[];
    value?: number | null;
    label?: string;
    onchange?: () => void;
  } = $props();
</script>

<SelectField {label} bind:value {onchange}>
  {#each sites as site}
    <option value={site.pk}>{siteLabel(site)}</option>
  {/each}
</SelectField>
