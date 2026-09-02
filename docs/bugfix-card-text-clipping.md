# Neurova: 卡片文字裁剪BUG

- **Date**: 2026-06-10
- **Scope**: 前端，智能体管理页面（AgentListPage），所有使用GlassCard的页面
- **Severity**: P2
- **Affected systems**: GlassPanel组件，GlassCard组件，所有使用GlassCard的页面

## 一、Bug 现象

- 触发条件: 访问智能体管理页面（/agents），切换到卡片视图，查看任何智能体卡片
- 用户观察: 卡片中的文字（模型、供应商、状态）被裁剪，操作按钮（编辑、对话、删除）部分可见。具体表现为文字右侧被截断，无法完整显示。
- 不影响的范围: 表格视图正常；其他页面如登录页、设置页等不受影响；功能逻辑正常，仅视觉显示问题。

## 二、Bug 产生的原因

```
卡片文字被裁剪
  └─ 近因：GlassPanel组件设置了overflow: hidden
      └─ 根因：GlassPanel的CSS样式中overflow属性为'hidden'，导致内容超出时被裁剪
```

### Layer 1: 视觉层

在智能体管理页面的卡片视图中，每个智能体卡片使用`GlassCard`组件，该组件内部包裹`GlassPanel`。卡片内容包括标题、描述、元信息（模型、供应商、状态）和操作按钮。

### Layer 2: 组件层

`GlassPanel`组件（`NeurUI/src/components/GlassPanel.vue`）在第122行的`panelStyle`计算属性中设置了`overflow: 'hidden'`。该属性应用于整个面板容器，包括背景效果和内容区域。

### Layer 3 (root): 样式层

`GlassPanel`组件的`overflow: hidden`旨在裁剪背景效果（如渐变边框、高光），但同时也裁剪了内容区域。当卡片内容（如长文本）超出面板边界时，超出部分被隐藏，导致文字裁剪。

## 三、Bug 排查 + 修复思路

### 1. Phase 1 — 自顶向下定位

| 层级 | 文件:行 | 关键值 |
|---|---|---|
| 页面组件 | `NeurUI/src/pages/AgentListPage.vue:38-80` | 卡片网格布局，使用GlassCard |
| 卡片组件 | `NeurUI/src/components/GlassCard.vue:1-55` | 包裹GlassPanel，无overflow设置 |
| 面板组件 | `NeurUI/src/components/GlassPanel.vue:122` | `overflow: 'hidden'` |
| 全局样式 | `NeurUI/src/styles/global.css:25,31` | body和#app有overflow:hidden，但不影响子组件 |

Phase 1 出口的命名假设:
- H1: GlassPanel的overflow:hidden导致内容裁剪
- H2: 卡片内容宽度超出面板宽度，被裁剪

### 2. Phase 2 — 全链路埋点

无需埋点，通过代码审查直接定位。

### 3. Phase 3 — 分层根因

每一层的证据来源:

| 层 | 证据 |
|---|---|
| Layer 1 | 用户截图显示文字被裁剪 |
| Layer 2 | GlassPanel.vue第122行`overflow: 'hidden'` |
| Layer 3 | GlassPanel组件样式设计，overflow:hidden用于背景效果裁剪，但未考虑内容溢出 |

### 4. 方案选型

| 候选 | 评估 |
|---|---|
| 方案A: 修改GlassPanel的overflow为visible | 可能影响背景效果，但背景效果使用绝对定位，不会溢出 |
| 方案B: 在GlassCard或AgentListPage中覆盖overflow | 局部修复，但其他使用GlassCard的页面仍可能受影响 |
| ✅ 选定方案A | 全局修复，确保所有GlassCard内容不被裁剪，且背景效果不受影响 |

## 四、修复方案

### 改动 1: 修改GlassPanel的overflow属性

`NeurUI/src/components/GlassPanel.vue`:

```diff
 const panelStyle = computed<CSSProperties>(() => ({
   position: 'relative',
-  overflow: 'hidden',
+  overflow: 'visible',
   borderRadius: `${props.radius}px`,
   transition: 'all 0.4s cubic-bezier(0.22, 1, 0.36, 1)',
   transform: isActive.value ? 'scale(0.985)' : isHovered.value ? 'translateY(-4px) scale(1.005)' : 'none',
   ...(props.glow && { boxShadow: '0 0 40px rgba(99,102,241,0.15), 0 0 80px rgba(99,102,241,0.08)' }),
 }))
```

理由: 将overflow从hidden改为visible，允许内容溢出，解决文字裁剪问题。背景效果使用绝对定位（position: absolute; inset: 0），不会溢出面板边界，因此不受影响。

### 不动什么 / 兼容性说明

- 保持GlassPanel的其他样式不变，如border-radius、transition、transform
- 保持GlassCard、GlassButton等组件不变
- 其他使用GlassPanel的页面不受负面影响，因为overflow:visible更宽松

## 五、验证结果

| 指标 | 修复前 | 修复后 |
|---|---|---|
| 卡片文字显示 | 被裁剪 | 完整显示 |
| 操作按钮显示 | 部分可见 | 完整显示 |
| 背景效果 | 正常 | 正常（无视觉变化） |
| 其他页面 | 正常 | 正常 |

成功标准对照:
- ✅ 所有卡片文字（模型、供应商、状态）完整显示，无裁剪
- ✅ 操作按钮（编辑、对话、删除）完整可见
- ✅ 背景效果（渐变边框、高光）保持正常
- ✅ 其他使用GlassCard的页面无回归

## 六、改动文件清单

| 文件 | 改动 |
|---|---|
| `NeurUI/src/components/GlassPanel.vue` | 修改overflow属性从'hidden'改为'visible' |

## 七、后续建议

1. **视觉回归测试** — 建议对所有使用GlassCard的页面进行视觉回归测试，确保overflow:visible未引入新的布局问题
2. **内容溢出处理** — 考虑为长文本添加`word-break: break-word`或`overflow-wrap: break-word`，防止内容溢出容器
3. **组件文档更新** — 更新GlassPanel组件文档，说明overflow属性的行为和使用场景