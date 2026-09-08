<template>
  <svg
    class="nr-ui-icon"
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.7"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <path v-for="(d, i) in paths" :key="i" :d="d" />
    <circle v-for="(c, i) in circles" :key="'c' + i" :cx="c[0]" :cy="c[1]" :r="c[2]" />
    <rect v-for="(r, i) in rects" :key="'r' + i" :x="r[0]" :y="r[1]" :width="r[2]" :height="r[3]" :rx="r[4]" />
    <line v-for="(l, i) in lines" :key="'l' + i" :x1="l[0]" :y1="l[1]" :x2="l[2]" :y2="l[3]" />
  </svg>
</template>

<script setup lang="ts">
/**
 * 统一线描 UI 图标（2026-09-08 全页图标统一）。
 *
 * 替代散落的 emoji（💬📄🗂🌐 等），与 composer 既有 nr-ico 24×24 stroke
 * 体系同风格：stroke=currentColor 继承文字色，linecap/linejoin 圆角。
 * 每个图标 = paths/circles/rects/lines 的声明式组合，单文件零依赖。
 *
 * 新增图标：在 ICON_SHAPES 加条目即可（形状数据来自 24×24 网格手绘）。
 */
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    name: string
    size?: number
  }>(),
  { size: 16 },
)

interface IconShape {
  paths?: string[]
  circles?: Array<[number, number, number]>
  rects?: Array<[number, number, number, number, number]>
  lines?: Array<[number, number, number, number]>
}

const ICON_SHAPES: Record<string, IconShape> = {
  // 会话气泡
  chat: {
    paths: ['M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z'],
  },
  // 置顶图钉
  pin: {
    paths: ['M12 17v5', 'M9 10.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V7h1a2 2 0 0 0 0-4H8a2 2 0 0 0 0 4h1z'],
  },
  // 存档箱
  archive: {
    rects: [[3, 4, 18, 4, 1]],
    paths: ['M5 8v11a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8', 'M10 12h4'],
  },
  // 全局/跨会话搜索
  globe: {
    circles: [[12, 12, 9]],
    paths: ['M3 12h18', 'M12 3a15.3 15.3 0 0 1 0 18 15.3 15.3 0 0 1 0-18z'],
  },
  // 搜索
  search: {
    circles: [[11, 11, 7]],
    paths: ['m21 21-4.35-4.35'],
  },
  // Markdown 文档
  fileText: {
    paths: ['M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z', 'M14 2v6h6', 'M9 13h6', 'M9 17h6'],
  },
  // HTML/浏览器窗口
  browser: {
    rects: [[3, 4, 18, 16, 2]],
    lines: [[3, 9, 21, 9], [7, 6.5, 7, 6.5], [10, 6.5, 10, 6.5]],
  },
  // 图片
  image: {
    rects: [[3, 3, 18, 18, 2]],
    circles: [[8.5, 8.5, 1.5]],
    paths: ['m21 15-5-5L5 21'],
  },
  // 音频
  audio: {
    paths: ['M11 5 6 9H2v6h4l5 4z', 'M15.54 8.46a5 5 0 0 1 0 7.07', 'M19.07 4.93a10 10 0 0 1 0 14.14'],
  },
  // 文本
  file: {
    paths: ['M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z', 'M14 2v6h6'],
  },
  // 电脑/显示器
  monitor: {
    rects: [[2, 3, 20, 14, 2]],
    paths: ['M8 21h8', 'M12 17v4'],
  },
  // 大脑/推理
  brain: {
    paths: ['M9.5 2A2.5 2.5 0 0 1 12 4.5v15a2.5 2.5 0 0 1-4.96.44 2.5 2.5 0 0 1-2.96-3.08 3 3 0 0 1-.34-5.58 2.5 2.5 0 0 1 1.32-4.24 2.5 2.5 0 0 1 4.44-2.04z', 'M14.5 2A2.5 2.5 0 0 0 12 4.5v15a2.5 2.5 0 0 0 4.96.44 2.5 2.5 0 0 0 2.96-3.08 3 3 0 0 0 .34-5.58 2.5 2.5 0 0 0-1.32-4.24 2.5 2.5 0 0 0-4.44-2.04z'],
  },
  // 文件夹
  folder: {
    paths: ['M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z'],
  },
  // 键盘/shell
  keyboard: {
    rects: [[2, 5, 20, 14, 2]],
    lines: [[6, 9, 6, 9], [10, 9, 10, 9], [14, 9, 14, 9], [18, 9, 18, 9], [6, 13, 6, 13], [18, 13, 18, 13], [8, 15.5, 16, 15.5]],
  },
  // 代码
  code: {
    paths: ['m16 18 6-6-6-6', 'm8 6-6 6 6 6'],
  },
  // 扳手/通用工具
  wrench: {
    paths: ['M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z'],
  },
  // 下载箭头（发送/提交）
  send: {
    paths: ['m22 2-7 20-4-9-9-4z', 'M22 2 11 13'],
  },
  // 方块（停止）
  stop: {
    rects: [[6, 6, 12, 12, 2]],
  },
  // 对勾（确认）
  check: {
    paths: ['M20 6 9 17l-5-5'],
  },
  // 上箭头（发送）
  arrowUp: {
    paths: ['M12 19V5', 'm5 12 7-7 7 7'],
  },
  // 复制
  copy: {
    rects: [[9, 9, 13, 13, 2]],
    paths: ['M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1'],
  },
  // 重新生成
  refresh: {
    paths: ['M23 4v6h-6', 'M1 20v-6h6', 'M3.51 9a9 9 0 0 1 14.85-3.36L23 10', 'M1 14l4.64 4.36A9 9 0 0 0 20.49 15'],
  },
  // 点赞
  like: {
    paths: ['M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3'],
  },
  // 点踩
  dislike: {
    paths: ['M10 15v4a3 3 0 0 0 3 3l4-9V2H5.72a2 2 0 0 0-2 1.7l-1.38 9a2 2 0 0 0 2 2.3zm7-13h2.67A2.31 2.31 0 0 1 22 4v7a2.31 2.31 0 0 1-2.33 2H17'],
  },
  // 分叉
  fork: {
    circles: [[12, 18, 2.5], [6, 6, 2.5], [18, 6, 2.5]],
    paths: ['M6 8.5v3a4 4 0 0 0 4 4h4a4 4 0 0 0 4-4v-3', 'M12 15.5V12'],
  },
  // 锚点/checkpoint
  anchor: {
    circles: [[12, 5, 2.5]],
    paths: ['M12 22a8 8 0 0 0 8-8', 'M12 22a8 8 0 0 1-8-8', 'M12 7.5V22', 'M4 14h16'],
  },
  // 编辑
  edit: {
    paths: ['M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5z'],
  },
  // 删除
  trash: {
    paths: ['M3 6h18', 'M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6', 'M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2', 'M10 11v6', 'M14 11v6'],
  },
  // 加号/上传
  plus: {
    paths: ['M12 5v14', 'M5 12h14'],
  },
  // 麦克风
  mic: {
    rects: [[9, 2, 6, 12, 3]],
    paths: ['M5 10v2a7 7 0 0 0 14 0v-2', 'M12 19v3'],
  },
  // 音量（自动语音开）
  volume: {
    paths: ['M11 5 6 9H2v6h4l5 4z', 'M15.5 8.5a5 5 0 0 1 0 7', 'M18.5 5.5a9 9 0 0 1 0 13'],
  },
  // 静音（自动语音关）
  volumeOff: {
    paths: ['M11 5 6 9H2v6h4l5 4z', 'M22 9l-6 6', 'M16 9l6 6'],
  },
  // 星形/思考程度
  spark: {
    paths: ['M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z'],
  },
  // 设置齿轮
  settings: {
    circles: [[12, 12, 3]],
    paths: ['M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z', 'M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z'],
  },
  // 收起/展开 chevron
  chevronLeft: { paths: ['m15 18-6-6 6-6'] },
  // 时钟（历史）
  clock: {
    circles: [[12, 12, 9]],
    paths: ['M12 7v5l3 3'],
  },
  // 下载
  download: {
    paths: ['M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4', 'M7 10l5 5 5-5', 'M12 15V3'],
  },
  // 刷新
  reload: {
    paths: ['M23 4v6h-6', 'M1 20v-6h6', 'M3.51 9a9 9 0 0 1 14.85-3.36L23 10', 'M1 14l4.64 4.36A9 9 0 0 0 20.49 15'],
  },
  // 双箭头下（滚动到底）
  chevronsDown: {
    paths: ['m7 6 5 5 5-5', 'm7 13 5 5 5-5'],
  },
  // 关闭 ×
  x: {
    paths: ['M18 6 6 18', 'M6 6l12 12'],
  },
  // 眼睛（预览）
  eye: {
    paths: ['M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z'],
    circles: [[12, 12, 3]],
  },
  // 音频波形（录音中）
  wave: {
    lines: [[4, 10, 4, 14], [8, 7, 8, 17], [12, 4, 12, 20], [16, 7, 16, 17], [20, 10, 20, 14]],
  },
  // 检索雷达（记忆检索中）
  radar: {
    circles: [[12, 12, 9], [12, 12, 4.5]],
    lines: [[12, 12, 18, 6]],
  },
}

// audio 图标含填充形状的兼容写法：单独声明
ICON_SHAPES['audio'] = {
  paths: ['M11 5 6 9H2v6h4l5 4z', 'M15.54 8.46a5 5 0 0 1 0 7.07', 'M19.07 4.93a10 10 0 0 1 0 14.14'],
}

const shape = computed(() => ICON_SHAPES[props.name] ?? ICON_SHAPES['file'])
const paths = computed(() => shape.value.paths ?? [])
const circles = computed(() => shape.value.circles ?? [])
const rects = computed(() => shape.value.rects ?? [])
const lines = computed(() => shape.value.lines ?? [])
</script>

<style scoped>
.nr-ui-icon {
  flex: none;
  vertical-align: middle;
}
</style>
