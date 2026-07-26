<script lang="ts">
  let {
    href,
    kicker,
    title,
    description
  }: {
    href: string;
    kicker: string;
    title: string;
    description: string;
  } = $props();
</script>

<a class="card" {href}>
  <span class="card-kicker">{kicker}</span>
  <strong>{title}</strong>
  <small>{description}</small>
</a>

<style>
  .card {
    border: 1px solid rgba(72, 49, 31, 0.18);
    border-radius: 24px;
    background: rgba(255, 252, 240, 0.68);
    box-shadow: 0 20px 60px rgba(62, 44, 30, 0.12);
    color: inherit;
    min-height: 10rem;
    padding: 1.3rem;
    text-decoration: none;
    transition: transform 160ms ease, border-color 160ms ease;
  }

  .card:hover {
    transform: translateY(-2px);
    border-color: #9c5632;
  }

  .card strong,
  .card small,
  .card-kicker {
    display: block;
  }

  .card strong {
    margin-top: 0.5rem;
    font-size: 1.45rem;
  }

  .card small {
    margin-top: 0.7rem;
    color: #73583d;
    line-height: 1.4;
  }

  .card-kicker {
    color: #9c5632;
    font-family: "Avenir Next", "Gill Sans", sans-serif;
    font-size: 0.72rem;
    font-weight: 800;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }
</style>
