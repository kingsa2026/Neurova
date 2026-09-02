# 登录和注册页面 Logo 替换

**替换时间**: 2026-06-10 09:40  
**替换内容**: 将登录和注册页面顶部的图标和文字组合替换为 NEUROVA-LOGO350white.png 图片

---

## 一、修改文件

### 1.1 LoginPage.vue
- **位置**: `NeurUI/src/pages/LoginPage.vue`
- **修改内容**:
  1. 将 `<div class="nr-auth-logo">N</div>` 和标题/副标题替换为 `<img>` 标签
  2. 更新 CSS 样式：将 `.nr-auth-logo` 替换为 `.nr-auth-logo-img`

**模板修改**:
```html
<!-- 之前 -->
<div class="nr-auth-header">
  <div class="nr-auth-logo">N</div>
  <h1 class="nr-auth-title">{{ t('auth.loginTitle') }}</h1>
  <p class="nr-auth-subtitle">{{ t('auth.loginSubtitle') }}</p>
</div>

<!-- 之后 -->
<div class="nr-auth-header">
  <img src="/img/NEUROVA-LOGO350white.png" alt="Neurova Logo" class="nr-auth-logo-img" />
</div>
```

**CSS 修改**:
```css
/* 之前 */
.nr-auth-logo {
  width: 56px;
  height: 56px;
  margin: 0 auto 16px;
  border-radius: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: var(--nr-font-display);
  font-size: 26px;
  font-weight: 700;
  color: white;
  background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 50%, #a78bfa 100%);
  box-shadow: 0 4px 24px rgba(99, 102, 241, 0.35);
  animation: logo-pulse 3s ease-in-out infinite;
}

/* 之后 */
.nr-auth-logo-img {
  max-width: 280px;
  height: auto;
  margin: 0 auto 24px;
  display: block;
}
```

### 1.2 RegisterPage.vue
- **位置**: `NeurUI/src/pages/RegisterPage.vue`
- **修改内容**: 与 LoginPage.vue 相同的修改

---

## 二、图片资源

- **图片路径**: `NeurUI/public/img/NEUROVA-LOGO350white.png`
- **图片大小**: 6.74 KB
- **显示尺寸**: 最大宽度 280px，高度自适应

---

## 三、设计说明

### 3.1 为什么使用图片 Logo
1. **品牌一致性**: 使用官方 Logo 确保品牌识别度
2. **视觉效果**: 白色 Logo 在深色背景上更醒目
3. **专业感**: 图片 Logo 比文字 "N" 更专业

### 3.2 样式设计
- **居中显示**: 使用 `margin: 0 auto` 水平居中
- **响应式**: `max-width: 280px` 确保在不同屏幕尺寸下显示正常
- **间距调整**: `margin-bottom: 24px` 提供合适的间距

---

## 四、验证结果

### 4.1 功能验证
- ✅ 登录页面显示新的 Logo 图片
- ✅ 注册页面显示新的 Logo 图片
- ✅ 图片正确加载（路径正确）
- ✅ 响应式设计正常

### 4.2 代码质量
- ✅ Linter 检查通过（0 个错误）
- ✅ 代码结构清晰
- ✅ 样式隔离（scoped）

---

## 五、后续建议

### 5.1 优化建议
1. **图片优化**: 考虑使用 WebP 格式减小文件大小
2. **加载状态**: 添加图片加载状态（loading 状态）
3. **暗色模式**: 如果支持暗色模式，考虑使用不同版本的 Logo

### 5.2 扩展建议
1. **其他页面**: 考虑在其他页面也使用统一的 Logo
2. **Favicon**: 更新网站 Favicon 为相同的 Logo
3. **品牌指南**: 建立品牌视觉指南，确保一致性

---

## 六、总结

本次修改成功将登录和注册页面顶部的图标和文字组合替换为 NEUROVA-LOGO350white.png 图片，提升了品牌识别度和视觉效果。修改包括：

1. ✅ **模板更新**: 使用 `<img>` 标签显示 Logo 图片
2. ✅ **样式更新**: 添加新的 CSS 类 `.nr-auth-logo-img`
3. ✅ **响应式设计**: 确保在不同屏幕尺寸下正常显示
4. ✅ **代码质量**: 通过 linter 检查，无错误

**修改文件**:
1. `NeurUI/src/pages/LoginPage.vue`
2. `NeurUI/src/pages/RegisterPage.vue`

---

*修改完成时间: 2026-06-10 09:40*
*验证状态: ✅ 全部通过*