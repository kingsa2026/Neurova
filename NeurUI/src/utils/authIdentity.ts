/**
 * 「这一发失败是身份问题吗」——全仓唯一一处判定。
 *
 * 401 与 403 是两件事：一个是**没登录**（或登录状态已过期），一个是**登了但不够格**。
 * 把两者合并成一句，或者干脆把它们说成「暂无数据」「操作失败」，都是把登录问题伪装成
 * 数据问题或通用故障（本仓既有纪律见 `MobilePairingPanel.vue` 的「权限态与空态不合并」
 * 注释与 `AgentChannelPage.vue` 的 accessDenied 独立一格）。
 */

export type IdentityFailure = 'anonymous' | 'forbidden'

/** 只有 401/403 算身份失败；5xx、404、无状态码一律不算——不许借这道口吞真故障。 */
export function identityFailureOf(status: unknown): IdentityFailure | null {
  if (status === 401) return 'anonymous'
  if (status === 403) return 'forbidden'
  return null
}
