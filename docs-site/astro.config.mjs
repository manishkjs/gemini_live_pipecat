// @ts-check
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';

// Deployed as a GitHub Pages *project* site:
//   https://manishkjs.github.io/gemini_live_pipecat/
// If you later move to a custom domain, set `site` to that domain,
// change `base` to '/', and add a `public/CNAME` file.
export default defineConfig({
  site: 'https://manishkjs.github.io',
  base: '/gemini_live_pipecat',
  // Allow remote dev hosts / IDE proxies to reach the local dev and preview
  // servers. Only affects local serving, never the built static output that
  // ships to GitHub Pages. Set DEV_ALLOWED_HOSTS (comma-separated) if you
  // develop on a remote VM behind a proxy; otherwise any host is allowed
  // locally, which is safe because this never touches the published site.
  vite: {
    server: { allowedHosts: process.env.DEV_ALLOWED_HOSTS?.split(',') ?? true },
    preview: { allowedHosts: process.env.DEV_ALLOWED_HOSTS?.split(',') ?? true },
  },
  integrations: [
    starlight({
      title: 'Gemini Live for Developers',
      description:
        'Build production-grade, low-latency, interruptible voice agents on the Gemini Live API.',
      social: [
        {
          icon: 'github',
          label: 'GitHub',
          href: 'https://github.com/manishkjs/gemini_live_pipecat',
        },
      ],
      customCss: ['./src/styles/custom.css'],
      sidebar: [
        {
          label: 'Guides',
          items: [
            { label: 'Getting started', slug: 'getting-started' },
            { label: 'Voice Studio', slug: 'voice-playground' },
          ],
        },
        {
          label: 'Concepts',
          items: [
            { label: 'Architecture', slug: 'architecture' },
            { label: 'Configuration reference', slug: 'gemini-live-configuration' },
            { label: 'Audio engineering', slug: 'audio-engineering' },
            { label: 'Tools & function calling', slug: 'tools' },
            { label: 'Choosing a framework', slug: 'frameworks' },
          ],
        },
        {
          label: 'Operate',
          items: [
            { label: 'Latency & telemetry', slug: 'latency-and-telemetry' },
            { label: 'Optimization patterns', slug: 'optimization' },
            { label: 'Deployment', slug: 'deployment' },
            { label: 'Troubleshooting', slug: 'troubleshooting' },
          ],
        },
      ],
    }),
  ],
});
