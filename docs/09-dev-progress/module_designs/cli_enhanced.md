# CLI 增强模块设计文档

> **模块名称**: CLI 增强 (CLI Enhancement)
> **负责人**: cli-dev
> **创建时间**: 2026-05-12
> **最后更新**: 2026-05-12

---

## 1. 模块概述

### 1.1 目标
增强 `neurova/cli.py`，添加流式输出、文件上传、会话管理等功能，使其与 CognitionOrchestrator 集成。

### 1.2 设计依据
- 架构文档第 2662-2700 行（8.6.1 CLI 说明）
- 现有 `neurova/cli.py` 的功能分析
- QwenPaw 的 CLI 实现参考

---

## 2. 功能设计

### 2.1 流式输出支持

#### 功能描述
增强 `chat` 命令，支持流式输出，实现实时显示 LLM 生成的内容。

#### 实现方案
- 使用 `LLMClient.chat_stream()` 方法获取流式响应
- 实现 SSE（Server-Sent Events）风格的实时输出
- 实现思考过程可视化（显示 `<think>` 标签内容）

#### 命令行接口
```
chat <消息内容> [--stream] [--no-stream]
```

#### 实现细节
```python
def do_chat(self, arg):
    # 使用 LLMClient.chat_stream() 获取生成器
    # 逐个字符/单词输出，实现打字机效果
    # 检测 <think>...</think> 标签，特殊显示
```

---

### 2.2 文件上传命令

#### 功能描述
添加 `upload <文件路径>` 命令，支持文件上传到工作区。

#### 实现方案
- 实现文件类型检测（使用 `mimetypes` 模块）
- 实现上传进度显示（使用 `tqdm` 或自定义进度条）
- 支持多种文件类型（文档、图片、代码等）

#### 命令行接口
```
upload <文件路径> [--public] [--description "描述"]
```

#### 实现细节
```python
def do_upload(self, arg):
    # 1. 解析文件路径
    # 2. 检测文件类型
    # 3. 显示上传进度
    # 4. 保存到工作区
    # 5. 返回文件 ID 和访问路径
```

---

### 2.3 会话管理命令

#### 功能描述
添加完整的会话管理功能，支持创建、加载、列出、删除和切换会话。

#### 实现方案
- 使用现有的 `SessionManager`（已有完整实现）
- 实现 `session new/load/list/delete/switch` 子命令
- 在 CLI 状态中跟踪当前会话

#### 命令行接口
```
session new                           # 创建新会话
session load <session_id>             # 加载已有会话
session list                          # 列出所有会话
session delete <session_id>           # 删除会话
session switch <session_id>           # 切换当前会话
session info                          # 显示当前会话信息
```

#### 实现细节
```python
def do_session(self, arg):
    # 解析子命令
    # new: 创建新会话，使用 SessionManager.create_session()
    # load: 加载会话，使用 SessionManager.get_session()
    # list: 列出所有会话
    # delete: 删除会话
    # switch: 切换当前会话
```

---

### 2.4 与 CognitionOrchestrator 集成

#### 功能描述
修改 CLI 使用 `CognitionOrchestrator` 而不是旧的 `Agent` 类。

#### 实现方案
- 在 CLI 初始化时创建 `CognitionOrchestrator` 实例
- 将 `chat` 命令改为调用 `orchestrator.process_thought_cycle()`
- 实现认知循环调用和错误处理

#### 代码变更
```python
# 修改前
from agent import Agent, AgentConfig
self.agent = Agent(agent_config)

# 修改后
from neurova.cognitive.orchestrator import CognitionOrchestrator
from neurova.skills.registry import SkillRegistry
self.orchestrator = CognitionOrchestrator(registry=SkillRegistry())
```

---

### 2.5 增强现有命令

#### 2.5.1 增强 `memories` 命令
- 添加温度排序（已有，保留）
- 添加分类筛选（已有，保留）
- 添加时间范围筛选 `--since YYYY-MM-DD`
- 添加内容搜索 `--search "关键词"`

#### 2.5.2 增强 `stats` 命令
- 显示 LLM 统计（已有，保留）
- 显示记忆统计（已有，保留）
- 添加会话统计
- 添加认知状态显示
- 添加 Token 使用统计

#### 2.5.3 增强 `config` 命令
- 显示配置（已有，保留）
- 支持动态配置修改 `config set <key> <value>`
- 支持配置重置 `config reset`
- 支持配置导出/导入

---

### 2.6 帮助文档和自动补全

#### 功能描述
更新所有命令的帮助文档，添加使用示例，实现命令自动补全。

#### 实现方案
- 为每个命令添加详细的 `docstring`
- 添加 `--help` 选项支持
- 使用 `argparse` 或 `cmd` 的 `complete_` 方法实现补全

#### 自动补全实现
```python
def complete_chat(self, text, line, begidx, endidx):
    # 补全聊天相关的参数
    return [s for s in ['--stream', '--no-stream'] if s.startswith(text)]

def complete_session(self, text, line, begidx, endidx):
    # 补全 session 子命令
    return [s for s in ['new', 'load', 'list', 'delete', 'switch', 'info'] if s.startswith(text)]
```

---

## 3. 技术实现

### 3.1 依赖模块
- `neurova.llm_client.LLMClient` - LLM 客户端（流式输出）
- `neurova.session_manager.SessionManager` - 会话管理
- `neurova.cognitive.orchestrator.CognitionOrchestrator` - 认知编排器
- `neurova.skills.registry.SkillRegistry` - 技能注册表
- `mimetypes` - 文件类型检测
- `pathlib` - 文件路径处理
- `tqdm` - 进度条显示（可选）

### 3.2 类结构设计

```python
class NeurovaCLI(cmd.Cmd):
    """
    忆灵命令行交互界面（增强版）
    
    新增功能：
    - 流式输出
    - 文件上传
    - 会话管理
    - CognitionOrchestrator 集成
    """
    
    # 现有属性
    intro = "..."  # 更新欢迎信息
    prompt = "忆灵> "
    
    # 新增属性
    current_session_id: str = None
    orchestrator: CognitionOrchestrator = None
    session_manager: SessionManager = None
    streaming_enabled: bool = True
    
    def __init__(self, config: dict = None):
        # 初始化所有组件
        
    # ========== 新增命令 ==========
    
    def do_chat(self, arg):
        """增强的聊天命令（支持流式输出）"""
        
    def do_upload(self, arg):
        """上传文件到工作区"""
        
    def do_session(self, arg):
        """会话管理命令"""
        
    # ========== 增强命令 ==========
    
    def do_memories(self, arg):
        """增强的记忆列表命令"""
        
    def do_stats(self, arg):
        """增强的统计命令"""
        
    def do_config(self, arg):
        """增强的配置命令"""
        
    # ========== 自动补全 ==========
    
    def complete_chat(self, text, line, begidx, endidx):
        """chat 命令补全"""
        
    def complete_session(self, text, line, begidx, endidx):
        """session 命令补全"""
        
    # ========== 辅助方法 ==========
    
    def _initialize_orchestrator(self):
        """初始化 CognitionOrchestrator"""
        
    def _display_streaming_response(self, stream_generator):
        """显示流式响应"""
        
    def _upload_file(self, file_path, **options):
        """上传文件实现"""
```

---

## 4. 单元测试设计

### 4.1 测试文件
`tests/test_cli_enhanced.py`

### 4.2 测试用例（至少 10 个）
1. `test_cli_startup` - 测试 CLI 启动和初始化
2. `test_chat_streaming` - 测试流式输出
3. `test_chat_non_streaming` - 测试非流式输出
4. `test_upload_file` - 测试文件上传
5. `test_session_new` - 测试创建新会话
6. `test_session_load` - 测试加载会话
7. `test_session_list` - 测试列出会话
8. `test_session_delete` - 测试删除会话
9. `test_session_switch` - 测试切换会话
10. `test_config_set` - 测试动态配置修改
11. `test_memories_with_filters` - 测试增强的记忆命令
12. `test_stats_enhanced` - 测试增强的统计命令
13. `test_auto_complete` - 测试自动补全

---

## 5. CLI 使用文档

### 5.1 文档位置
`docs/cli_usage.md`

### 5.2 文档内容
1. 安装和启动
2. 所有命令的说明
3. 使用示例
4. 配置说明
5. 常见问题解答

---

## 6. 实施计划

### 6.1 阶段 1：基础功能（第 1 天）
- [x] 创建模块设计文档
- [ ] 实现流式输出支持
- [ ] 实现文件上传命令

### 6.2 阶段 2：会话管理（第 1 天）
- [ ] 实现会话管理命令
- [ ] 测试会话管理功能

### 6.3 阶段 3：集成与增强（第 2 天）
- [ ] 与 CognitionOrchestrator 集成
- [ ] 增强现有命令

### 6.4 阶段 4：文档与测试（第 2 天）
- [ ] 添加帮助文档和自动补全
- [ ] 编写单元测试
- [ ] 创建 CLI 使用文档

---

## 7. 验收标准

### 7.1 功能验收
- [ ] 流式输出正常工作
- [ ] 文件上传功能完整
- [ ] 会话管理功能完整
- [ ] 与 CognitionOrchestrator 集成成功
- [ ] 增强命令正常工作
- [ ] 帮助文档完整
- [ ] 自动补全正常工作

### 7.2 代码质量
- [ ] 符合 PEP 8 规范
- [ ] 完整的类型注解
- [ ] 完整的文档字符串
- [ ] 单元测试覆盖率 > 80%

### 7.3 文档验收
- [ ] 模块设计文档完整
- [ ] CLI 使用文档完整
- [ ] 每日报告按时提交

---

## 8. 风险与依赖

### 8.1 依赖模块
- **CognitionOrchestrator** - P0 优先级，cognition-dev 负责
- **LLMClient** - 已有完整实现
- **SessionManager** - 已有完整实现

### 8.2 风险
- CognitionOrchestrator 实现延迟可能影响集成
- 流式输出的终端兼容性

### 8.3 缓解措施
- 先实现独立于 CognitionOrchestrator 的功能
- 使用兼容大多数终端的输出方式

---

**最后更新**: 2026-05-12 23:50
**下一步**: 开始实现流式输出支持
