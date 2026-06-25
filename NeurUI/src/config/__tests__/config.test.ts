/**
 * 阶段6 RED: 验证前端统一配置库
 *
 * 测试内容：
 * 1. config.apiBaseUrl 存在且为字符串
 * 2. config.apiTimeout 存在且为数字
 * 3. config.appName 存在且为字符串
 * 4. config.isDev 和 config.isProd 为布尔值
 * 5. getConfig() 返回配置对象副本
 * 6. updateConfig({ apiTimeout: 5000 }) 可更新配置
 */
import { describe, it, expect, beforeEach } from 'vitest'
import config, { getConfig, updateConfig } from '../index'

describe('config - 基本属性', () => {
  it('apiBaseUrl 应存在且为字符串', () => {
    expect(typeof config.apiBaseUrl).toBe('string')
    expect(config.apiBaseUrl.length).toBeGreaterThan(0)
  })

  it('apiTimeout 应存在且为数字', () => {
    expect(typeof config.apiTimeout).toBe('number')
    expect(config.apiTimeout).toBeGreaterThan(0)
  })

  it('appName 应存在且为字符串', () => {
    expect(typeof config.appName).toBe('string')
    expect(config.appName.length).toBeGreaterThan(0)
  })

  it('appVersion 应存在且为字符串', () => {
    expect(typeof config.appVersion).toBe('string')
    expect(config.appVersion.length).toBeGreaterThan(0)
  })

  it('isDev 应为布尔值', () => {
    expect(typeof config.isDev).toBe('boolean')
  })

  it('isProd 应为布尔值', () => {
    expect(typeof config.isProd).toBe('boolean')
  })

  it('isDev 和 isProd 应互斥', () => {
    expect(config.isDev).not.toBe(config.isProd)
  })
})

describe('getConfig - 返回副本', () => {
  it('应返回包含所有字段的对象', () => {
    const c = getConfig()
    expect(c).toHaveProperty('apiBaseUrl')
    expect(c).toHaveProperty('apiTimeout')
    expect(c).toHaveProperty('appName')
    expect(c).toHaveProperty('appVersion')
    expect(c).toHaveProperty('isDev')
    expect(c).toHaveProperty('isProd')
  })

  it('返回的对象修改不应影响原配置', () => {
    const c1 = getConfig()
    const originalTimeout = c1.apiTimeout
    c1.apiTimeout = 999999
    c1.appName = '篡改名'

    const c2 = getConfig()
    expect(c2.apiTimeout).toBe(originalTimeout)
    expect(c2.appName).not.toBe('篡改名')
  })

  it('多次调用应返回独立的副本', () => {
    const c1 = getConfig()
    const c2 = getConfig()
    expect(c1).not.toBe(c2)
    expect(c1).toEqual(c2)
  })
})

describe('updateConfig - 更新配置', () => {
  let originalTimeout: number

  beforeEach(() => {
    originalTimeout = getConfig().apiTimeout
  })

  it('应可更新 apiTimeout', () => {
    updateConfig({ apiTimeout: 5000 })
    expect(getConfig().apiTimeout).toBe(5000)
    // 恢复
    updateConfig({ apiTimeout: originalTimeout })
  })

  it('应可更新 appName', () => {
    const original = getConfig().appName
    updateConfig({ appName: 'TestApp' })
    expect(getConfig().appName).toBe('TestApp')
    updateConfig({ appName: original })
  })

  it('应可同时更新多个字段', () => {
    const original = getConfig()
    updateConfig({ apiTimeout: 10000, appName: 'Multi' })
    const updated = getConfig()
    expect(updated.apiTimeout).toBe(10000)
    expect(updated.appName).toBe('Multi')
    // 恢复
    updateConfig({ apiTimeout: original.apiTimeout, appName: original.appName })
  })

  it('未更新的字段应保持原值', () => {
    const original = getConfig()
    updateConfig({ apiTimeout: 7777 })
    const updated = getConfig()
    expect(updated.appName).toBe(original.appName)
    expect(updated.appVersion).toBe(original.appVersion)
    expect(updated.isDev).toBe(original.isDev)
    // 恢复
    updateConfig({ apiTimeout: original.apiTimeout })
  })
})
