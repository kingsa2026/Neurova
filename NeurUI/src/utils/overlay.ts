/**
 * Ant Design 弹层容器（单一事实源）。
 *
 * 弹层默认挂在触发节点父容器里，玻璃卡片（GlassPanel / GlassCard）
 * `overflow: hidden` 会把弹层裁掉（默认 LLM 下拉被裁剪事故 2026-09-09），
 * 故需要把弹层挂到 body 逃出裁剪。
 *
 * 此前有 4 处各写一份（`App.vue` 与两个侧栏候选项叫 `getPopupContainer`，
 * `ModelPage.vue` 叫 `popupToBody`）：同名同体、互不引用。收口到本模块后
 * 各处只 import，不再各留一份 `() => document.body`。
 */
export function overlayContainerToBody(): HTMLElement {
  return document.body
}
