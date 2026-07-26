<script lang="ts">
  import { onMount } from 'svelte';
  import {
    createSite,
    deleteSiteCredential,
    getSiteCredential,
    listSites,
    saveSiteCredential,
    updateSite
  } from '$lib/api';
  import ActionButton from '$lib/components/ActionButton.svelte';
  import FormRow from '$lib/components/FormRow.svelte';
  import Notice from '$lib/components/Notice.svelte';
  import PageHeading from '$lib/components/PageHeading.svelte';
  import TextField from '$lib/components/TextField.svelte';
  import { siteLabel } from '$lib/format';
  import type { CredentialPayload, Site, SiteCredential, SitePayload } from '$lib/types';

  let sites: Site[] = $state([]);
  let selectedSitePk: number | 'new' = $state('new');
  let loading = $state(true);
  let savingSite = $state(false);
  let savingCredential = $state(false);
  let deletingCredential = $state(false);
  let error = $state('');
  let message = $state('');
  let credential: SiteCredential | null = $state(null);
  let loadingCredential = $state(false);

  let siteForm: SitePayload = $state(blankSite());
  let credentialForm: CredentialPayload = $state(blankCredential());

  function blankSite(): SitePayload {
    return {
      family: 'wikisource',
      code: 'en',
      articlepath: '/wiki/$1',
      host: '',
      api_url: '',
      label: ''
    };
  }

  function blankCredential(): CredentialPayload {
    return {
      username: '',
      password: '',
      bot_name: ''
    };
  }

  function payloadFromForm(): SitePayload {
    return {
      family: siteForm.family.trim(),
      code: siteForm.code.trim(),
      articlepath: siteForm.articlepath?.trim() || '/wiki/$1',
      host: siteForm.host?.trim() || null,
      api_url: siteForm.api_url?.trim() || null,
      label: siteForm.label?.trim() || null
    };
  }

  function credentialPayloadFromForm(): CredentialPayload {
    return {
      username: credentialForm.username.trim(),
      password: credentialForm.password,
      bot_name: credentialForm.bot_name?.trim() || null
    };
  }

  function selectNew(): void {
    selectedSitePk = 'new';
    siteForm = blankSite();
    credential = null;
    credentialForm = blankCredential();
    message = '';
    error = '';
  }

  async function selectSite(site: Site): Promise<void> {
    selectedSitePk = site.pk;
    siteForm = {
      family: site.family,
      code: site.code,
      articlepath: site.articlepath ?? '/wiki/$1',
      host: site.host ?? '',
      api_url: site.api_url ?? '',
      label: site.label ?? ''
    };
    message = '';
    error = '';
    await loadCredential(site.pk);
  }

  async function loadSites(): Promise<void> {
    loading = true;
    error = '';
    try {
      sites = await listSites();
      if (sites.length > 0) {
        await selectSite(sites[0]);
      } else {
        selectNew();
      }
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to load sites';
    } finally {
      loading = false;
    }
  }

  async function loadCredential(sitePk: number): Promise<void> {
    loadingCredential = true;
    try {
      credential = await getSiteCredential(sitePk);
      credentialForm = credential
        ? {
            username: credential.username,
            password: credential.password,
            bot_name: credential.bot_name ?? ''
          }
        : blankCredential();
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to load credential';
    } finally {
      loadingCredential = false;
    }
  }

  async function submitSite(): Promise<void> {
    savingSite = true;
    error = '';
    message = '';
    try {
      const payload = payloadFromForm();
      const creating = selectedSitePk === 'new';
      const saved =
        selectedSitePk === 'new' ? await createSite(payload) : await updateSite(selectedSitePk, payload);
      sites = await listSites();
      await selectSite(saved);
      message = creating ? 'Site added.' : 'Site saved.';
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to save site';
    } finally {
      savingSite = false;
    }
  }

  async function submitCredential(): Promise<void> {
    if (selectedSitePk === 'new') return;
    savingCredential = true;
    error = '';
    message = '';
    try {
      credential = await saveSiteCredential(selectedSitePk, credentialPayloadFromForm());
      credentialForm = {
        username: credential.username,
        password: credential.password,
        bot_name: credential.bot_name ?? ''
      };
      message = 'Credential saved.';
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to save credential';
    } finally {
      savingCredential = false;
    }
  }

  async function removeCredential(): Promise<void> {
    if (selectedSitePk === 'new') return;
    deletingCredential = true;
    error = '';
    message = '';
    try {
      await deleteSiteCredential(selectedSitePk);
      credential = null;
      credentialForm = blankCredential();
      message = 'Credential removed.';
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to remove credential';
    } finally {
      deletingCredential = false;
    }
  }

  onMount(loadSites);
</script>

<section class="sites-workspace">
  <aside class="site-browser" aria-label="Configured sites">
    <PageHeading
      eyebrow="Configuration"
      title="Sites"
      count={loading ? 'Loading' : `${sites.length} configured`}
    />

    <div class="new-site">
      <ActionButton onclick={selectNew}>New site</ActionButton>
    </div>

    {#if loading}
      <p class="state">Loading sites...</p>
    {:else if sites.length === 0}
      <p class="state">No sites configured.</p>
    {:else}
      <nav class="site-list" aria-label="Sites">
        {#each sites as site}
          <button
            type="button"
            class:active={selectedSitePk === site.pk}
            onclick={() => selectSite(site)}
          >
            <span>{siteLabel(site)}</span>
            <small>{site.api_url ?? site.host ?? `${site.family}:${site.code}`}</small>
          </button>
        {/each}
      </nav>
    {/if}
  </aside>

  <section class="editor-pane">
    {#if error}
      <Notice>{error}</Notice>
    {/if}
    {#if message}
      <Notice kind="success">{message}</Notice>
    {/if}

    <form
      class="panel"
      onsubmit={(event) => {
        event.preventDefault();
        void submitSite();
      }}
    >
      <header>
        <p class="eyebrow">{selectedSitePk === 'new' ? 'New site' : `Site ${selectedSitePk}`}</p>
        <h2>{selectedSitePk === 'new' ? 'Add a wiki.' : siteForm.label || `${siteForm.family}:${siteForm.code}`}</h2>
      </header>

      <FormRow>
        <TextField label="Family" bind:value={siteForm.family} required placeholder="wikisource" />
        <TextField label="Code" bind:value={siteForm.code} required placeholder="en" />
      </FormRow>

      <TextField label="Label" bind:value={siteForm.label} placeholder="Local Wikisource" />

      <TextField
        label="API URL"
        bind:value={siteForm.api_url}
        placeholder="https://en.wikisource.org/w/api.php"
      />

      <FormRow>
        <TextField label="Host" bind:value={siteForm.host} placeholder="en.wikisource.org" />
        <TextField
          label="Article path"
          bind:value={siteForm.articlepath}
          required
          placeholder="/wiki/$1"
        />
      </FormRow>

      <div class="actions">
        <ActionButton type="submit" disabled={savingSite}>
          {savingSite ? 'Saving...' : selectedSitePk === 'new' ? 'Add site' : 'Save site'}
        </ActionButton>
      </div>
    </form>

    {#if selectedSitePk !== 'new'}
      <form
        class="panel"
        onsubmit={(event) => {
          event.preventDefault();
          void submitCredential();
        }}
      >
        <header>
          <p class="eyebrow">Login</p>
          <h2>Site credential</h2>
          <p class="description">
            {loadingCredential
              ? 'Loading credential...'
              : credential
                ? `Configured for ${credential.username}`
                : 'No credential configured.'}
          </p>
        </header>

        <TextField
          label="Username"
          bind:value={credentialForm.username}
          required
          autocomplete="username"
        />

        <FormRow>
          <TextField
            label="Password"
            bind:value={credentialForm.password}
            required
            type="password"
            autocomplete="current-password"
          />
          <TextField
            label="Bot password suffix"
            bind:value={credentialForm.bot_name}
            placeholder="wtbot"
          />
        </FormRow>

        <div class="actions">
          <ActionButton type="submit" disabled={savingCredential || loadingCredential}>
            {savingCredential ? 'Saving...' : 'Save credential'}
          </ActionButton>
          {#if credential}
            <ActionButton
              variant="secondary"
              onclick={() => void removeCredential()}
              disabled={deletingCredential}
            >
              {deletingCredential ? 'Removing...' : 'Remove credential'}
            </ActionButton>
          {/if}
        </div>
      </form>
    {/if}
  </section>
</section>

<style>
  .sites-workspace {
    display: grid;
    grid-template-columns: minmax(18rem, 28rem) minmax(0, 1fr);
    gap: clamp(1rem, 3vw, 2rem);
  }

  .site-browser,
  .panel {
    border: 1px solid rgba(72, 49, 31, 0.18);
    border-radius: 16px;
    background: rgba(255, 252, 240, 0.72);
    box-shadow: 0 16px 44px rgba(62, 44, 30, 0.1);
  }

  .site-browser {
    align-self: start;
    padding: 1.2rem;
  }

  .new-site {
    display: grid;
    margin: 1rem 0;
  }

  .site-list {
    display: grid;
    gap: 0.5rem;
  }

  .site-list button {
    cursor: pointer;
    border: 1px solid rgba(72, 49, 31, 0.14);
    border-radius: 12px;
    background: rgba(255, 253, 245, 0.7);
    color: inherit;
    display: grid;
    gap: 0.35rem;
    padding: 0.85rem;
    text-align: left;
  }

  .site-list button.active,
  .site-list button:hover {
    border-color: rgba(156, 86, 50, 0.52);
    background: #fffdf5;
  }

  .site-list span {
    font-weight: 800;
    line-height: 1.25;
  }

  .site-list small,
  .description {
    color: #73583d;
    font-family: "Avenir Next", "Gill Sans", sans-serif;
    font-size: 0.78rem;
  }

  .editor-pane {
    display: grid;
    gap: 1rem;
    min-width: 0;
  }

  .panel {
    display: grid;
    gap: 1rem;
    padding: 1.2rem;
  }

  .panel h2 {
    font-size: clamp(1.7rem, 3vw, 3.2rem);
    overflow-wrap: anywhere;
  }

  .actions {
    display: flex;
    flex-wrap: wrap;
    gap: 0.75rem;
  }

  @media (max-width: 900px) {
    .sites-workspace {
      grid-template-columns: 1fr;
    }
  }
</style>
