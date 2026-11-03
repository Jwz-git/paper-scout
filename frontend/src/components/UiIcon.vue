<template>
  <svg class="ui-icon" :data-icon="name" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">
    <path v-for="(path, index) in drawing.paths" :key="`path-${index}`" :d="path" />
    <circle v-for="(circle, index) in drawing.circles" :key="`circle-${index}`" :cx="circle[0]" :cy="circle[1]" :r="circle[2]" />
    <circle v-for="(dot, index) in drawing.dots" :key="`dot-${index}`" :cx="dot[0]" :cy="dot[1]" :r="dot[2]" fill="currentColor" stroke="none" />
  </svg>
</template>

<script setup lang="ts">
import { computed } from 'vue';

type Circle = readonly [x: number, y: number, radius: number];
interface IconDrawing { paths?: readonly string[]; circles?: readonly Circle[]; dots?: readonly Circle[]; }

// 24 × 24 网格，统一圆角描边。轮廓、圆和实心圆点分别绘制，避免拼接路径误连。
const icons = {
  // 论文页与放大镜：用于品牌和助手身份。
  scout: { paths: ['M12.5 3H5a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h6', 'M12.5 3 18 8.5V10M12.5 3v5.5H18', 'M7.5 12H10M7.5 15.5H9', 'm18.5 18.5 3 3'], circles: [[15.5, 15.5, 4.25]] },
  plus: { paths: ['M12 4.5v15M4.5 12h15'] },
  refresh: { paths: ['M20 9a8.2 8.2 0 0 0-13.7-3L3.5 9', 'M3.5 4v5h5', 'M4 15a8.2 8.2 0 0 0 13.7 3l2.8-3', 'M15.5 15h5v5'] },
  menu: { paths: ['M4 6.5h16M4 12h16M4 17.5h16'] },
  close: { paths: ['m6 6 12 12M18 6 6 18'] },
  documents: { paths: ['M8 3h8l4 4v12H8Z', 'M16 3v4h4', 'M4 7v14h12', 'M11 11h6M11 15h4'] },
  arrowUp: { paths: ['M12 20V4M5.5 10.5 12 4l6.5 6.5'] },
  arrowDown: { paths: ['M12 4v16M5.5 13.5 12 20l6.5-6.5'] },
  arrowRight: { paths: ['M4 12h16M13.5 5.5 20 12l-6.5 6.5'] },
  arrowLeft: { paths: ['M20 12H4M10.5 5.5 4 12l6.5 6.5'] },
  arrowUpRight: { paths: ['M6 18 18 6M6 6h12v12'] },
  chevronDown: { paths: ['m6 9 6 6 6-6'] },
  chevronRight: { paths: ['m9 6 6 6-6 6'] },
  search: { circles: [[10.5, 10.5, 6.5]], paths: ['m15.3 15.3 5.2 5.2'] },
  chat: { paths: ['M5.5 4.5h13a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H9l-5.5 3V6.5a2 2 0 0 1 2-2Z', 'M7.5 9h9M7.5 13h6'] },
  book: { paths: ['M12 5.5C9 3.8 6 3.5 3 4.5v15c3-1 6-.7 9 1 3-1.7 6-2 9-1v-15c-3-1-6-.7-9 1Z', 'M12 5.5v15'] },
  edit: { paths: ['m4 15.5 12-12a2.8 2.8 0 0 1 4 4l-12 12-4.5 1Z', 'm14 5.5 4 4M4 15.5l4 4'] },
  desktop: { paths: ['M4 4.5h16a1 1 0 0 1 1 1v11H3v-11a1 1 0 0 1 1-1Z', 'M8 20.5h8M12 16.5v4'] },
  model: { paths: ['M8 6h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2Z', 'M9.5 9.5h5v5h-5Z', 'M9 3v3M15 3v3M9 18v3M15 18v3M3 9h3M3 15h3M18 9h3M18 15h3'] },
  network: { paths: ['M9 3.5h6v5H9Z', 'M3.5 15.5h6v5h-6ZM14.5 15.5h6v5h-6Z', 'M12 8.5v4M6.5 15.5v-3h11v3'] },
  shield: { paths: ['M12 3 20 6v5.5c0 4.3-3.4 7.6-8 9.5-4.6-1.9-8-5.2-8-9.5V6Z', 'm8.5 11.8 2.3 2.3 4.7-4.7'] },
  key: { circles: [[8, 8, 4.5]], paths: ['m11.3 11.3 9.2 9.2M16 16l2-2M18.5 18.5l2-2'] },
  info: { circles: [[12, 12, 9]], paths: ['M12 11v6'], dots: [[12, 7.5, 1]] },
  process: { paths: ['M9 5h11M9 12h11M9 19h11'], dots: [[4, 5, 1.15], [4, 12, 1.15], [4, 19, 1.15]] },
  chart: { paths: ['M4 3.5v17h17M8 16v-4M13 16V8M18 16V4'] },
  clock: { circles: [[12, 12, 9]], paths: ['M12 6.5V12l4 2.5'] },
  settings: { paths: ['M3 6h4M11 6h10M3 12h10M17 12h4M3 18h4M11 18h10'], circles: [[9, 6, 2], [15, 12, 2], [9, 18, 2]] },
  layout: { paths: ['M4.5 3.5h15a1 1 0 0 1 1 1v15a1 1 0 0 1-1 1h-15a1 1 0 0 1-1-1v-15a1 1 0 0 1 1-1Z', 'M3.5 8.5h17M9 8.5v12'] },
  database: { paths: ['M4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6', 'M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3', 'M20 6c0 1.7-3.6 3-8 3S4 7.7 4 6s3.6-3 8-3 8 1.3 8 3Z'] },
  eye: { paths: ['M2.5 12c2.2-4.5 5.4-7 9.5-7s7.3 2.5 9.5 7c-2.2 4.5-5.4 7-9.5 7s-7.3-2.5-9.5-7Z'], circles: [[12, 12, 3]] },
  eyeOff: { paths: ['M3 3l18 18', 'M9.8 5.2A10 10 0 0 1 12 5c4.1 0 7.3 2.5 9.5 7a16 16 0 0 1-3 4', 'M6.2 6.2a17 17 0 0 0-3.7 5.8c2.2 4.5 5.4 7 9.5 7a10 10 0 0 0 5.8-1.8', 'M9.9 9.9a3 3 0 0 0 4.2 4.2'] },
  check: { paths: ['m4.5 12.5 5 5 10-11'] },
  more: { dots: [[5, 12, 1.4], [12, 12, 1.4], [19, 12, 1.4]] },
  trash: { paths: ['M3.5 6.5h17M9 6.5v-3h6v3', 'M5.5 6.5 6.5 21h11l1-14.5', 'M10 10.5v6.5M14 10.5v6.5'] },
  restore: { paths: ['M3.5 3.5v5h5', 'M3.5 8.5a8.5 8.5 0 1 1 0 7'] },
  copy: { paths: ['M9 8h11v13H9Z', 'M15 8V3H4v13h5'] },
  download: { paths: ['M12 3.5v12M7 10.5l5 5 5-5', 'M4 16.5v4h16v-4'] },
  sun: { circles: [[12, 12, 4]], paths: ['M12 2v2M12 20v2M2 12h2M20 12h2', 'm4.9 4.9 1.4 1.4m11.4 11.4 1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4'] },
  moon: { paths: ['M20.3 14.6A8.8 8.8 0 0 1 9.4 3.7a8.8 8.8 0 1 0 10.9 10.9Z'] },
} as const satisfies Record<string, IconDrawing>;

const props = defineProps<{ name: keyof typeof icons }>();
const drawing = computed<IconDrawing>(() => icons[props.name]);
</script>
