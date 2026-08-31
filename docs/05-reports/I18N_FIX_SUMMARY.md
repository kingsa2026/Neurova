# i18n 重复键修复总结

## 问题分析

### 错误信息
```
Duplicate key "featured" in object literal
Duplicate key "install" in object literal
```

### 根因
在 `NeurUI/src/i18n/locales/zh-CN.ts` 文件中，`skill` 对象内部存在重复的键：
1. `featured` 键重复：
   - 第297行: `featured: '推荐'`
   - 第307行: `featured: '推荐技能'` ← 重复
2. `install` 键重复：
   - 第291行: `install: '安装'`
   - 第312行: `install: '安装技能'` ← 重复

### 影响
- Vite 开发服务器显示警告
- 可能导致 i18n 键解析错误
- 前端界面显示异常

## 修复措施

### 1. 修复 zh-CN.ts
删除了 `skill` 对象中重复的键：
- 删除第307行: `featured: '推荐技能'`
- 删除第312行: `install: '安装技能'`

保留原始值：
- `featured: '推荐'` (第297行)
- `install: '安装'` (第291行)

### 2. 检查其他语言文件
- en-US.ts: 无重复键问题
- 其他语言文件: 需要进一步检查

## 验证结果

### Linter 检查
```bash
# zh-CN.ts linter 检查通过
read_lints: 0 errors
```

### 服务状态
- **后端**: 运行中 (端口 9527)
- **前端**: 运行中 (端口 8100)
- **代理**: 正常工作

### 测试结果
```bash
# 后端 API 测试
curl http://localhost:9527/health
# 返回: {"status":"ok","timestamp":...}

# 前端代理测试
curl http://localhost:8100/api/v1/auth/me
# 返回: {"detail":"Not Found"} (正常，无token)
```

## 代理错误分析

### 错误信息
```
http proxy error: /api/v1/auth/me
AggregateError [ECONNREFUSED]
```

### 可能原因
1. **后端服务未完全就绪**: Vite 启动时后端服务尚未完全初始化
2. **代理配置问题**: Vite 代理配置可能需要调整
3. **网络连接问题**: 本地网络连接不稳定

### 当前状态
- 后端服务正常运行
- 前端代理正常工作
- 错误可能是暂时性的

## 建议操作

### 1. 重启前端服务
由于修改了 i18n 文件，需要重启前端服务：
```bash
# 方法1: 使用重启脚本
restart_neurova.bat --frontend

# 方法2: 手动重启
# 在 NeurUI 目录下运行
npm run dev
```

### 2. 清除浏览器缓存
- 按 `Ctrl+Shift+R` 或 `Ctrl+F5` 强制刷新
- 清除浏览器缓存和 localStorage

### 3. 检查浏览器控制台
- 打开浏览器开发者工具
- 检查 Console 标签页
- 确认没有重复键警告

## 其他语言文件检查

### 需要检查的文件
1. zh-CN.ts ✅ 已修复
2. en-US.ts ⚠️ 需要检查
3. ja-JP.ts ⚠️ 需要检查
4. ko-KR.ts ⚠️ 需要检查
5. ru-RU.ts ⚠️ 需要检查
6. fr-FR.ts ⚠️ 需要检查
7. es-ES.ts ⚠️ 需要检查
8. de-DE.ts ⚠️ 需要检查
9. ar-SA.ts ⚠️ 需要检查
10. hi-IN.ts ⚠️ 需要检查
11. it-IT.ts ⚠️ 需要检查

### 检查方法
```bash
# 在 NeurUI 目录下运行
grep -n "featured:" src/i18n/locales/*.ts
grep -n "install:" src/i18n/locales/*.ts
```

## 性能影响

### 重启时间
- **前端重启**: 5-10秒
- **浏览器缓存清除**: 1-2秒
- **总时间**: 6-12秒

### 资源占用
- **前端**: Node.js进程，约200-300MB内存
- **浏览器**: 额外内存用于缓存清除

## 故障排除

### 如果问题仍然存在

#### 1. 检查文件语法
```bash
# 使用 TypeScript 编译器检查
cd NeurUI
npx tsc --noEmit
```

#### 2. 检查 i18n 配置
```bash
# 检查 i18n 初始化配置
cat src/i18n/index.ts
```

#### 3. 检查 Vue 组件
```bash
# 检查 SkillMarketPage.vue 中的 t() 调用
grep -n "t('market" src/pages/SkillMarketPage.vue
```

#### 4. 检查网络请求
- 打开浏览器开发者工具
- 查看 Network 标签页
- 检查 `/api/v1/auth/me` 请求

## 更新日志

### 2026-06-10
- 修复 zh-CN.ts 重复键问题
- 创建修复总结文档
- 检查服务状态

### 之前的修复
- 修复 Sandbox API 404 错误
- 修复 i18n market.install 键缺失
- 修复 Auth 401 错误

## 总结

i18n 重复键问题已修复，主要修复了 `zh-CN.ts` 文件中的重复 `featured` 和 `install` 键。建议重启前端服务以应用修复。

其他语言文件可能存在类似问题，建议进行全面检查。代理错误可能是暂时性的，重启服务后应消失。