# 循环导入问题报告

## 问题描述
在运行单元测试时，发现 `neurova/skills/` 模块存在循环导入问题，阻止了测试的正常运行。

## 错误详情
```
ImportError: cannot import name 'SkillManifest' from partially initialized module 'neurova.skills.manifest' (most likely due to a circular import)
```

## 循环导入链
```
neurova/skills/manifest.py
  → neurova/skills/skill_packager.py
    → neurova/skills/manifest.py  ← 循环！
```

## 问题文件
1. `neurova/skills/manifest.py` (第9行)
2. `neurova/skills/skill_packager.py` (第25行)

## 解决方案
需要修复循环导入，建议：
1. 将 `manifest.py` 中的导入改为惰性导入
2. 或者重构代码，将 `SkillManifest`、`PluginEntryPoints`、`SkillRecord` 的定义移到 `manifest.py`

## 影响
- 阻止了系统设置功能的单元测试运行
- 可能影响其他模块的测试

## 建议
由于这是 `skills` 模块的预先存在的问题，建议由 `skill-system-dev` 修复此问题。

---
**报告人**: settings-dev  
**报告时间**: 2026-05-12 22:30
