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
  // Allow the Cloudtop IDE proxy (*.proxy.googlers.com) and rangarok host to
  // reach the local dev/preview servers. Only affects local serving, never the
  // built static output that ships to GitHub Pages.
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
            { label: 'Tools & function calling', slug: 'tools' },
          ],
        },
        {
          label: 'Operate',
          items: [
            { label: 'Deployment', slug: 'deployment' },
            { label: 'Diagnostics', slug: 'diagnostics' },
            { label: 'Troubleshooting', slug: 'troubleshooting' },
          ],
        },
      ],
    }),
  ],
});
