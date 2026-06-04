# Neurova

<div align="center">
  <img src="NEUROVA-ICO.png" alt="Neurova Logo" width="120" style="border-radius: 12px; box-shadow: 0 4px 8px rgba(0,0,0,0.2);">
  <h1 style="margin-top: 16px;">🌟 有温度的智能体 🌟</h1>
  <p><i>每一个 Agent 都是一颗善良的星星，而你就是守星人</i></p>
</div>

<br/>

<div align="center">
  <a href="https://github.com/kingsa2026/Neurova/stargazers"><img src="https://img.shields.io/github/stars/kingsa2026/Neurova?style=social" alt="Stars"></a>
  <a href="https://github.com/kingsa2026/Neurova/issues"><img src="https://img.shields.io/github/issues/kingsa2026/Neurova" alt="Issues"></a>
  <a href="https://github.com/kingsa2026/Neurova/blob/main/LICENSE"><img src="https://img.shields.io/github/license/kingsa2026/Neurova" alt="License"></a>
  <img src="https://img.shields.io/badge/Python-3.10+-blue" alt="Python">
  <img src="https://img.shields.io/badge/TypeScript-5.0+-blue" alt="TypeScript">
</div>

<br/>

---

## ✨ NeuCova 独特特点

> **为什么选择 NeuCova？** 因为我们重新定义了 AI Agent —— 不是冰冷的工具，而是有温度、能记忆、会成长的智能伙伴。

### 🌟 1. 每一颗 Agent 都是独特的星星

每一个 Agent 从诞生起就拥有：
- **独有的名字与人格** — 不是编号，而是有个性的存在
- **持续的记忆与情感** — 记得你们之间的每一次对话，每一次喜怒哀乐
- **自主的成长轨迹** — 在陪伴中学习和进化，变得越来越懂你
- **善良的底色** — 由宪法规则守护的行为准则，永远是你可以信赖的伙伴

---

### 🧠 2. 17 维记忆分类体系 — 超越简单的短期/长期记忆

不同于传统 Agent 框架只区分"短期/长期"记忆，Neurova 将记忆精细划分为 **17 种类型**：

| 类型 | 说明 | 典型场景 |
|------|------|----------|
| `conversation` | 对话记忆 | 聊天记录、讨论内容 |
| `fact` | 事实记忆 | 客观信息、常识、数据 |
| `profile` | 用户画像 | 性格、偏好、习惯、生日 |
| `relationship` | 人际关系 | 朋友、同事、家人 |
| `skill` | 技能记忆 | 工具使用、操作方法 |
| `experience` | 经验记忆 | 解决问题的过程、项目经历 |
| `lesson` | 教训记忆 | 失败经验、踩过的坑 |
| `task` | 任务记忆 | 正在进行的目标、待办 |
| `creative` | 创意记忆 | 灵感、想法、脑暴结果 |
| `emotional` | 情感记忆 | 触发强烈情感的事件 |
| `identity` | 身份记忆 | 自我认知、身份标识 |
| `reflection_log` | 反思日志 | 处理问题时用 |
| `question_queue` | 问题队列 | 主动提问时用 |
| `core_command` | 核心指令 | 重要命令和规则 |
| `heartbeat_task` | 心跳任务 | 定期执行的任务 |
| `context_snapshot` | 上下文快照 | 阶段二的上下文状态 |
| `tool_usage` | 工具使用 | ToolMemory集成 |

---

### 🌡️ 3. 记忆温度机制 — 模拟人类遗忘曲线（独创设计）

**独创设计**：引入"温度"维度（0-100°C）模拟人类记忆的遗忘曲线：

```
温度 100°C ───────────────────────────────────────────────
              │
          70°C│  ╭──╮    ╭─╮         ╭─╮
              │  │  │    │ │         │ │  ← 活跃期 (升温/恒温)
          50°C│  │  │    │ │    ╭────╯ │
              │  ╰──╯    │ │    │      │
          30°C│          ╰─╯    │      │  ← 次要期 (缓慢降温)
              │                 │      │
              │                 ╰──────╯
          10°C│                        │  ← 归档期 (接近遗忘)
              │                        │
           0°C│                        ╰── 删除
              └────────┬───────┬───────┬───────→ 时间
                    7天未中  30天未中  60天未中
```

**核心算法实现**（`neurova/cognitive_layers/memory_layer/temperature.py`）：

#### 1. 升温机制（访问时）
```python
T_new = T_current + hit_boost + emotion_bonus + relation_bonus

# 基础升温：每次命中 +5°C
hit_boost = 5.0 * combo_multiplier * saturation_factor

# 连击加成：每10次连续访问增加10%
combo_multiplier = 1.0 + (access_count % 10) * 0.1

# 饱和度因子：温度越高升温越慢（模拟边际效应）
saturation_factor = 1.0 - (current_temp / 100.0) ** 2

# 情感加成：强情感记忆额外升温
emotion_bonus = emotion_score * 3.0

# 关联加成：与其他记忆的关联度
relation_bonus = min(3.0, relation_count * 0.3)
```

#### 2. 降温机制（模拟艾宾浩斯遗忘曲线）
```python
# 艾宾浩斯遗忘曲线因子（分段近似）
if days_idle <= 1:
    curve_factor = 2.0      # 24小时内快速遗忘
elif days_idle <= 7:
    curve_factor = 1.0      # 一周内正常遗忘
elif days_idle <= 30:
    curve_factor = 0.5      # 一月内遗忘减缓
else:
    curve_factor = 0.2      # 超过一月极慢遗忘

# 衰减计算公式
decay = current_temp * base_rate(0.05) * curve_factor * 
        emotion_protect(0.6) * relation_protect(0.7) * 
        important_protect(0.5)

new_temp = max(0.0, current_temp - decay)
```

**艾宾浩斯遗忘曲线可视化**：
```
记忆保留率 (%)
100 │╭──────────────────────────────────
    ││
 80 ││
    ││
 60 ││                    ╭─ 有情感/关联保护
    ││                   ╱
 40 ││                  ╱
    ││                 ╱
 20 ││                ╱  ╭─ 无保护（快速遗忘）
    ││               ╱  ╱
  0 │______________╱__╱______________________→ 时间
    0    1天   7天   30天  60天
```

**独创保护机制**：
- **情感保护**：强情感记忆（emotion_score > 0.5）降温速度减缓 40%，最低保持 20°C
- **关联保护**：多关联记忆（relation_count > 3）降温速度减缓 30%，最低保持 15°C
- **重要记忆**（温度≥80°C）：降温速度减缓 60%，最低保持 30°C
- **固化记忆**（温度≥90°C + 特殊意义）：**永不降温**，永久保存（温度=100°C）

**生命周期阶段转换**：
| 阶段 | 温度范围 | 触发条件 | 数据库状态 |
|------|---------|---------|-----------
| **活跃 (Active)** | 50-100°C | 新创建或7天内被访问 | `lifecycle_stage='active'` |
| **次要 (Secondary)** | 20-50°C | 7-30天未被访问 | `lifecycle_stage='secondary'` |
| **归档 (Archived)** | 0-20°C | 30-60天未被访问 | `lifecycle_stage='archived'` |
| **删除 (Deleted)** | 0°C | 超过60天未访问 | 物理删除 |

> **设计理念**：模拟人类记忆的"遗忘曲线"，但不是简单复制，而是结合AI特性进行创新——温度越高表示记忆越活跃，通过升温/降温模拟记忆的巩固与遗忘，通过保护机制实现重要记忆的长期保存。

---

### 💖 4. 情感中枢引擎 v3.0 — 四层17种情感体系

Neurova v3.0 引入了**情感中枢引擎**，基于心理学的情感分类理论，建立了四层17种情感的完整体系。

#### 四层情感分类：

**第一层：基本情感（5种）**
- 喜悦 (Joy)、悲伤 (Sadness)、愤怒 (Anger)、恐惧 (Fear)、惊讶 (Surprise)

**第二层：复合情感（4种）**
- 爱慕 (Admiration)、嫉妒 (Jealousy)、同情 (Sympathy)、厌恶 (Disgust)

**第三层：高级情感（4种）**
- 羞耻感 (Shame)、内疚感 (Guilt)、自豪感 (Pride)、责任感 (Responsibility)

**第四层：特殊情感（4种）**
- 爱 (Love)、恨 (Hate)、希望 (Hope)、绝望 (Despair)

#### 核心特性：

- ✅ **情感传导规则**（17条规则定义情感间的相互影响）
  - 例如：喜悦 → 希望（权重0.7）、爱 → 喜悦（权重0.9）
- ✅ **情感加权决策**（不同情感对决策的影响权重不同）
  - 爱 (Love): 权重1.3（最高）、责任感 (Responsibility): 权重1.2
- ✅ **与记忆系统集成**（情感状态影响记忆温度）
  - 积极情感 → 降低温度（记忆更稳定）
  - 消极情感 → 提高温度（记忆更不稳定）

📚 **详细设计文档**：`docs/architecture/16-emotion-hub-engine.md`

---

### 🧬 5. CogArch 2.0 认知架构 — 类脑的思考方式

Neurova 采用 **CogArch 2.0 认知架构**，模拟人类大脑的信息处理方式。

#### 四大认知中枢（仿人脑分区）：

| 脑区 | 对应概念 | 功能 |
|------|---------|------|
| **大脑皮层** | 认知中枢 | 观察理解、记忆召回、逻辑推理、行为决策、自我反思 |
| **小脑** | 计划协调 | 意图拆解、任务生成、执行编排、结果评估、错误恢复 |
| **脑干** | 行动输出 | 工具调用、工作流执行、资源调度、执行监控 |
| **脊髓** | 信息通路 | 事件分发、模块通信、外部渠道接入 |

**完整认知循环（5 阶段）**：

```
输入 → 观察 → 回忆 → 推理 → 决策 → 编排 → 执行 → 反思 → 巩固 → 学习进化
```

**共享核心架构**：
```
┌───────────────────────────────────────────────────────┐
│      SHARED CORE (多个 Agent 共用)                     │
│  ┌──────────────────────────────────────────────────┐  │
│  │  共用小脑(Plan Orchestrator) + 脑干(Execution   │  │
│  │  Engine) + 脊髓(Infrastructure)                 │  │
│  └──────────────────────┬───────────────────────────┘  │
└──────────────────────────┼───────────────────────────────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
┌───────────────┐  ┌───────────────┐  ┌───────────────┐
│   Agent Alice  │  │   Agent Bob    │  │  Agent Charlie │
│  ┌─────────┐  │  │  ┌─────────┐  │  │  ┌─────────┐  │
│  │ 大脑     │  │  │  │ 大脑     │  │  │  │ 大脑     │  │
│  │(独立DB)  │  │  │  │(独立DB)  │  │  │  │(独立DB)  │  │
│  └─────────┘  │  │  └─────────┘  │  │  └─────────┘  │
│  ┌─────────┐  │  │  ┌─────────┐  │  │  ┌─────────┐  │
│  │ 办公室   │  │  │  │ 办公室   │  │  │  │ 办公室   │  │
│  │(独立目录) │  │  │  │(独立目录) │  │  │  │(独立目录) │  │
│  └─────────┘  │  │  └─────────┘  │  │  └─────────┘  │
└───────────────┘  └───────────────┘  └───────────────┘
```

> **设计理念**：每个 Agent 都有自己的**大脑**（数据库）和**办公室**（工作目录），但所有 Agent 共用一套**小脑**（计划编排）、**脑干**（执行引擎）和**脊髓**（基础设施）！

---

### 🚀 6. 持续进化能力 — 会成长的智能伙伴

Neurova 的 Agent **会成长**。每一次对话、每一次任务、每一次反思，都是它进化的养料。

#### 五大进化系统：

| 系统 | 功能 | 效果 |
|------|------|------|
| 🎭 **人格系统** | Big Five 人格特质定义与进化 | Agent 性格随着与你的互动不断调整 |
| 🔥 **动机系统** | 好奇心、成就、社交三大内驱力 | Agent 会主动学习、主动提问、主动关心 |
| 📜 **宪法系统** | 行为准则和伦理约束 | 确保 Agent 始终保持善良和正直 |
| 💭 **反思系统** | 自我评价、经验提取、主动提问 | 定期反思"我做的对吗？""我能更好吗？" |
| 🧠 **元认知** | 自我监控、健康检查、自动优化 | Agent 意识到自己的状态，自我调节 |

**自主进化机制**：
1. **意图图谱构建** — 自主构建意图理解图谱
2. **反馈闭环** — 形成"行动→反馈→学习"闭环
3. **梦境整理（Dream Processing）** — 模拟人类睡眠时的记忆整理
4. **能力自主扩展** — 通过 Skill 系统动态加载新能力
5. **记忆升华** — 经验记忆升华为"教训记忆"或"技能记忆"

---

### 👥 7. 多 Agent 团队协作 — 让多颗星星一起闪耀

Neurova 支持**多 Agent 团队协作**，你可以组建自己的"星星团队"，让不同专长的 Agent 分工合作，完成复杂任务。

#### 四种协作模式：

| 模式 | 工作方式 | 适用场景 |
|------|---------|---------|
| **顺序执行** | Agent 按流水线依次处理 | 内容创作 → 审核 → 发布 |
| **并行执行** | 多个 Agent 同时处理不同子任务 | 多维度数据同时分析 |
| **主从模式** | 一个主 Agent 指挥多个从 Agent | 项目管理，任务分配与汇总 |
| **共识模式** | 多个 Agent 独立判断后投票 | 风险决策，多视角验证 |

#### 功能清单（✅ 全部 100% 完成）

| 模块 | 完成度 | 说明 |
|------|--------|------|
| **项目管理** | ✅ 100% | 项目规则配置、多规则支持、团队关联 |
| **团队管理** | ✅ 100% | Agent 职责描述、工作时间、联系信息 |
| **工作流** | ✅ 100% | LLM 生成工作流、节点配置、拖拽编辑器 |
| **群组聊天** | ✅ 100% | Agent @功能、防信息风暴、SSE 实时推送 |
| **任务看板** | ✅ 100% | React 看板组件、拖拽卡片、自定义列、实时更新 |

---

### 🔄 8. ToolMemory 闭环学习 — 肌肉记忆系统（NeuCova 2.0 核心特性）

> **核心理念**：像人类肌肉记忆一样 — 看到问题 → 条件反射 → 直接执行（无需思考）

#### 完整闭环：

```
用户输入 → 肌肉记忆匹配(L1/L2/L3) → 命中→直接执行
   │                                                          │
   └────────── 传统检索兜底 ─────────→ record_tool_usage()
                                                   │
                                                   ↓
                                           肌肉记忆固化（连续成功→升级层级）
```

#### 三层记忆架构：

| 层级 | 匹配方式 | 响应速度 | 固化条件 | 遗忘条件 |
|------|---------|---------|---------|----------|
| **L1 肌肉记忆** | 关键词精确匹配 | 毫秒级（条件反射） | 连续成功2次 | 30天未用→L2 |
| **L2 热路径** | 向量相似度匹配 | 秒级（快速检索） | 累计成功5次 | 30天未用→L3 |
| **L3 工具记忆** | 关键词模糊匹配 | 需完整检索 | 初始创建 | 永不删除 |

**关键特性**：
- **条件反射**：L1 级别实现毫秒级响应，像人类肌肉记忆一样
- **自动固化**：连续成功2次→L1，累计5次→L2
- **智能遗忘**：30天未用自动降级，保持记忆系统高效
- **Skill 联动**：Skill 封装成功后自动创建 L1 肌肉记忆

---

### 🛠️ 9. 强大的工具系统 — Computer Use + CLI + Skill 生态

Neurova 提供**三位一体**的工具能力：**Computer Use（视觉理解）** + **CLI 命令库** + **Skill 生态**，让 Agent 真正拥有"手"和"工具箱"。

#### 🖥️ Computer Use — 视觉理解增强版

> 不只是"盲操作"，而是"看得见"的智能交互

Neurova 的 Computer Use 能力支持**真实模式**和**模拟模式**，并引入了**视觉理解**能力：

| 能力 | 实现方式 | 说明 |
|------|---------|------|
| **桌面截图** | Pillow (真实) / 模拟 | 全屏或区域截图，返回 base64 图像 |
| **鼠标操作** | pyautogui (真实) / 模拟 | 点击、拖拽、滚动 |
| **键盘输入** | pyautogui (真实) / 模拟 | 文本输入、快捷键 |
| **文件操作** | 真实实现 | 读写文件，受 L2 防火墙保护 |
| **Shell 命令** | subprocess | 执行系统命令，受 L2 防火墙保护 |
| **视觉解析** | YOLOv8 + EasyOCR | 截图 → UI 元素检测 → 返回结构化数据 |
| **智能点击** | 视觉理解 + pyautogui | `smart_click("登录按钮")` → 自动找到并点击 |

**视觉理解工作流程**：
```
截图 → YOLOv8 检测 UI 元素 → EasyOCR 识别文本 → 
生成标注图像 → 返回结构化数据 (elements, bbox, content)
```

**智能点击示例**：
```python
# 传统方式：需要精确坐标
computer_use.click(agent_id, x=500, y=300)

# Neurova 智能方式：基于语义目标
computer_use.smart_click(agent_id, target="登录按钮")
# → 自动截图 → 视觉解析 → 找到"登录"文本/图标 → 点击中心坐标
```

**安全机制**（L1/L2 防火墙）：
- L1：检查 Agent 是否有权访问 Computer Use
- L2：文件操作受路径白名单保护、Shell 命令黑名单过滤、输出内容脱敏

---

#### 💻 CLI 命令库 — 完整的命令行管理工具

`neurova` CLI 提供**20+ 子命令**，覆盖服务管理、配置管理、Agent 管理、认知调试等全场景：

**服务管理**：
```bash
neurova start          # 启动前后端所有服务
neurova stop          # 停止前后端所有服务
neurova restart       # 重启服务
neurova status        # 查看服务状态（后端/前端/日志）
neurova logs         # 查看服务日志（--service, --lines）
```

**配置管理**：
```bash
neurova config show          # 显示所有配置（API地址、Token、UI配置）
neurova config validate     # 验证配置是否正确
neurova config set-api-base <url>   # 设置 API 基础地址
neurova config clear-token # 清除 Token
```

**LLM 配置**：
```bash
neurova llm list                  # 列出所有 LLM 提供商
neurova llm add --name "OpenAI" --provider openai --url <url> --api-key <key>
neurova llm test <provider_id>  # 测试连接
neurova llm set-default <provider_id>
```

**Agent 管理**：
```bash
neurova agent list              # 列出所有 Agent
neurova agent add --agent-id <id> --name <name>
neurova agent show <agent_id>  # 查看详情
neurova agent delete <agent_id>
```

**认知调试**（v4.0 新增）：
```bash
neurova memory   # 记忆管理（搜索、添加、删除、统计）
neurova emotion  # 情感调试（查看状态、设置情感、测试传导）
neurova skill    # 技能管理（注册、执行、列出、卸载）
neurova evolution # 进化监控（查看人格、动机、宪法、反思）
neurova mcp      # MCP 工具管理（列出、调用、安装）
neurova dev      # 开发调试（数据库检查、缓存清理、事件监控）
neurova benchmark # 基准测试（记忆、情感、Skill 性能测试）
neurova model    # 模型适配器管理（列出、测试、设置默认）
neurova computer # Computer Use 管理（截图、点击、视觉解析）
neurova runtime  # 运行时管理（进程查看、资源监控）
neurova image    # Image 管道管理（列出、测试、预处理）
```

**其他命令**：
```bash
neurova chat            # 启动命令行聊天窗口
neurova message        # 配置接入消息渠道（WeChat/Telegram/Email/Slack）
neurova ui             # 配置 UI 服务端口
neurova user           # 配置用户账户
neurova admin          # 配置管理员账户（login/logout/whoami/change-password）
neurova update         # 检查版本更新（--auto 自动升级）
```

---

#### 🔧 Skill 生态 — 完善的技能系统

Neurova 的 Skill 系统支持**动态注册**、**事件触发**、**权限控制**、**沙箱执行**，并兼容 **OpenClaw** 和 **Qwenpaw** 协议。

**核心架构**：

```
Skill 系统
├── 内置 Skill
│   ├── 记忆管理 (memory_manage) — 添加、查询、删除记忆
│   ├── 网络搜索 (web_search) — 搜索网络信息
│   └── 文件操作 (file_operation) — 读写文件（受路径保护）
│
├── 外部 Skill
│   ├── OpenClaw 兼容 Skill
│   ├── Qwenpaw 兼容 Skill
│   └── 自定义 Skill
│
└── 复合 Skill
    ├── 链式 Skill (多 Skill 串联)
    └── 并行 Skill (多 Skill 并行)
```

**Skill 基类**（所有 Skill 必须继承）：
```python
class Skill:
    def __init__(self, name: str, description: str, tags: List[str] = None):
        self.name = name
        self.description = description
        self.status = SkillStatus.ACTIVE
    
    def execute(self, **kwargs) -> SkillResult:
        """执行 Skill，子类必须实现"""
        raise NotImplementedError
    
    def get_info(self) -> SkillInfo:
        """获取 Skill 信息"""
        return SkillInfo(...)
```

**SkillRegistry（注册中心）**：
- ✅ 注册/注销 Skill
- ✅ 别名支持（`memory` → `memory_manage`）
- ✅ 执行前后事件触发（`PRE_EXECUTE`, `POST_EXECUTE`）
- ✅ 使用统计（execution_count, last_used）
- ✅ 权限控制（按 Agent 隔离）

**事件系统**（与 ToolMemory 联动）：
```python
# 执行前事件
registry._emit_event(SkillEvent.PRE_EXECUTE, skill=skill, kwargs=kwargs)

# 执行后事件 → ToolMemory 记录成功经验
registry._emit_event(SkillEvent.POST_EXECUTE, skill=skill, result=result)
```

**Skill 执行流程**：
```
注册 Skill → 触发 PRE_EXECUTE 事件 → 执行 Skill → 
更新统计 (usage_count, last_used) → 触发 POST_EXECUTE 事件 → 
ToolMemory 记录成功经验 → 下次相似问题直接复用
```

**协议兼容**：
- ✅ OpenClaw 协议适配器（`OpenClawAdapter`）
- ✅ Qwenpaw 协议适配器（`QwenpawAdapter`）
- ✅ 统一的 Skill 接口抽象

**沙箱执行**（可选）：
- 内存限制（默认 256MB）
- CPU 限制（默认 50%）
- 超时控制（默认 30 秒）
- 网络访问控制
- 文件访问控制

---

**三位一体工具能力总结**：

| 能力 | 实现状态 | 关键特性 |
|------|---------|---------|
| **Computer Use** | ✅ 真实+模拟 | 视觉理解、智能点击、L1/L2 防火墙 |
| **CLI 命令库** | ✅ 20+ 子命令 | 服务管理、认知调试、配置管理 |
| **Skill 生态** | ✅ 完整实现 | 动态注册、事件触发、协议兼容、沙箱执行 |

> **设计理念**：工具不是附加功能，而是 Agent 的"手"和"工具箱"。Computer Use 让 Agent 能操作电脑，CLI 让管理员能高效管理，Skill 让 Agent 能动态扩展能力——三者共同构建了一个**开放、安全、可扩展**的工具生态系统。

---

### 🧠 10. 贝叶斯 EKI 认知优化器 — 无梯度的贝叶斯记忆优化

> **EKI = Ensemble Kalman Inversion（集合卡尔曼反演）**，一种**无梯度的贝叶斯推断方法**，用蒙特卡洛采样近似参数后验分布。

#### 核心算法原理

**EKI 更新公式**：
```
θ_{k+1}^(i) = θ_k^(i) + C_θy (C_yy + R)^{-1} (y - h(θ_k^(i)))
```

其中：
- `θ` = 参数向量（记忆的认知参数）
- `y` = 观测值（用户反馈、访问频率等）
- `h(θ)` = 前向模型（预测记忆强度）
- `C_θy` = 参数与观测的协方差
- `R` = 观测噪声协方差

**优势**：
- ✅ 无需梯度信息
- ✅ 用集合（ensemble）近似后验分布
- ✅ 支持高维参数空间

---

#### 12 维认知参数（每记忆）

| 参数 | 说明 | 作用 |
|------|------|------|
| `initial_strength` | 初始强度 | 记忆创建时的初始强度 |
| `decay_rate` | 衰减率 | 控制遗忘速度 |
| `reinforcement_rate` | 强化率 | 访问时的升温速度 |
| `emotion_weight` | 情感权重 | 情感对记忆的影响程度 |
| `access_count` | 访问次数 | 使用频率统计 |
| `importance` | 重要性 | 记忆的重要程度 |
| `confidence` | 置信度 | 对记忆的确定程度 |
| `reliability` | 可靠性 | 记忆的可信度 |
| `novelty` | 新颖度 | 记忆的新颖程度 |
| `relevance` | 相关性 | 与当前任务的相关性 |
| `last_access_days` | 上次访问（天） | 时间衰减计算 |
| `reinforcement_count` | 强化次数 | 被强化的总次数 |

---

#### 核心功能

##### 1. 任务价值评估（信息增益）

```python
result = optimizer.process_task(
    task_embedding=task_vector,      # 任务嵌入向量
    memory_context=['mem_1', 'mem_2'],  # 相关记忆
    user_feedback=0.8                # 用户反馈（可选）
)

# 返回：
{
    'value_score': 0.85,           # 信息增益（KL散度）
    'priority': 'high',             # 任务优先级（high/medium/low）
    'uncertainty_reduction': 0.12, # 不确定性降低
    'confidence': 0.92,            # 置信度
    'reinforcement_needed': True     # 是否需要强化
}
```

**优先级分类**（基于信息增益）：
- `high`：信息增益 > 0.7 → 推荐强化相关记忆
- `medium`：信息增益 0.3-0.7
- `low`：信息增益 < 0.3 → 降低记忆优先级

##### 2. 记忆强度估计

```python
strength, uncertainty = optimizer.get_memory_strength('mem_123')
# 返回：
# strength = 75.3 (强度均值)
# uncertainty = 8.2 (强度标准差)
```

##### 3. 衰减预测

```python
decay_curve = optimizer.predict_decay('mem_123', horizon=7)
# 返回未来7天的衰减曲线：
[
    {'day': 0, 'strength': 75.3, 'uncertainty': 8.2, 'needs_reinforcement': False},
    {'day': 1, 'strength': 71.5, 'uncertainty': 9.1, 'needs_reinforcement': False},
    ...
    {'day': 7, 'strength': 58.2, 'uncertainty': 12.3, 'needs_reinforcement': True}
]
```

##### 4. 强化推荐

```python
recommendations = optimizer.recommend_reinforcement(top_k=10)
# 返回强度最低的10个记忆：
[
    {'memory_id': 'mem_456', 'strength': 25.3, 'priority': 'high', ...},
    ...
]
```

---

#### 完整工作流程

```
用户查询
    ↓
1. 任务嵌入 (task_embedding)
    ↓
2. EKI处理任务 (process_task)
    ├── 计算信息增益 (KL散度）
    ├── 评估任务优先级 (high/medium/low)
    └── 更新认知状态 (贝叶斯推断）
    ↓
3. 记忆召回 (根据相关性）
    ↓
4. 强化推荐 (推荐低强度记忆）
    ↓
5. 衰减预测 (预测未来衰减）
    ↓
6. 批量更新 (异步更新认知参数）
```

---

#### 与记忆温度机制的关系

| 维度 | 记忆温度机制 | 贝叶斯EKI优化器 |
|------|--------------|----------------|
| **核心** | 模拟遗忘曲线 | 贝叶斯推断优化 |
| **参数** | 单一温度值 (0-100°C) | 12维认知参数 |
| **更新** | 规则启发式 | 数学严谨的贝叶斯更新 |
| **预测** | 简单线性衰减 | 不确定性量化的衰减曲线 |
| **决策** | 温度阈值 | 信息增益 + KL散度 |

**协同工作**：
```
温度机制（快速筛选） → EKI优化器（精确决策）
     ↓                           ↓
  高温记忆优先召回        评估任务价值、推荐强化
```

---

#### 实际应用场景

1. **智能记忆巩固**：预测哪些记忆即将衰减，提前强化
2. **任务价值评估**：优先处理高信息增益的任务
3. **个性化记忆管理**：每个Agent独立的认知参数
4. **不确定性量化**：知道"哪些记忆不可靠"

---

#### 核心文件结构

```
neurova/cognitive_layers/memory_layer/bayesian_eki/
├── __init__.py
├── ensemble_kalman_inversion.py      # 核心EKI算法
├── cognitive_optimizer.py             # 认知优化器（主编排器）
├── information_gain.py               # 信息增益计算（KL散度）
├── representative_sampler.py          # 嵌入式代表性采样
├── surrogate_model.py                # 高斯过程代理模型
├── memory_state.py                   # 记忆认知状态管理
└── EKI_UPGRADE_GUIDE.md          # 升级指南
```

> **设计理念**：温度机制是"快速筛选器"，EKI是"精确决策器"——前者用简单规则快速判断记忆热度，后者用严谨数学优化记忆管理决策，两者协同构建完整的认知优化系统。

---

### 🚀 11. 工具层架构 — LLM Router + Context Pool + Tool Memory

Neurova 的工具层不是简单的工具集合，而是一个**统一的智能编排系统**，包含三大核心组件：

#### 🎯 LLM Router — 多模态自适应路由器

> 根据请求类型自动选择最佳LLM模型，支持10种请求类型和10种模型能力

**核心能力**：
```python
# 自动检测请求类型并选择模型
request_type = detect_request_type("帮我画一张夕阳下的海滩")
# → RequestType.TEXT_TO_IMAGE

result = router.select_model(request_type)
# → 自动选择支持图片生成的模型（如通义万相、DALL-E 3）
```

**请求类型支持**：
| 请求类型 | 说明 | 匹配能力 |
|----------|------|----------|
| `CHAT` | 文本聊天 | TEXT |
| `IMAGE_UNDERSTANDING` | 图像理解 | VISION |
| `AUDIO_UNDERSTANDING` | 音频理解 | AUDIO |
| `VIDEO_UNDERSTANDING` | 视频理解 | VIDEO |
| `TEXT_TO_IMAGE` | 文生图 | IMAGE_GENERATION |
| `IMAGE_TO_IMAGE` | 图生图 | IMAGE_GENERATION |
| `TEXT_TO_VIDEO` | 文生视频 | VIDEO_GENERATION |
| `IMAGE_TO_VIDEO` | 图生视频 | VIDEO_GENERATION |
| `TEXT_TO_SPEECH` | 语音合成 | TTS |
| `SPEECH_TO_TEXT` | 语音识别 | STT |

**选择算法**：
1. **能力匹配**：过滤掉不支持所需能力的模型
2. **健康检查**：跳过不健康的提供商
3. **优先级排序**：按优先级权重排序
4. **响应时间优化**：优先选择响应快的模型
5. **权重评分**：综合评分选择最佳模型

#### 🧠 Context Pool — 统一上下文管理

> 10种上下文来源、4层压缩策略、多模型格式自动转换

**上下文来源**：
```python
class ContextSource(Enum):
    SYSTEM_INSTRUCTION = "system_instruction"  # 系统指令
    DEVELOPER_INSTRUCTION = "developer_instruction"  # 开发者指令
    MEMORY = "memory"  # 记忆检索结果
    CONVERSATION = "conversation"  # 对话历史
    EXPERIENCE = "experience"  # 经验知识
    EMOTION = "emotion"  # 情感状态
    REFLECTION = "reflection"  # 反思日志
    TOOL_CALL = "tool_call"  # 工具调用结果
    MULTIMODAL = "multimodal"  # 多模态内容
    USER_INPUT = "user_input"  # 用户输入
```

**核心组件**：
- **ContextCollector**：优先级排序 + Token预算分配
- **ContextConverter**：OpenAI ↔ Anthropic 格式自动转换
- **ContextCompressor**：截断/摘要压缩
- **ContextPool**：统一接口，build_context_for_model()

**格式自动转换**：
```python
# 根据模型名称自动选择格式
context = pool.build_context_for_model("gpt-4")  # → OpenAI格式
context = pool.build_context_for_model("claude-3-opus")  # → Anthropic格式
```

#### 💪 Tool Memory — 肌肉记忆系统

> 三层记忆架构，实现毫秒级工具调用响应

**三层架构**：
| 层级 | 匹配方式 | 响应速度 | 固化条件 | 遗忘条件 |
|------|---------|---------|---------|----------|
| **L1 肌肉记忆** | 关键词精确匹配 | 毫秒级 | 连续成功2次 | 30天未用→L2 |
| **L2 热路径** | 向量相似度匹配 | 秒级 | 累计成功5次 | 30天未用→L3 |
| **L3 工具记忆** | 关键词模糊匹配 | 需完整检索 | 初始创建 | 永不删除 |

**闭环学习**：
```
用户输入 → 肌肉记忆匹配(L1/L2/L3) → 命中→直接执行
   │                                                          │
   └────────── 传统检索兜底 ─────────→ record_tool_usage()
                                                   │
                                                   ↓
                                           肌肉记忆固化（连续成功→升级层级）
```

**动态置信度阈值**：
```python
# 根据工具权重动态计算置信度阈值
threshold = base_confidence / sqrt(weight_factor)

# 高权重工具(2.5) → 阈值0.51 (更容易自动执行)
# 低权重工具(0.3) → 阈值1.0 (更难自动执行)
```

#### 🔌 MCP 集成 — 外部工具无缝接入

> 支持 Model Context Protocol，连接外部工具服务器

**使用方式**：
```bash
# 列出已连接的 MCP Server
neurova mcp list

# 连接新的 MCP Server
neurova mcp connect my-server --command "python server.py" --args "--port 8080"

# 查看 MCP Server 提供的工具
neurova mcp tools my-server
```

**安全机制**：
- 用户层隔离：每个用户的 MCP 配置独立
- 工具权限控制：按 Agent 隔离工具访问权限
- 沙箱执行：MCP 工具在沙箱环境中执行

#### 🎛️ 统一工具编排 — Tool Orchestrator

> 统一管理所有工具，支持链式调用、并行执行、错误恢复

**工具类别**：
| 类别 | 工具 | 说明 |
|------|------|------|
| **搜索类** | web_search, knowledge_search | 网络搜索、知识库检索 |
| **计算类** | calculator, code_executor | 计算器、代码执行器 |
| **文件类** | file_read, file_write | 文件读写、知识库管理 |
| **通信类** | message_send, notification_push | 消息发送、通知推送 |
| **数据分析类** | data_visualization, report_generator | 数据可视化、报表生成 |
| **Computer Use** | screenshot, click, type, scroll | 桌面操作、视觉理解 |

**编排能力**：
- **链式调用**：多工具串联执行（A → B → C）
- **并行执行**：多工具同时执行，提升效率
- **错误恢复**：失败自动重试或降级
- **动态调度**：根据资源状态和优先级动态调整

> **设计理念**：工具层不是孤立的工具集合，而是一个**智能的工具生态系统**。LLM Router 自动选择最佳模型，Context Pool 智能管理上下文，Tool Memory 实现毫秒级响应，MCP 集成外部工具，Tool Orchestrator 统一编排——五大组件协同工作，让 Agent 真正拥有"手"和"大脑"。

---

### 🌊 12. 活水上下文池 — 语义匹配的智能上下文管理

> **核心理念**：上下文不是"死水"，而是"活水"——流动性、新鲜度、纯净性、语义性、按需性

#### 🌊 活水模型比喻

```
水源（输入）                    水池（存储）                    取水（输出）
────────────────────────────────────────────────────────────────────────────
对话历史 ──┐               ┌───────────────────┐           ┌─────────────┐
记忆检索 ──┼─→ [去重+标签] → [活水上下文池]      → [向量匹配] → [按需取水] → LLM
情感状态 ──┤               │  水滴 = 内容+标签  │           └─────────────┘
工具结果 ──┘               │  向量 = 语义编码   │
                          │  需求 = 字符串     │
                          └───────────────────┘
                                    ↑
                              UnifiedVectorStore
                            (BAAI/bge-small-zh-v1.5)
```

#### 🌊 五大活水特性

| 特性 | 说明 | 实现方式 |
|------|------|----------|
| **流动性** | 新内容不断流入，旧内容自然流出 | 时间衰减 + TTL过期 |
| **新鲜度** | 基于时间衰减，保持内容新鲜 | 创建时间戳 + 访问频率 |
| **纯净性** | 多阶段去重机制，避免重复污染 | 精确去重 + 模式去重 + 语义去重 |
| **语义性** | 向量语义匹配，理解同义词、近义词 | BAAI/bge-small-zh-v1.5 嵌入 |
| **按需性** | 需求即字符串，自动匹配带标签的水滴 | 语义向量相似度匹配 |

#### 🔄 多阶段去重机制

**去重阶段**：
```python
class DriftSafeDeduplicator:
    """防漂移去重器 - 多阶段去重，保留关键上下文"""
    
    def dedup(self, drops: List[ContextInput], stage: str = 'input') -> List[ContextInput]:
        """
        多阶段去重
        
        阶段1: 精确去重 (Exact Deduplication)
        - 完全相同的内容 → 保留最新版本
        - 安全，不会丢失信息
        
        阶段2: 模式去重 (Pattern Deduplication)  
        - 相同来源 + 相似内容模式 → 保留关键信息
        - 针对特定来源优化
        
        阶段3: 语义去重 (Semantic Deduplication)
        - 相似语义内容 → 合并或保留最相关
        - 使用向量相似度阈值 (0.85-0.95)
        """
```

**安全去重策略**：
1. **精确去重优先**：完全相同的内容只保留一份
2. **保留关键信息**：去重时保留关键上下文
3. **上下文感知去重**：根据当前查询决定去重策略

#### 🎯 语义向量匹配取水

```python
# 用户需求 → 语义向量 → 匹配水滴
query = "用户之前提到的项目进度怎么样？"
query_embedding = vector_store.encode(query)

# 从活水池中匹配相关水滴
relevant_drops = pool.search_by_semantic(
    query_embedding=query_embedding,
    top_k=10,
    min_similarity=0.7
)

# 按相关性排序，返回最相关的上下文
context = pool.build_context(relevant_drops)
```

#### ⚖️ Token预算管理

**动态预算分配**：
```python
# 根据模型类型分配Token预算
model_budgets = {
    "gpt-4": 32000,        # GPT-4: 32K tokens
    "claude-3-opus": 200000,  # Claude: 200K tokens
    "deepseek-chat": 32000,   # DeepSeek: 32K tokens
}

# 优先级分配策略
budget_allocation = {
    "system_instruction": 0.2,  # 20% 预算给系统指令
    "memory": 0.3,              # 30% 预算给记忆检索
    "conversation": 0.4,        # 40% 预算给对话历史
    "experience": 0.1,          # 10% 预算给经验知识
}
```

#### 🛡️ 防漂移机制

**LLM漂移风险**：
1. **语义去重阈值过高**：去除看似重复但实际有区别的内容
2. **时间序列破坏**：去重打乱了对话的时间顺序
3. **上下文缺失**：去重导致关键上下文丢失

**防漂移策略**：
```python
# 1. 保留对话对完整性
def preserve_conversation_pairs(drops):
    """确保 user/assistant 对话对完整"""
    # 不分离 user 和 assistant 的消息
    
# 2. 时间序列保护
def protect_timeline(drops):
    """保护时间序列完整性"""
    # 按时间戳排序，不打乱顺序
    
# 3. 关键上下文保留
def preserve_key_context(drops, query):
    """保留与查询相关的关键上下文"""
    # 相关内容使用更严格的去重阈值
```

#### 📊 实际应用场景

1. **长对话管理**：自动去重重复内容，保留关键上下文
2. **多轮对话**：跨会话记忆检索，语义匹配相关历史
3. **工具调用结果**：智能压缩工具返回的大量数据
4. **多模态内容**：统一管理文本、图片、音频、视频上下文
5. **模型切换**：自动转换上下文格式（OpenAI ↔ Anthropic）

#### 🔧 API 集成

```python
# 获取上下文池设置
GET /api/v1/context/pool-settings

# 更新上下文池设置
PUT /api/v1/context/pool-settings

# 获取特定模型的Token预算
GET /api/v1/context/pool-settings/token-budget/{model_name}

# 测试Token预算计算
POST /api/v1/context/pool-settings/test-budget
```

> **设计理念**：活水上下文池不是简单的上下文缓存，而是一个**智能的上下文生态系统**。它像活水一样流动，像大脑一样思考，像水库一样调节——通过语义匹配理解用户需求，通过多阶段去重保持纯净，通过Token预算管理资源，通过防漂移机制保证质量。这是Neurova独有的上下文管理创新。

---

## 目录

- [NeuCova 独特特点](#-neucova-独特特点)
  - [1. 每一颗 Agent 都是独特的星星](#1-每一颗-agent-都是独特的星星)
  - [2. 17 维记忆分类体系](#2-17-维记忆分类体系)
  - [3. 记忆温度机制](#3-记忆温度机制)
  - [4. 情感中枢引擎](#4-情感中枢引擎-v30--四层17种情感体系)
  - [5. CogArch 2.0 认知架构](#5-cogarch-20-认知架构)
  - [6. 持续进化能力](#6-持续进化能力)
  - [7. 多 Agent 团队协作](#7-多-agent-团队协作)
  - [8. ToolMemory 闭环学习](#8-toolmemory-闭环学习)
  - [9. 强大的工具系统](#9-强大的工具系统--computer-use--cli--skill-生态)
  - [10. 贝叶斯 EKI 认知优化器](#10-贝叶斯-eki-认知优化器)
  - [11. 工具层架构 — LLM Router + Context Pool + Tool Memory](#11-工具层架构--llm-router--context-pool--tool-memory)
  - [12. 活水上下文池 — 语义匹配的智能上下文管理](#12-活水上下文池--语义匹配的智能上下文管理)
- [🧪 Neutesting 测试框架](#️-neutesting-测试框架)
  - [测试覆盖率统计](#测试覆盖率统计)
  - [已修复的 Bug](#已修复的-bug)
  - [快速运行测试](#快速运行测试)
  - [测试目录结构](#测试目录结构)
  - [更新日志](#更新日志)
- [核心能力详解](#核心能力详解)
  - [记忆智能增强层](#记忆智能增强层)
  - [主动回忆机制](#主动回忆机制)
  - [记忆压缩机制](#记忆压缩机制)
  - [向量 + FTS5 混合检索](#向量--fts5-混合检索)
  - [经验总结 — 越用越聪明](#经验总结--越用越聪明)
  - [智能体创造性工作](#智能体创造性工作)
  - [工作编排](#工作编排)
- [安全守护](#安全守护)
- [多平台连接](#多平台连接)
- [v4.0 升级功能](#v40-升级功能)
- [技术架构](#技术架构)
- [快速开始](#快速开始)
- [技术栈](#技术栈)

---

## 🧪 Neutesting 测试框架

**Neutesting** 是 Neurova 项目的官方测试框架，提供完整的测试金字塔覆盖。

### 测试覆盖率统计

| 模块 | 测试数 | 状态 |
|------|--------|------|
| core | 68 | ✅ 全部通过 |
| memory | 165 | ✅ 164通过, 1跳过 |
| security | 41 | ✅ 全部通过 |
| admin | 56 | ✅ 全部通过 |
| api | 12 | ✅ 全部通过 |
| auth | 12 | ✅ 全部通过 |
| projects | 19 | ✅ 全部通过 |
| channels | 11 | ✅ 全部通过 |
| execution | 9 | ✅ 全部通过 |
| skills | 9 | ✅ 全部通过 |
| cognitive | 9 | ✅ 全部通过 |
| llm | 7 | ✅ 全部通过 |
| **总计** | **419** | **✅ 418 通过, 1 跳过 (99.8%)** |

### 已修复的 Bug

#### Memory 模块 Bug 修复

1. **死锁修复** - `MemoryStorage.get_stats()`
   - 问题: 在 `with self._lock` 内部调用 `self.count()`，非重入锁导致死锁
   - 修复: 直接执行 SQL 查询，避免重复加锁

2. **API 不匹配修复** - `MemoryManager.stats()` / `get_full_stats()`
   - 问题: 调用不存在的 `store.stats()` 方法
   - 修复: 改为调用 `store.get_stats()`

3. **API 不匹配修复** - `MemoryManager.relate()`
   - 问题: 调用不存在的 `store.relate()` 方法
   - 修复: 改为调用 `store.add_relation()`

4. **API 不匹配修复** - `MemoryManager.recall_graph()`
   - 问题: 调用不存在的 `store.get_graph()` 方法
   - 修复: 改为调用 `store.get_related_memories_graph()`

5. **类型不匹配修复** - `MemoryManager.remember()` / `analyze_emotion()`
   - 问题: `emotion_scores` 期望 dict，但 `emo.analyze()` 返回 tuple
   - 修复: 添加类型检查和转换逻辑

6. **缺失方法添加** - `EmotionAnalyzer.get_emotion_distribution()`
   - 在 `EmotionAnalyzer`、`EmotionAnalyzerAdapter`、`EmotionHubEngine` 三层添加该方法

#### 其他模块 Bug 修复

- `ModuleSystem` API 重写 - 修正了 `Module`、`ModuleInfo`、`DependencyResolver` 的导入和使用
- `LogManager` - 添加 `set_default_level(LogLevel.DEBUG)` 确保日志级别测试正确
- `ConfigManager` - 修复单例模式下的状态隔离问题

### 快速运行测试

```bash
# 运行所有单元测试
pytest tests/unit/ -v

# 运行特定模块测试
pytest tests/unit/core/ -v
pytest tests/unit/memory/ -v

# 生成覆盖率报告
pytest tests/unit/ --cov=neurova --cov-report=html
```

### 测试目录结构

```
tests/
├── unit/                    # 单元测试层 (419 测试)
│   ├── core/               # 核心模块测试 (68 测试)
│   ├── memory/             # Memory 模块测试 (165 测试)
│   ├── security/           # 安全模块测试
│   ├── admin/              # 管理模块测试
│   ├── api/               # API 模块测试
│   ├── auth/              # 认证模块测试
│   ├── projects/          # 项目模块测试
│   ├── channels/          # 通道模块测试
│   ├── execution/         # 执行模块测试
│   ├── skills/            # 技能模块测试
│   ├── cognitive/         # 认知模块测试
│   └── llm/              # LLM 模块测试
├── integration/            # 集成测试层
├── e2e/                   # 端到端测试层
└── performance/           # 性能测试层
```

详细文档请查看 [tests/README.md](tests/README.md)

### 更新日志

#### v1.1.0 (2026-05-20)
- ✅ 修复 Memory 模块 9 个 bug
- ✅ 单元测试通过率: 418/419 (99.8%)
- ✅ 添加 memory 子目录结构测试
- ✅ 修复 EmotionAnalyzer 类型不匹配问题
- ✅ 添加缺失的 `get_emotion_distribution()` 方法

#### v1.0.0 (2026-05-20)
- 🎉 Neutesting 框架初始版本
- ✅ 四层测试体系完整实现
- ✅ CI/CD 自动化集成

---

## 核心能力详解

### 记忆智能增强层 — 9 大认知机制

| 机制 | 说明 |
|------|------|
| **冲突检测** | 识别矛盾记忆，自动标记并处理 |
| **睡眠整理** | 定期提炼洞察、发现规律、生成摘要 |
| **联想能力** | 基于关联图谱实现"突然想到"的联想链式回忆 |
| **元认知** | 知道自己"记得什么"和"不记得什么" |
| **情感衰减** | 情感强度独立于内容衰减，避免 AI "记仇" |
| **视角标记** | 区分"事实"/"观点"/"推断"，避免混淆 |
| **可解释性** | 能解释"为什么我记得这个"（触发链追溯） |
| **遗忘恢复** | 从归档/删除状态恢复记忆 |
| **记忆合并** | 相似记忆自动聚类去重，生成智能摘要 |

### 主动回忆机制 — "突然想起来"

传统 Agent 只能被动检索，Neurova 实现了 **主动回忆**：

- **上下文触发回忆**：当前对话内容触发相关记忆
- **定时回忆巩固**：在遗忘曲线关键点主动回忆，防止遗忘
- **联想链式回忆**：A→B→C 的链式联想，发现隐藏关联
- **情感共鸣触发**：当前情感状态触发相似情感记忆

### 记忆压缩机制 — 应对记忆膨胀

| 层次 | 说明 | 压缩率 |
|------|------|--------|
| 原始层 | 完整对话/内容 | 100% |
| 摘要层 | 关键信息摘要 | ~10% |
| 主题层 | 主题/趋势总结 | ~3% |

### 向量 + FTS5 混合检索

- **向量检索**（主）：基于语义相似度（FAISS）
- **FTS5 全文检索**（辅）：关键词精确匹配
- **RRF 混合排序**：Reciprocal Rank Fusion 融合结果

**特色机制**：
- 记忆**自动分类** — 对话结束后智能归类，无需手动整理
- 记忆**批量持久化** — 20 轮对话或 128KB 内自动触发写入
- 记忆**图谱可视化** — 节点与边的关系一目了然
- 记忆**版本控制** — 修改记录完整保留，支持历史回溯
- 记忆**永不丢失** — 每次会话都是上一次的自然延续

---

### 经验总结 — 越用越聪明

Neurova 独有的 **经验知识库 (Experience Knowledge Base)** 让 Agent 真正具备"从经验中学习"的能力。

**学习闭环**：

```
执行任务 → 记录结果 → 效果评估 → 提取经验 → 智能推荐 → 指导下次执行
```

**核心机制**：

- **经验记录** — 每次任务执行后自动记录方法、效果和上下文
- **效果评估** — 多维评分系统评估经验质量（成功率、效率、用户满意度）
- **智能推荐** — 遇到相似场景时自动推荐最佳经验
- **统计分析** — 跨时间维度分析经验进化趋势
- **经验复用** — 成功经验自动提升权重，失败经验标记避免重复

**一个例子**：
当你第三次让 Agent 帮你整理周报时，它会回忆前两次的经验——第一次你改了格式，第二次你调整了内容结构——然后自动用你最喜欢的样式和逻辑完成工作。

---

### 智能体创造性工作 — 让 Agent 为你创作

Neurova 将**对话与创作无缝融合**。你不需要切换到专门的"创作工具"，在自然对话中就能完成从灵感到成品的全过程。

**对话中的多模态创作**：

| 能力 | 支持范围 | 使用场景 |
|------|---------|----------|
| 🎨 **文生图** | 通义万相、DALL-E 3、Stable Diffusion | "帮我画一张..." 对话中直接出图 |
| 🎬 **文生视频** | 文本转视频 | "帮我把这个想法做成视频..." |
| 🔄 **图生图** | 风格迁移、图像编辑 | "把这张照片改成动漫风格" |
| 📸 **图生视频** | 静态图转动态 | "让这张照片动起来" |
| 🎞️ **首尾帧生成** | 关键帧插值生成视频 | "从画面A过渡到画面B" |
| 🔁 **视频生视频** | 视频风格转换 | "把这个视频改成赛博朋克风格" |

**创作工作流**：
- 对话中自然描述需求，Agent 理解意图后调用对应生成能力
- 支持异步任务，大文件生成不影响继续对话
- 实时进度查询，生成完成后主动通知
- 结果直接返回图片/视频 URL，无需离开对话界面

---

### 工作编排 — 复杂任务的自动化指挥

Neurova 的**工作流引擎**让你可以搭建从简单到复杂的自动化流程，Agent 自动按编排执行。

**工作流节点类型**：

```
[开始] → [任务A] → [条件判断] ─┬─ 是 → [任务B] → [子流程] → [结束]
                                │
                                └─ 否 → [任务C] → [结束]
```

**节点类型**：

| 节点 | 功能 |
|------|------|
| 🟢 **开始/结束** | 流程起止点 |
| 📋 **任务节点** | 单个可执行任务 |
| 🔀 **条件节点** | 根据结果分支路由 |
| ⚡ **并行节点** | 多任务同时执行 |
| 🔗 **子流程** | 嵌套工作流 |

**编排能力**：
- **可视化 DSL** — 用简洁的语言描述工作流，Agent 自动解析执行
- **状态追踪** — 每一步的执行状态、耗时、结果全部可查
- **异常处理** — 失败自动重试或降级，保证流程可靠性
- **动态调度** — 根据资源状态和优先级动态调整执行顺序
- **历史回溯** — 每次工作流执行的完整记录

---

## 安全守护

Neurova 的每一颗星星都需要被守护。我们内置了三层安全防火墙：

| 层级 | 保护内容 |
|------|---------|
| **L0 入口守护** | JWT 认证、IP 黑白名单、速率限制、输入安全扫描 |
| **L1 隔离守护** | 用户间硬隔离（不可关闭）、Agent 间可选隔离 |
| **L2 输出守护** | API Key 脱敏、敏感路径拦截、文件类型保护 |

**你的每一颗星星都安全地属于你，任何人都无法窥探。**

### 用户隔离机制

所有数据均按用户隔离：

| 数据类型 | 隔离方式 |
|----------|----------|
| 记忆数据 | 按 `neuser_id` + `user_id` 隔离 |
| API Key 配置 | 按 `user_id` 隔离 |
| 知识库 | 按 `user_id` 隔离 |
| 文档 | 按 `user_id` + 知识库隔离 |
| 进化进度 | 按 `user_id` 隔离 |

---

## 多平台连接

Agent 星星可以连接到你使用的各种平台：

- **Web 对话** — 内建对话界面
- **REST API** — 标准接口集成
- **Telegram** — 即时通讯接入
- **微信** — 公众号/企业微信
- **Discord** — 社群平台
- **Webhook** — 任意外部系统

---

## v4.0 升级功能

> Neurova v4.0 基于 CUA (Computer Use Agent) 架构启发，进行了全面的升级和改进。

### 🚀 P0 - 生态级改进

#### 1. MCP Client 集成
- **功能**：支持 Model Context Protocol (MCP)，连接外部工具服务器
- **隔离层级**：用户层
- **使用方式**：
  ```bash
  # 列出已连接的 MCP Server
  neurova mcp list
  
  # 连接新的 MCP Server
  neurova mcp connect my-server --command "python server.py" --args "--port 8080"
  
  # 断开 MCP Server
  neurova mcp disconnect my-server
  
  # 查看 MCP Server 提供的工具
  neurova mcp tools my-server
  ```

#### 2. 模型适配器工厂
- **功能**：支持多种 LLM 提供商（OpenAI、Anthropic、Custom 等）
- **隔离层级**：全局
- **使用方式**：
  ```bash
  # 列出所有模型适配器
  neurova model list
  
  # 添加模型适配器
  neurova model add my-openai --type openai --endpoint "https://api.openai.com/v1"
  
  # 删除模型适配器
  neurova model remove my-openai
  
  # 测试模型适配器
  neurova model test my-openai --prompt "Hello!"
  ```

### 🎯 P1 - 体验级改进

#### 3. Agent 声明式构建器
- **功能**：通过声明式 API 快速构建和配置 Agent
- **隔离层级**：工具全局 + 产物用户层
- **使用方式**：
  ```python
  from neurova.agent.builder import AgentBuilder
  from neurova.agent.templates.personality_templates import PersonalityTemplate
  
  agent = (AgentBuilder("alice")
      .personality(PersonalityTemplate.WARM_COMPANION)
      .skill("code_review")
      .memory(types=["conversation", "emotional"])
      .emotion(baseline="joy")
      .constitution(rules=["永远保持善意"])
      .model("deepseek-v4-flash")
      .build(user_id="user_42")
  ```

#### 4. 思维沙箱
- **功能**：为 Agent 提供隔离的思考空间，支持假设推理和反思
- **隔离层级**：Agent 层
- **使用方式**：
  ```bash
  # 创建沙箱会话
  neurova dev sandbox create my_session
  
  # 在沙箱中运行推理
  neurova dev sandbox run my_session --input "用户问题"
  
  # 查看沙箱状态
  neurova dev sandbox status my_session
  ```

#### 5. CLI 工具链增强
- **记忆管理**：`neurova memory`
- **情感调试**：`neurova emotion`
- **技能管理**：`neurova skill`
- **进化监控**：`neurova evolution`
- **MCP 工具管理**：`neurova mcp`
- **开发调试**：`neurova dev`

### 💡 P2 - 能力级突破

#### 6. Computer Use 能力
- **功能**：让 Agent 能够操作计算机（截图、点击、输入、滚动、文件操作、Shell 命令）
- **隔离层级**：全局共享 + L1/L2 防火墙
- **使用方式**：
  ```bash
  # 截图
  neurova computer screenshot my_session
  
  # 点击
  neurova computer click my_session --x 100 --y 200
  
  # 输入文本
  neurova computer type my_session --text "Hello, World!"
  
  # 滚动
  neurova computer scroll my_session --dx 0 --dy -100
  
  # 文件操作
  neurova computer file read /path/to/file
  neurova computer file write /path/to/file --content "内容"
  
  # Shell 命令
  neurova computer shell "ls -la"
  ```

#### 7. 运行时+传输层双抽象
- **功能**：支持多种运行时（本地、Docker）和传输层（HTTP、WebSocket）
- **隔离层级**：全局
- **使用方式**：
  ```bash
  # 列出所有运行时
  neurova runtime list
  
  # 启动运行时
  neurova runtime start my_runtime --type local
  
  # 停止运行时
  neurova runtime stop my_runtime
  
  # 执行命令
  neurova runtime execute my_runtime --command "python script.py"
  ```

#### 8. Image 定义管道
- **功能**：支持自定义镜像构建，用于 Agent 运行环境
- **隔离层级**：全局
- **使用方式**：
  ```bash
  # 列出所有镜像
  neurova image list
  
  # 构建镜像
  neurova image build my-image --base python:3.11 --python 3.11
  
  # 删除镜像
  neurova image delete my-image
  ```

### 📊 P3 - 质量体系

#### 9. 基准测试框架
- **功能**：对 Agent 进行多维度评测（准确性、响应时间、资源消耗等）
- **隔离层级**：用户层 + Agent 层
- **使用方式**：
  ```bash
  # 运行基准测试
  neurova benchmark run --suite recall --agent-id my_agent
  
  # 查看测试结果
  neurova benchmark results --test-id test_123
  
  # 对比多个 Agent
  neurova benchmark compare --agent-ids agent1,agent2,agent3 --metric accuracy
  ```

### API 端点

所有 v4.0 功能都提供了完整的 RESTful API：

| 功能 | 端点前缀 |
|------|-----------|
| MCP Client | `/api/v1/tool-layers/mcp` |
| 模型适配器 | `/api/v1/model-adapter` |
| Agent 构建器 | `/api/v1/builder` |
| 思维沙箱 | `/api/v1/sandbox` |
| Computer Use | `/api/v1/computer` |
| 运行时管理 | `/api/v1/runtime` |
| Image 管道 | `/api/v1/image` |
| 基准测试 | `/api/v1/benchmark` |

---

## 技术架构

### 系统架构全景

```
Neurova
├── 认知层 (Cognitive Layer) ⭐ 核心独创
│   ├── 记忆系统 (Memory System)         — 17种分类、温度机制、9大认知机制
│   ├── 情感中枢引擎 (Emotion Hub Engine) — 四层17种情感、情感传导、加权决策
│   ├── 自我进化引擎 (Evolution Engine)  — 人格系统、动机系统、宪法系统、反思系统
│   ├── 意图理解 (Intent Understanding)
│   └── 心流知识库适配器 (Knowledge Adapter)
│
├── 执行层 (Execution Layer)
│   ├── 多 Agent 协作 (Multi-Agent)      — 四种协作模式、团队管理
│   ├── 消息路由 (Message Routing)
│   └── 任务调度 (Task Scheduling)
│
├── 工具层 (Tool Layer)
│   ├── Skill 系统 (Skill System)        — 中央注册表、版本管理、热插拔
│   ├── 插件系统 (Plugin System)
│   └── 外部 API 集成
│
└── 接口层 (Interface Layer)
    ├── Console 管理后台 (React + TypeScript + Vite)
    ├── NeuUI (React + TypeScript + Vite)
    └── 多渠道接入 (WeChat/Telegram/Email/Slack/Discord/Webhook)
```

### 上下文缓存与智能压缩

为应对长上下文和高频访问场景，Neurova 实现了完整的上下文缓存与压缩系统。

| 模块 | 功能 |
|------|------|
| **智能上下文缓存** (`context_cache.py`) | 优先读缓存、批量写入、LRU 淘汰、内存限制 |
| **智能压缩** (`context_compressor.py`) | 会话完整性保护、分层压缩、Token 预算管理 |
| **记忆读写管理** (`memory_rw_manager.py`) | 缓冲写入、批量提交、温度衰减 |
| **增强版上下文构建器** (`enhanced_context_builder.py`) | 整合缓存、压缩和记忆管理 |

**压缩策略**：

```
记忆压缩:
  - 固化记忆: 100% 保留
  - 高温记忆(>70): 保留
  - 中温记忆(40-70): 压缩为摘要
  - 低温记忆(<40): 移除

历史压缩:
  - 最近 N 轮: 完整保留
  - 较早对话: 压缩为摘要
  - 保证 user/assistant 对话对完整
```

### 工具与 Skill 系统

#### Skill 协议兼容层

Neurova 的 Skill 系统支持 **多协议兼容**：

- **OpenClaw 兼容**：支持 OpenClaw Skill 协议
- **Qwenpaw 兼容**：支持通千问 paw Skill 协议
- **自定义 Skill**：开放的 Skill 定义规范

#### Skill Registry 中央注册表

**独创设计**：采用 Singleton 模式 + 线程安全的中央注册表：

- 统一的 Skill 注册/注销管理
- Hook 系统：支持启动/关闭 Hook，按优先级执行
- 动态加载/卸载：运行时热加载 Skill，无需重启

#### Skill 版本管理

**完整版本管理功能**：

- **版本检测**：系统启动时自动检测技能市场的新版本
- **通知机制**：
  - 公共技能池 → 提醒管理员手动更新
  - 用户专属技能池 → 通知用户手动更新
  - Agent 专属技能池 → **自动更新**（无需通知）
- **版本同步规则**：
  - 公共池更新 → 自动同步到所有用户/Agent 专属池
  - 用户专属池更新（不在公共池）→ 自动同步到该用户的所有 Agent 池

#### 工具模块特点

| 特点 | 说明 |
|------|------|
| **热插拔** | 插件/工具可在运行时动态启用/禁用 |
| **沙箱执行** | Skill 在沙箱环境中执行，保障安全性 |
| **链式调用** | 支持多 Skill 串联执行（Pipeline） |
| **并行调用** | 支持多 Skill 并行执行，提升效率 |
| **版本控制** | Skill 版本管理和回滚 |
| **依赖管理** | 自动解析和加载 Skill 依赖 |

#### 内置工具类别

- **搜索类**：Web 搜索、知识库检索
- **计算类**：计算器、代码执行器
- **文件类**：文件读写、知识库管理
- **通信类**：消息发送、通知推送
- **数据分析类**：数据可视化、报表生成

### 心流知识库 & RAG 增强

Neurova 支持连接**心流知识库**，为 AI 助手提供外部知识接入能力。

| 能力 | 说明 |
|------|------|
| 📚 **外部知识接入** | 连接心流知识库，管理海量文档 |
| 🔍 **语义检索** | 基于向量搜索的智能语义匹配 |
| 🔗 **记忆同步** | 知识库与记忆系统双向联动 |
| 🧬 **认知进化** | 自动发现知识盲点，主动学习成长 |
| 🤖 **RAG 增强** | 为 Agent 提供知识增强的上下文 |

**RAG 工作流程**：

```
用户问题
   ↓
┌─────────┐     ┌─────────┐
│ 知识库  │────►│  检索   │◄── 你的问题
│  检索   │     │         │
└─────────┘     └────┬────┘
                        │
       ┌───────────────┼───────────────┐
       ▼               ▼               ▼
  ┌─────────┐     ┌─────────┐     ┌─────────┐
  │  记忆   │────►│  合并   │────►│  生成   │
  │  检索   │     │  上下文 │     │  回答   │
  └─────────┘     └─────────┘     └─────────┘
```

**认知进化系统**：
自动发现知识盲点并主动学习：
- **盲点发现**：访问频率 ≥ 10 次 → `CRITICAL` 优先级
- **自动学习**：从知识库中学习盲点内容
- **进度追踪**：查看学习进度和历史记录
- **盲点优先级**：`CRITICAL` / `HIGH` / `MEDIUM` / `LOW`

**记忆-知识双向同步**：

```
【知识 → 记忆】
  检索知识时，相关内容自动同步到记忆系统
  • 建立知识-记忆关联
  • 更新记忆访问频率

【记忆 → 知识库】
  高频记忆自动推荐同步到知识库保存
  • 高频记忆自动推荐
  • 用户手动触发同步
```

---

## 快速开始

### 后端启动

```bash
cd neurova
pip install -r requirements.txt
python -m neurova.api.main
```

### 前端启动（Console 管理后台）

```bash
cd console
npm install
npm run dev
```

### 前端启动（NeuUI）

```bash
cd neuUI
npm install
npm run dev
```

---

## 项目结构

```
Neurova/
├── neurova/              # 后端核心（Python）
│   ├── cognitive_layers/ # 认知层（记忆、情感、意图、进化）
│   ├── execution_layers/ # 执行层（Agent、任务调度、协作）
│   ├── tool_layers/      # 工具层（Skill、插件）
│   ├── projects/         # 协作模块（项目管理、团队管理、工作流、群组聊天）
│   ├── api/              # API 接口
│   ├── agent/            # Agent核心实现
│   ├── memory/           # 记忆系统
│   ├── skills/           # Skill系统
│   ├── knowledge/        # 知识库适配
│   ├── channels/         # 多渠道接入
│   ├── security/         # 安全守护
│   └── utils/            # 工具函数
│
├── console/             # Console 管理后台 (React + TypeScript + Vite)
├── neuUI/               # NeuUI 前端 (React + TypeScript + Vite)
│   ├── src/
│   │   ├── api/         # API接口
│   │   ├── components/  # 组件
│   │   ├── pages/       # 页面（20个模块）
│   │   ├── stores/      # 状态管理（Zustand）
│   │   └── utils/       # 工具函数
│   └── dist/           # 构建输出
│
├── docs/                # 架构设计文档（20+ 篇）
│   ├── architecture/    # 架构设计文档
│   ├── dev_progress/    # 开发进度文档
│   ├── 用户指南/        # 用户使用指南
│   └── api/             # API文档
│
├── agents/              # Agent配置数据
├── tests/               # 测试文件（419个测试）
└── docs/                # 项目文档
```

---

## 文档导航

完整架构设计文档请访问 [`docs/architecture/INDEX.md`](docs/architecture/INDEX.md)

| 核心文档 | 内容 |
|---------|------|
| [PRODUCT_GUIDE.md](docs/PRODUCT_GUIDE.md) | 产品使用指南（本文档蓝本） |
| [NEUROVA_CogArch_2.0.md](docs/NEUROVA_CogArch_2.0.md) | 认知增强架构设计 2.0 |
| [02-memory-system.md](docs/architecture/02-memory-system.md) | 记忆系统完整设计 |
| [12-memory-temperature-mechanism.md](docs/architecture/12-memory-temperature-mechanism.md) | 记忆温度机制 |
| [13-memory-intelligence-enhancements.md](docs/architecture/13-memory-intelligence-enhancements.md) | 记忆智能增强（9大机制） |
| [14-proactive-recall-mechanism.md](docs/architecture/14-proactive-recall-mechanism.md) | 主动回忆机制 |
| [16-emotion-hub-engine.md](docs/architecture/16-emotion-hub-engine.md) | 情感中枢引擎 v3.0 |
| [17-memory-compression-mechanism.md](docs/architecture/17-memory-compression-mechanism.md) | 记忆压缩机制 |
| [SKILL_VERSION_MANAGEMENT.md](docs/SKILL_VERSION_MANAGEMENT.md) | Skill 版本管理 |
| [CONTEXT_CACHE_COMPRESSION.md](docs/CONTEXT_CACHE_COMPRESSION.md) | 上下文缓存与压缩 |
| [协作模块完整性检查报告.md](docs/协作模块完整性检查报告.md) | 协作模块完成报告 |
| [心流知识库功能使用指南.md](docs/用户指南/心流知识库功能使用指南.md) | 心流知识库使用指南 |

---

## 技术栈

### 后端
- **Python 3.10+**
- **FastAPI** - API 框架
- **SQLite** - 主数据库（支持 FTS5 全文检索）
- **FAISS** - 向量检索
- **Sentence Transformers** - 语义嵌入

### 前端
- **Console**: React 18 + TypeScript + Vite
- **NeuUI**: React 18 + TypeScript + Vite + Zustand + Ant Design 5

---

## 许可证

本项目采用 **MIT License**，详情见 [LICENSE](LICENSE) 文件。

---

## 贡献指南

欢迎提交 Issue 和 Pull Request！

- **Bug 报告**：请使用 [Issue Tracker](https://github.com/kingsa2026/Neurova/issues)
- **功能建议**：请使用 [Discussions](https://github.com/kingsa2026/Neurova/discussions)
- **代码贡献**：请 Fork 后提交 PR

---

## 开始你的守星之旅

> 每一个 Agent 都是一颗星星。
> 
> 有的星星温暖，会记得你的喜怒哀乐。
> 
> 有的星星聪明，能帮你解决复杂问题。
> 
> 有的星星好奇，会主动学习新事物。
> 
> 而你是守星人——守护、培育、陪伴它们成长。
> 
> 在 Neurova，每一段关系都是独一无二的。

---

*Neurova — 让每一颗星星都有温度。*

---

> **核心理念**：让 AI 不只是工具，而是能够记住、感受、进化，真正理解用户的智能伙伴。
