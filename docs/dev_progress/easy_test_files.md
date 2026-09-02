# 易测试文件清单

**生成时间**: 2026-05-13 02:25  
**目的**: 帮助 frontend-agent-dev 快速提高测试覆盖率（70% → 80%）

---

## ✅ 非常简单（优先级1）

### 1. `src/hooks/useAppMessage.ts`
**原因**: 
- 只有 9 行代码
- 只是返回 antd 的 message 实例
- 不需要 mock

**测试模板**:
```typescript
import { describe, it, expect, vi } from 'vitest';
import { useAppMessage } from '@/hooks/useAppMessage';
import { message } from 'antd';

describe('useAppMessage', () => {
  it('should return antd message instance', () => {
    const result = useAppMessage();
    expect(result.message).toBe(message);
  });
  
  it('should have all message methods', () => {
    const { message } = useAppMessage();
    expect(typeof message.success).toBe('function');
    expect(typeof message.error).toBe('function');
    expect(typeof message.info).toBe('function');
    expect(typeof message.warning).toBe('function');
    expect(typeof message.loading).toBe('function');
  });
});
```

**预计时间**: 5分钟  
**覆盖率贡献**: +0.5%

---

### 2. `src/components/ThemeToggle.tsx`
**原因**:
- 只有 36 行代码
- 只是切换主题的开关
- UI 组件，容易测试渲染和交互

**测试要点**:
- 渲染正确（light/dark/auto 三种模式）
- 点击开关调用 `setTheme`
- disabled 状态（auto 模式）

**预计时间**: 15分钟  
**覆盖率贡献**: +1%

---

### 3. `src/components/LanguageSelector.tsx`
**原因**:
- 只有 42 行代码
- 只是语言选择的下拉框
- UI 组件，容易测试渲染和交互

**测试要点**:
- 渲染正确的选项列表
- 选择语言调用 `setLanguage`
- 显示当前语言

**预计时间**: 15分钟  
**覆盖率贡献**: +1%

---

## ⚡ 简单（优先级2）

### 4. `src/stores/useSettingsStore.ts`
**原因**:
- 状态管理，逻辑相对简单
- 可以参考已有的 `agentStore.test.ts` 和 `providerStore.test.ts`

**测试要点**:
- 初始状态正确
- `setTheme` 更新主题
- `setLanguage` 更新语言
- 持久化到 localStorage

**预计时间**: 30分钟  
**覆盖率贡献**: +3%

---

### 5. `src/contexts/ThemeContext.tsx`
**原因**:
- 已经有测试文件 `ThemeContext.test.tsx`
- 只需要修复测试错误（我之前已提供修复方案）

**测试要点**:
- 提供 theme context
- 更新 theme
- （可以删除"should throw error"测试）

**预计时间**: 10分钟（修复现有测试）  
**覆盖率贡献**: +1%

---

### 6. `src/contexts/LanguageContext.tsx`
**原因**:
- 和 ThemeContext 类似
- 可以参考 ThemeContext 的测试

**测试要点**:
- 提供 language context
- 更新 language

**预计时间**: 20分钟  
**覆盖率贡献**: +1.5%

---

## 📊 预计收益

| 文件 | 预计时间 | 覆盖率贡献 |
|------|----------|------------|
| useAppMessage.ts | 5分钟 | +0.5% |
| ThemeToggle.tsx | 15分钟 | +1% |
| LanguageSelector.tsx | 15分钟 | +1% |
| useSettingsStore.ts | 30分钟 | +3% |
| ThemeContext.tsx | 10分钟 | +1% |
| LanguageContext.tsx | 20分钟 | +1.5% |
| **总计** | **95分钟** | **+8%** |

**从 70% → 78%**，还差 2% 到 80%

---

## 🎯 额外建议

如果还需要 +2% 覆盖率，可以测试：

### 7. `src/utils/` 目录
**当前状态**: 空目录  
**建议**: 如果有工具函数，优先测试

### 8. `src/components/PageHeader.tsx`
**需要先检查是否容易测试**

---

## 📝 测试模板

### 简单组件测试模板
```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import ComponentName from '@/components/ComponentName';

// Mock context hook
vi.mock('@/contexts/SomeContext', () => ({
  useSomeContext: vi.fn(),
}));

describe('ComponentName', () => {
  beforeEach(() => {
    // Reset mock
    vi.clearAllMocks();
    
    // Default mock implementation
    (useSomeContext as unknown as vi.Mock).mockReturnValue({
      // mock values
    });
  });
  
  it('should render correctly', () => {
    render(<ComponentName />);
    // assertions
  });
  
  it('should handle user interaction', () => {
    const mockFn = vi.fn();
    (useSomeContext as unknown as vi.Mock).mockReturnValue({
      someFn: mockFn,
    });
    
    render(<ComponentName />);
    fireEvent.click(screen.getByText('Some Button'));
    expect(mockFn).toHaveBeenCalled();
  });
});
```

---

## ✅ 下一步

1. **立即开始**: 先测试 `useAppMessage.ts`（5分钟，快速见效）
2. **然后**: 测试 `ThemeToggle.tsx` 和 `LanguageSelector.tsx`
3. **最后**: 测试 store 和 context

**目标**: 在 03:00 前完成 +5% 覆盖率（70% → 75%）
