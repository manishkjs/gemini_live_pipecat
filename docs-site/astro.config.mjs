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
      head: [
        {
          tag: 'script',
          content: `
            (function () {
              const STORAGE_KEY = 'sl-left-sidebar-width';
              const MIN_W = 180;
              const MAX_W = 560;
              const saved = localStorage.getItem(STORAGE_KEY);
              if (saved) {
                const px = parseInt(saved, 10);
                if (!isNaN(px) && px >= MIN_W && px <= MAX_W) {
                  document.documentElement.style.setProperty('--sl-left-sidebar-width', px + 'px');
                }
              }
              function initSidebarResizer() {
                if (!document.documentElement.hasAttribute('data-has-sidebar')) return;
                if (document.querySelector('.sl-sidebar-resizer')) return;
                const handle = document.createElement('div');
                handle.className = 'sl-sidebar-resizer';
                handle.title = 'Drag to resize sidebar (double-click to reset)';
                handle.setAttribute('role', 'separator');
                handle.setAttribute('aria-orientation', 'vertical');
                handle.setAttribute('aria-label', 'Resize navigation sidebar');
                document.body.appendChild(handle);

                let dragging = false;
                handle.addEventListener('pointerdown', function (e) {
                  if (e.button !== 0) return;
                  dragging = true;
                  handle.classList.add('is-dragging');
                  document.body.classList.add('sl-resizing-sidebar');
                  handle.setPointerCapture(e.pointerId);
                  e.preventDefault();
                });

                handle.addEventListener('pointermove', function (e) {
                  if (!dragging) return;
                  const clamped = Math.max(MIN_W, Math.min(MAX_W, Math.round(e.clientX)));
                  document.documentElement.style.setProperty('--sl-left-sidebar-width', clamped + 'px');
                  try { localStorage.setItem(STORAGE_KEY, String(clamped)); } catch (_) {}
                });

                function stopDrag(e) {
                  if (!dragging) return;
                  dragging = false;
                  handle.classList.remove('is-dragging');
                  document.body.classList.remove('sl-resizing-sidebar');
                  try { handle.releasePointerCapture(e.pointerId); } catch (_) {}
                }
                handle.addEventListener('pointerup', stopDrag);
                handle.addEventListener('pointercancel', stopDrag);

                handle.addEventListener('dblclick', function () {
                  document.documentElement.style.removeProperty('--sl-left-sidebar-width');
                  try { localStorage.removeItem(STORAGE_KEY); } catch (_) {}
                });
              }
              if (document.readyState === 'loading') {
                document.addEventListener('DOMContentLoaded', initSidebarResizer);
              } else {
                initSidebarResizer();
              }
              document.addEventListener('astro:page-load', initSidebarResizer);
            })();
          `,
        },
      ],
      sidebar: [
        {
          label: 'Guides',
          items: [
            { label: 'Getting started', slug: 'getting-started' },
            { label: 'Gemini Live Skill', slug: 'gemini-live-skill' },
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
          label: 'Economics & Optimization',
          items: [
            { label: 'Telephony pricing & tokenomics', slug: 'pricing' },
            { label: 'Pricing calculator', slug: 'pricing-calculator' },
            { label: 'Optimization patterns', slug: 'optimization' },
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
