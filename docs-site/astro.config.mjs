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
      head: [
        {
          tag: 'script',
          attrs: {
            src: '/gemini_live_pipecat/sidebar-resizer.js',
            defer: true,
          },
        },
      ],
      sidebar: [
        {
          label: 'Guides',
          items: [
            { label: 'Getting started', slug: 'getting-started' },
            { label: 'Voice Studio', slug: 'voice-playground' },
            { label: 'Gemini Live Skill', slug: 'gemini-live-skill' },
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
          label: 'Economics & Optimization',
          items: [
            { label: 'Telephony pricing & tokenomics', slug: 'pricing' },
            { label: 'Pricing calculator', slug: 'pricing-calculator' },
            {
              label: 'Optimization patterns',
              items: [
                { label: 'Overview (All 4 Pillars)', slug: 'optimization' },
                { label: 'Pillar 1: Sliding window', slug: 'optimization/sliding-window' },
                { label: 'Pillar 2: Prompt cards & tools', slug: 'optimization/prompt-cards' },
                { label: 'Pillar 3: Lossless fact pruning', slug: 'optimization/history-pruning' },
                { label: 'Pillar 4: Cached TTS', slug: 'optimization/cached-tts' },
              ],
            },
            { label: 'Prompt optimization', slug: 'prompt-optimization' },
          ],
        },
        {
          label: 'Operate',
          items: [
            { label: 'Latency & telemetry', slug: 'latency-and-telemetry' },
            { label: 'Deployment', slug: 'deployment' },
            { label: 'Troubleshooting', slug: 'troubleshooting' },
          ],
        },
      ],
    }),
  ],
});
