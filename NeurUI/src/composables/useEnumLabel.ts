/**
 * useEnumLabel.ts — 后端枚举名的多语言标签
 *
 * 后端把枚举原值直接放进响应（DriveType 的 competence、人格 traits 的 Openness…），
 * 展示层需按当前语言解析 motivation.* / personality.* / emotion.* 等键。
 * 未收录值必须回退后端原文：自定义人格模板特质与后端新增枚举都不该露出键名。
 */
import { useI18n } from 'vue-i18n'

export function useEnumLabel() {
  const { t, te } = useI18n()

  /** 大小写不敏感：Competence / COMPETENCE / competence 解析为同一键 */
  function enumLabel(prefix: string, name?: string | null): string {
    if (!name) return ''
    const key = `${prefix}.${name.toLowerCase()}`
    return te(key) ? t(key) : name
  }

  return { enumLabel }
}
