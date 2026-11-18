/**
 * ESLint 平面配置（flat config）——2026-11-19 审计修复批立项。
 *
 * 背景：package.json 的 lint 脚本长期指向 eslint 但仓内既无配置也无依赖
 * （AGENTS.md §4 记载"这道门今天跑不起来"）。本批补齐 flat config 与
 * devDependencies，并把门接进 CI frontend job。
 *
 * 规则档位：js.recommended + ts.recommended + vue flat/essential 起步
 * （能抓住真问题又不至于让存量代码一次性爆量）；后续按棘轮方式收紧。
 */
import js from '@eslint/js'
import pluginVue from 'eslint-plugin-vue'
import tseslint from 'typescript-eslint'
import globals from 'globals'

export default [
  { ignores: ['dist/**', 'node_modules/**', 'src-tauri/**', 'coverage/**', 'playwright-report/**', 'test-results/**'] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  ...pluginVue.configs['flat/essential'],
  {
    files: ['**/*.vue'],
    languageOptions: {
      parserOptions: { parser: tseslint.parser },
    },
  },
  {
    languageOptions: {
      globals: { ...globals.browser, ...globals.node },
    },
  },
  {
    rules: {
      // 棘轮起步档（2026-11-19）：两条高频规则对存量代码各爆 1475/139 处，
      // 先显式关闭让门禁装起来转绿，后续按目录逐步收紧（收紧=改这里）。
      // 其余 recommended/essential 规则全部生效并已在本次清零。
      '@typescript-eslint/no-explicit-any': 'off',
      '@typescript-eslint/no-unused-vars': 'off',
    },
  },
  {
    // 测试档豁免：断言链/属性探针（chai 风格 x.y.z 表达式）在测试里是合法
    // 形态，no-unused-expressions 会把它们全判成无效表达式；vi.hoisted 桩
    // （vitest 提升期回调先于 import 执行）依文档惯例用 require 引入被桩模块。
    files: ['**/__tests__/**', '**/*.test.ts', '**/*.spec.ts'],
    rules: {
      '@typescript-eslint/no-unused-expressions': 'off',
      '@typescript-eslint/no-require-imports': 'off',
    },
  },
]
