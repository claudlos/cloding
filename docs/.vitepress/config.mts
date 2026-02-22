import { defineConfig } from 'vitepress'

export default defineConfig({
  title: 'cloding',
  description: 'Run Claude Code with any OpenRouter model. Same tools, fraction of the cost.',
  base: '/cloding/',
  head: [
    ['link', { rel: 'icon', type: 'image/svg+xml', href: '/cloding/logo.svg' }],
    ['meta', { name: 'theme-color', content: '#10b981' }],
    ['meta', { property: 'og:title', content: 'cloding — Claude Code, any model' }],
    ['meta', { property: 'og:description', content: 'Run Claude Code with any OpenRouter model. Same tools, fraction of the cost.' }],
    ['meta', { property: 'og:type', content: 'website' }],
  ],
  cleanUrls: true,
  appearance: 'dark',
  lastUpdated: true,

  themeConfig: {
    logo: '/logo.svg',
    siteTitle: 'cloding',

    nav: [
      { text: 'Guide', link: '/introduction' },
      { text: 'GitHub', link: 'https://github.com/claudlos/cloding' }
    ],

    sidebar: [
      {
        text: 'Getting Started',
        items: [
          { text: 'Introduction', link: '/introduction' },
          { text: 'Installation', link: '/installation' },
          { text: 'Quick Start', link: '/quick-start' },
        ]
      },
      {
        text: 'Usage',
        items: [
          { text: 'Models & Pricing', link: '/models' },
          { text: 'Docker Mode', link: '/docker' },
          { text: 'Pipeline Mode', link: '/pipeline' },
          { text: 'Configuration', link: '/configuration' },
        ]
      },
      {
        text: 'Reference',
        items: [
          { text: 'CLI Reference', link: '/cli' },
          { text: 'Custom Models', link: '/custom-models' },
        ]
      }
    ],

    socialLinks: [
      { icon: 'github', link: 'https://github.com/claudlos/cloding' }
    ],

    editLink: {
      pattern: 'https://github.com/claudlos/cloding/edit/master/docs/:path',
      text: 'Edit this page on GitHub'
    },

    search: {
      provider: 'local'
    },

    footer: {
      message: 'Released under the MIT License.',
      copyright: '© 2025 cloding'
    }
  }
})
