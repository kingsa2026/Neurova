/**
 * 通用工具函数
 */
&nbsp;
/**
 * 防抖函数
 * @param fn - 要防抖的函数
 * @param delay - 延迟时间（毫秒）
 * @returns 防抖后的函数
 */
export function debounce&lt;T extends (...args: unknown[]) =&gt; unknown&gt;(fn: T, delay: number): (...args: Parameters&lt;T&gt;) =&gt; void {
  let timer: ReturnType&lt;typeof setTimeout&gt; | null = null
  return function (this: unknown, ...args: Parameters&lt;T&gt;) {
    if (timer) clearTimeout(timer)
    timer = setTimeout(() =&gt; {
      fn.apply(this, args)
    }, delay)
  }
}
&nbsp;
/**
 * 节流函数
 * @param fn - 要节流的函数
 * @param interval - 间隔时间（毫秒）
 * @returns 节流后的函数
 */
export function throttle&lt;T extends (...args: unknown[]) =&gt; unknown&gt;(fn: T, interval: number): (...args: Parameters&lt;T&gt;) =&gt; void {
  let lastTime = 0
  return function (this: unknown, ...args: Parameters&lt;T&gt;) {
    const now = Date.now()
    if (now - lastTime &gt;= interval) {
      lastTime = now
      fn.apply(this, args)
    }
  }
}
&nbsp;
/**
 * 格式化日期
 * @param date - 日期对象或时间戳
 * @param format - 格式字符串（默认：'YYYY-MM-DD HH:mm:ss'）
 * @returns 格式化后的日期字符串
 */
export function formatDate(date: Date | number, format: string = 'YYYY-MM-DD HH:mm:ss'): string {
  const d = date instanceof Date ? date : new Date(date)
  const year = d.getFullYear()
  const month = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  const hours = String(d.getHours()).padStart(2, '0')
  const minutes = String(d.getMinutes()).padStart(2, '0')
  const seconds = String(d.getSeconds()).padStart(2, '0')
  return format
    .replace('YYYY', String(year))
    .replace('MM', month)
    .replace('DD', day)
    .replace('HH', hours)
    .replace('mm', minutes)
    .replace('ss', seconds)
}
&nbsp;
/**
 * 格式化文件大小
 * @param bytes - 字节数
 * @returns 格式化后的文件大小字符串
 */
export function formatFileSize(bytes: number): string {
  if (bytes === 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const k = 1024
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + units[i]
}
&nbsp;
/**
 * 生成唯一 ID
 * @returns 唯一 ID 字符串
 */
export function generateId(): string {
  return Date.now().toString(36) + Math.random().toString(36).substr(2, 9)
}
&nbsp;
/**
 * 深拷贝
 * @param obj - 要拷贝的对象
 * @returns 拷贝后的对象
 */
export function deepClone&lt;T&gt;(obj: T): T {
  if (obj === null || typeof obj !== 'object') return obj
  return JSON.parse(JSON.stringify(obj))
}
&nbsp;
/**
 * 检查是否为空值（null、undefined、空字符串、空数组、空对象）
 * @param value - 要检查的值
 * @returns 是否为空
 */
export function isEmpty(value: unknown): boolean {
  if (value === null || value === undefined) return true
  if (typeof value === 'string' &amp;&amp; value.trim() === '') return true
  if (Array.isArray(value) &amp;&amp; value.length === 0) return true
  if (typeof value === 'object' &amp;&amp; Object.keys(value as object).length === 0) return true
  return false
}
&nbsp;