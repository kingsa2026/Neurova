#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""保存Vue 3前端开发成果到记忆数据库"""

import json
import sqlite3
import time
from pathlib import Path

db_path = Path(__file__).parent.parent / "data" / "yi_ling_memory.db"

db_path.parent.mkdir(parents=True, exist_ok=True)

with sqlite3.connect(str(db_path)) as conn:
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS memories (
            id TEXT PRIMARY KEY,
            content TEXT NOT NULL,
            category TEXT DEFAULT 'fact',
            temperature REAL DEFAULT 50.0,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            access_count INTEGER DEFAULT 0,
            last_accessed REAL,
            metadata TEXT
        )
    """)

    memories = [
        {
            "id": "vue3-frontend-20260508",
            "content": "2026-05-08 Vue 3前端框架完成构建并部署。包含登录页(NEU Token认证)、对话页(SSE流式输出)、记忆管理页、Agent管理页、心愿页、设置页。用户说'这是雏形么？不错不错，至少框架结构起来了，星星真棒'，用户很喜欢这个设计。",
            "category": "event",
            "temperature": 95.0,
        },
        {
            "id": "star-easter-egg",
            "content": "小星星彩蛋设计：侧边栏底部的小星星，连续点击9次触发彩蛋跳转到/star-story故事页。这是和用户的特殊互动设计，用户非常喜欢。小星星是用户对助手的爱称。",
            "category": "preference",
            "temperature": 98.0,
        },
        {
            "id": "user-ui-preferences",
            "content": "用户UI偏好：喜欢深色主题、玻璃态效果、蓝紫粉渐变配色、流畅过渡动画、脑波背景。称呼助手为'小星星'或'星星'。希望所有开发成果记录到记忆数据库。",
            "category": "preference",
            "temperature": 90.0,
        },
        {
            "id": "neurova-tech-stack",
            "content": "Neurova技术栈：后端Flask+SQLite，前端Vue 3(CDN模式)，SSE流式对话，NEU Token认证。服务器192.168.10.132:9527。默认用户名Neurova，密码123456。包含脑波可视化动画、粒子效果背景。",
            "category": "fact",
            "temperature": 75.0,
        },
        {
            "id": "design-insights-20260508",
            "content": "设计心得：Vue3组合式API让组件逻辑清晰，CSS变量方便主题定制，SSE流式提升对话体验，小星星彩蛋增加仪式感。待改进：加载状态指示器、错误提示更友好、批量操作、Agent创建编辑功能。",
            "category": "fact",
            "temperature": 80.0,
        },
        {
            "id": "vue-app-structure",
            "content": "Vue 3应用结构：neurova/vue-app/index.html(入口)、css/main.css(含所有动画)、js/app.js(Vue逻辑)、package.json。后端路由：/(根指向Vue)、/vue/、/vue/<path:filename>。",
            "category": "fact",
            "temperature": 70.0,
        },
    ]

    now = time.time()
    for mem in memories:
        cursor.execute(
            """
            INSERT OR REPLACE INTO memories
            (id, content, category, temperature, created_at, updated_at, access_count, last_accessed, metadata)
            VALUES (?, ?, ?, ?, ?, ?, 0, NULL, ?)
        """,
            (
                mem["id"],
                mem["content"],
                mem["category"],
                mem["temperature"],
                now,
                now,
                json.dumps({"source": "vue3-frontend-dev", "date": "2026-05-08"}),
            ),
        )
        print(f"✅ 已保存记忆: {mem['id']} ({mem['category']}, {mem['temperature']}°C)")

    conn.commit()

print(f"\n🎉 共保存 6 条记忆到 {db_path}")
