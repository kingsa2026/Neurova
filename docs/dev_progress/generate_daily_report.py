#!/usr/bin/env python3
"""
每日报告生成器

用法：
    python generate_daily_report.py --date 2026-05-12 --module multi_agent_manager --author "multi-agent-dev"
    python generate_daily_report.py --today --module skill_system --author "skill-system-dev"
"""

import argparse
from datetime import datetime
from pathlib import Path
import sys

def get_template_content() -> str:
    """读取模板内容"""
    template_path = Path(__file__).parent / "daily_reports" / "TEMPLATE.md"
    if template_path.exists():
        with open(template_path, 'r', encoding='utf-8') as f:
            return f.read()
    else:
        return """# 每日进度报告

> **日期**: [YYYY-MM-DD]  
> **报告人**: [姓名/团队成员]  
> **模块**: [模块名称]

---

## 📊 今日进度总结

**完成度**: [X]%  
**今日工作时间**: [X]小时  
**总体状态**: [🟢 正常 / 🟡 有风险 / 🔴 已阻塞]

---

## ✅ 完成的工作

### 1. 代码实现
- [x] [具体完成的子任务1]
- [x] [具体完成的子任务2]

### 2. 文档更新
- [x] 更新了 `[module_designs/xxx.md]`
- [x] 更新了 `progress_tracker.md`

### 3. 测试
- [x] 编写了 [X] 个单元测试
- [x] 测试通过率: [X]%

---

## 🚨 遇到的问题

### 问题1: [问题标题]
- **描述**: [详细描述问题]
- **影响**: [对进度的影响]
- **解决方案**: [已解决/待解决，解决方案]
- **状态**: [已解决/进行中/待解决]

---

## 📅 明日计划

- [ ] [计划完成的子任务1]
- [ ] [计划完成的子任务2]

---

**报告时间**: [YYYY-MM-DD HH:MM]
"""

def generate_report(date: str, module: str, author: str) -> str:
    """生成每日报告"""
    template = get_template_content()
    
    # 替换模板中的占位符
    content = template.replace("[YYYY-MM-DD]", date)
    content = content.replace("[姓名/团队成员]", author)
    content = content.replace("[模块名称]", module)
    content = content.replace("[YYYY-MM-DD HH:MM]", datetime.now().strftime("%Y-%m-%d %H:%M"))
    
    return content

def save_report(date: str, content: str) -> Path:
    """保存报告到文件"""
    reports_dir = Path(__file__).parent / "daily_reports"
    reports_dir.mkdir(exist_ok=True)
    
    file_path = reports_dir / f"{date}.md"
    
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    return file_path

def main():
    parser = argparse.ArgumentParser(description="生成每日进度报告")
    parser.add_argument("--date", type=str, help="报告日期 (格式: YYYY-MM-DD)")
    parser.add_argument("--today", action="store_true", help="使用今天作为报告日期")
    parser.add_argument("--module", type=str, required=True, help="模块名称")
    parser.add_argument("--author", type=str, required=True, help="作者/团队成员名称")
    
    args = parser.parse_args()
    
    # 确定日期
    if args.today:
        date = datetime.now().strftime("%Y-%m-%d")
    elif args.date:
        date = args.date
    else:
        print("错误: 必须提供 --date 或 --today 参数")
        sys.exit(1)
    
    # 生成报告
    content = generate_report(date, args.module, args.author)
    
    # 保存报告
    file_path = save_report(date, content)
    
    print(f"✅ 每日报告已生成: {file_path}")
    print(f"📝 请编辑该文件，填写具体的进度信息")

if __name__ == "__main__":
    main()
