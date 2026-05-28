<template>
  <div class="markdown-body" v-html="html"></div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { renderMarkdown } from '../utils/markdown'

const props = defineProps<{
  source: string
}>()

const html = computed(() => renderMarkdown(props.source))
</script>

<style>
@import 'katex/dist/katex.min.css';

.markdown-body {
  font-size: var(--text-md);
  line-height: 1.75;
  color: var(--text-primary);
}
.markdown-body > *:first-child { margin-top: 0; }
.markdown-body > *:last-child { margin-bottom: 0; }

.markdown-body h1,
.markdown-body h2,
.markdown-body h3,
.markdown-body h4 {
  font-family: var(--font-display);
  font-weight: 700;
  line-height: 1.3;
  margin: var(--space-6) 0 var(--space-3);
  color: var(--text-primary);
}
.markdown-body h1 {
  font-size: var(--text-2xl);
  border-bottom: 2px solid var(--border-light);
  padding-bottom: var(--space-3);
}
.markdown-body h2 {
  font-size: var(--text-xl);
  border-left: 4px solid var(--accent-primary);
  padding-left: var(--space-3);
}
.markdown-body h3 {
  font-size: var(--text-lg);
  color: var(--text-secondary);
}
.markdown-body h4 {
  font-size: var(--text-base);
  color: var(--text-tertiary);
}

.markdown-body p {
  margin: var(--space-3) 0;
}

.markdown-body strong {
  font-weight: 700;
  color: var(--text-primary);
}
.markdown-body em {
  font-style: italic;
  color: var(--text-secondary);
}

.markdown-body ul,
.markdown-body ol {
  margin: var(--space-3) 0;
  padding-left: var(--space-6);
}
.markdown-body li {
  margin: var(--space-1) 0;
}
.markdown-body li::marker {
  color: var(--accent-primary);
}

.markdown-body table {
  width: 100%;
  border-collapse: collapse;
  margin: var(--space-4) 0;
  font-size: var(--text-sm);
  border-radius: var(--radius-md);
  overflow: hidden;
  box-shadow: var(--shadow-sm);
}
.markdown-body th {
  background: var(--bg-sidebar);
  font-weight: 600;
  text-align: left;
  padding: var(--space-3) var(--space-4);
  border-bottom: 2px solid var(--border-medium);
  color: var(--text-secondary);
}
.markdown-body td {
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--border-light);
}
.markdown-body tr:last-child td {
  border-bottom: none;
}
.markdown-body tr:nth-child(even) {
  background: var(--bg-base);
}

.markdown-body code {
  font-family: var(--font-mono);
  font-size: 0.88em;
  background: var(--bg-code);
  padding: 2px 6px;
  border-radius: 4px;
  color: #c44b4b;
}
.markdown-body pre {
  background: #2d2d2d;
  color: #f8f8f2;
  padding: var(--space-4);
  border-radius: var(--radius-md);
  overflow-x: auto;
  margin: var(--space-4) 0;
  font-size: var(--text-sm);
  line-height: 1.6;
}
.markdown-body pre code {
  background: transparent;
  color: inherit;
  padding: 0;
  border-radius: 0;
  font-size: inherit;
}

.markdown-body blockquote {
  margin: var(--space-4) 0;
  padding: var(--space-3) var(--space-5);
  border-left: 4px solid var(--accent-primary);
  background: var(--accent-primary-light);
  border-radius: 0 var(--radius-md) var(--radius-md) 0;
  color: var(--text-secondary);
  font-style: italic;
}

.markdown-body hr {
  border: none;
  height: 1px;
  background: linear-gradient(to right, transparent, var(--border-medium), transparent);
  margin: var(--space-6) 0;
}

.markdown-body a {
  color: var(--accent-primary);
  text-decoration: underline;
  text-underline-offset: 2px;
}

.markdown-body .katex {
  font-size: 1.05em;
}
.markdown-body .katex-display {
  margin: var(--space-4) 0;
  overflow-x: auto;
  padding: var(--space-2) 0;
}
.markdown-body .katex-error {
  color: var(--accent-danger);
  background: #fff0f0;
  padding: 2px 6px;
  border-radius: 4px;
  font-family: var(--font-mono);
  font-size: 0.9em;
}
</style>
