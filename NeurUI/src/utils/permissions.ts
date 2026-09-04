/**
 * 用户组功能模块可见性判定
 *
 * 与后端契约对齐（neurova/auth/user_group_model.py get_allowed_modules_for_user）:
 *  - 用户不属于任何组 / 所属组未配置模块 → allowed_modules 为空数组 = 不限制
 *  - admin 恒全量可见
 *  - 模块 key 使用菜单路由 path，动态段（/agent/:id/memory）按前缀匹配实际路由
 */

export interface ModuleAccessContext {
  role?: string
  /** 后端 /auth/me 返回的 allowed_modules（空数组/缺省 = 不限制） */
  allowed_modules?: string[]
}

/** /dashboard 是兜底主页，恒可见 */
const ALWAYS_VISIBLE_PREFIXES = ['/dashboard']

function matchModule(moduleKey: string, path: string): boolean {
  if (!moduleKey.includes(':')) {
    return path === moduleKey || path.startsWith(moduleKey + '/')
  }
  // 动态段模块（/agent/:id/memory）→ 逐段比对，:xxx 匹配任意单段
  const mParts = moduleKey.split('/')
  const pParts = path.split('/')
  for (let i = 0; i < mParts.length; i++) {
    if (mParts[i].startsWith(':')) continue
    if (pParts[i] !== mParts[i]) return false
  }
  return pParts.length >= mParts.length
}

/**
 * 判定当前用户是否可访问某功能模块（路由 path 粒度）
 */
export function canAccessModule(moduleKey: string, ctx: ModuleAccessContext): boolean {
  if (ctx?.role === 'admin') return true
  const allowed = ctx?.allowed_modules
  // 空数组/缺省 = 不限制（向后兼容：存量用户与未配置组全可见）
  if (!allowed || allowed.length === 0) return true
  if (ALWAYS_VISIBLE_PREFIXES.some(p => matchModule(p, moduleKey))) return true
  return allowed.some(key => matchModule(key, moduleKey))
}

/**
 * 过滤模块 key 列表，仅保留当前用户可见的项（保持原顺序）
 */
export function filterModules(moduleKeys: string[], ctx: ModuleAccessContext): string[] {
  return moduleKeys.filter(key => canAccessModule(key, ctx))
}
