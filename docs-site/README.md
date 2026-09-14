# Gemini Live — Developer Docs (Starlight)

Customer-facing documentation for building real-time voice agents on the Gemini
Live API. Built with [Astro](https://astro.build) + [Starlight](https://starlight.astro.build).

> **Isolation:** This site is intentionally decoupled from the application.
> It has its own `package.json`, imports nothing from `server/` or `client/`,
> is excluded from the Docker image and Cloud Build context (`.gcloudignore`,
> `.dockerignore`), and deploys **only** to GitHub Pages via
> `.github/workflows/docs.yml`. It never ships in your Cloud Run deploy.

## Local development

```bash
cd docs-site
npm ci
npm run dev      # http://localhost:4321/gemini_live_pipecat
npm run build    # outputs to docs-site/dist
npm run preview  # serve the production build locally
```

## Deployment (GitHub Pages)

Pushing to `ui-changes-sep` or `main` with changes under `docs-site/**` triggers
the Pages workflow. **One-time setup:** in the GitHub repo, go to
**Settings -> Pages -> Build and deployment -> Source** and select
**GitHub Actions**.

Published at: `https://manishkjs.github.io/gemini_live_pipecat/`

## Using a custom domain later

1. In `astro.config.mjs`, set `site` to your domain and `base` to `'/'`.
2. Add `docs-site/public/CNAME` containing the domain.
3. Update internal links from `/gemini_live_pipecat/...` to `/...`.

## Content

Pages live in `src/content/docs/`. Navigation is defined in `astro.config.mjs`.
Content is written for **external customers** — it deliberately omits any
Google-internal references.
