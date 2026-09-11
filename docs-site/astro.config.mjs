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
  // ships to GitHub Pages. Add your own hostnames here if you develop on a VM.
  vite: {
    server: { allowedHosts: ['.googlers.com'] },
    preview: { allowedHosts: ['.googlers.com'] },
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
            { label: 'Voice playground', slug: 'voice-playground' },
          ],
        },
        {
          label: 'Concepts',
          items: [
            { label: 'Architecture', slug: 'architecture' },
            { label: 'Gemini Live configuration', slug: 'gemini-live-configuration' },
            { label: 'Audio engineering', slug: 'audio-engineering' },
            { label: 'Tools & function calling', slug: 'tools' },
            { label: 'Choosing a framework', slug: 'frameworks' },
          ],
        },
        {
          label: 'Operate',
          items: [
            { label: 'Deployment', slug: 'deployment' },
            { label: 'Diagnostics', slug: 'diagnostics' },
            { label: 'Latency & telemetry', slug: 'latency-and-telemetry' },
            { label: 'Troubleshooting', slug: 'troubleshooting' },
          ],
        },
      ],
    }),
  ],
});
