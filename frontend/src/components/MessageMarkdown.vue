<template>
  <div class="message-markdown" v-html="rendered"></div>
</template>

<script lang="ts">
import MarkdownIt from 'markdown-it';

// 模型文本不允许执行HTML或自动加载远端图片；引用仍由独立的证据按钮打开。
const markdown = new MarkdownIt({ html: false, linkify: false, breaks: true }).disable('image');
markdown.renderer.rules.link_open = (tokens, index, options, _env, renderer) => {
  tokens[index].attrSet('target', '_blank');
  tokens[index].attrSet('rel', 'noopener noreferrer');
  return renderer.renderToken(tokens, index, options);
};
</script>

<script setup lang="ts">
import { computed } from 'vue';

const props = defineProps<{ content: string }>();
const rendered = computed(() => markdown.render(props.content));
</script>
