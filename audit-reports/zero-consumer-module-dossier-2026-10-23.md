# 三个零生产消费者符号的五字段档案（2026-10-23，§6-404 批 M）

> 只读档案，本批**未动这三处一行生产代码**。判定三态：**删 / 接线 / 需人裁**。
> 铁律（教义第 5 条与 §6-163 系列同一口径）：无现役替代不判删；全仓唯一实装且无替代 ⇒ **需人裁**，
> 并写明"删即永久失去什么"。
> 置信度：**✅＝主会话独立复算**（本文里每条 file:line 与每条 git 实证都是本会话现跑的命令输出）；
> 子代理的同名结论只作线索，凡未复算的一律不写进判定。

## 0. 这批为什么会撞到它们

预存红分组里那族「构造签名漂移 15 格」被点名为下一批第一格。逐格读实装后的实况是：**签名没漂移，
被测形状从未存在过**——三档测试都是按想象写的（想象面逐条见 `tests/unit/ci/test_imaginedApiSuitesRetired.py`
的档头）。而"想象"之所以能活这么久，是因为这三个符号**在生产侧一个消费者都没有**：没有任何一条
真实调用链会去纠正它们，测试于是成了它们唯一的"用户"，而那个用户是虚构的。

本批的处置边界：退役**测试**（假读数必须清）＋把唯一真缺口补进真实档；**模块本身的存废不在本批裁**。

## 1. 复算口径（负面证据怎么取的）

对三个符号各自做了五类取数，全部为空或仅命中定义文件：

1. 类名 grep（`neurova/` ＋ `scripts/`）：
   `BrowserSupervisor` 仅 `browser_manager.py:128`；`CognitiveSecuritySystem` 仅
   `cognitive_security.py:563`；`StateManager` 仅 `state_manager.py:57`（文件内工厂 `:387/:392`）。
2. 内层符号逐个 grep（防"整文件有人 import、符号没人读"的假阳性）：
   `PromptInjectionDetector:109`/`SensitiveInfoDetector:202`/`OutputFilter:289`/
   `CognitiveSafetyChecker:352`/`MemorySecurityGuard:492`/`ThreatFinding:48`/`SafetyCheckResult:72`/
   `SafetyLevel:26` 在 `cognitive_security.py` 之外**零命中**；
   `get_state_manager:387`/`reset_state_manager:392`/`StateStatus:28`/`StateChange:38`/`StateSnapshot:48`
   在 `state_manager.py` 之外**零命中**。
3. 动态装载：`importlib.import_module` / `__import__` / `pkgutil` / `walk_packages` 的注册表式装载
   只有 `neurova/api/endpoints/__init__.py` 那份 `ENDPOINT_MODULES` 硬清单（项项都是
   `neurova.api.endpoints.*`）；插件管理器按 `iterdir()` 只扫外部插件目录，**不走**
   `neurova/security` 或 `neurova/core`。字符串形态 `'neurova.security.cognitive_security'`／
   `'neurova.core.state_manager'` 零命中。
4. 包再导出：`security/__init__.py` 只导 `AuditLog/Permission/Role`；`core/__init__.py` 两行；
   `computer_use/__init__.py` 的 `__all__` 不含 `BrowserSupervisor`。无 `import *`。
5. 历史口径（"从未被生产 import"还是"被摘链"）：
   `git log -S "from neurova.security.cognitive_security import" --all -- neurova` **空**；
   `git log -S "from neurova.core.state_manager import" --all -- neurova` **空**；
   `git grep -n "BrowserSupervisor(" 806c7047 -- neurova` 命中三处
   （`browser_manager.py:186/:198/:210`，形如 `BrowserSupervisor(f"ws://localhost:{self._port}")`），
   而 `git grep -n "BrowserSupervisor(" HEAD -- neurova` **空** ⇒ 只有它是"曾被接线、后被摘除"。

反向守卫核对（防止"删掉一个被判据护着的东西"）：`grep -rnE '不得删|禁止删除|不是死代码' tests` 与
三个符号的交集为空；但 `tests/integration/test_computer_use_browser_integration.py:124` 有一条
**方向相反**的常驻守卫——它钉的是「`BrowserManager` 上不得出现 `_supervisor`」，原文理由：
"`BrowserSupervisor` 是需要 CDP ws_url 的零实例化死类；挂到 manager 上等于接通一条没人走过的通道"。
⇒ 本批退役想象测试时它一格没红，且它已经是"这个类不许被悄悄接上"的在册裁决，接线方案要动它。

## 2. 档案

### M1 `computer_use/browser_manager.py::BrowserSupervisor`（`:128-211`，约 84 行）

- **原功能**：CDP WebSocket 直连的会话壳——`connect()` 起 `websockets.connect` ＋后台
  `_event_loop`（`:171`）收帧；`send(method, params)`（`:153`）用自增 id 配 `asyncio.Future`
  做请求／响应关联，30s 超时后从 `_pending_responses` 摘除；`_compress_snapshot(snapshot: str,
  max_length=10000)`（`:193`）对快照**字符串**做头截断；`disconnect()`（`:198`）。
  同一文件里的 `DialogHandler:99` 是 JS 对话框处理器：`async handle_dialog(dialog)` 读
  `dialog.type/message`，按 `_auto_accept` 调 `dialog.accept()` 或 `dismiss()`，并把
  `{type,message,accepted,timestamp}` 追加进 `_dialogs` 留档；`get_dialogs()/clear_dialogs()`。
- **关键入口**：`BrowserSupervisor:128`、`DialogHandler:99`（无工厂函数、无单例口）。
- **来历**：✅ `806c7047`(2026-06-06) 由 `CamofoxAdapter` 三处实例化；`b1dfb744`(2026-08-31)
  随 `CamofoxAdapter` 整块删除（该 commit 后文件内只剩类定义一行命中）。
  ⇒ **形态是"曾被消费后被摘"**，与 M2/M3 的"引入即孤岛"不同，判删时要按这条历史区别对待。
- **现役替代（逐项验证实质，不看存在）**：
  ① CDP 面：现役走 camofox-browser 的 **REST**（`camofox_server_backend.py:38`
  `DEFAULT_CAMOFOX_URL = "http://localhost:9377"`，请求单点 `:167 self._client.request`），覆盖 REST 已提供的动作；
  **不提供任意 CDP JSON-RPC 方法调用**——`send()` 的 id/future 关联与 `_event_loop` 的事件回推
  在全仓仅此一处。② 对话框面：`DialogHandler` 在 `:1596` 被实例化成 `self._dialog_handler`，
  而 `_dialog_handler` 这个名字全仓**仅此一处出现** ⇒ 只写不读断点（§2 协作红线的"写出无人读的字段"）；
  `camofox_server_backend.py`／`remote_backend.py` 里 `dialog` 零命中，`PlaywrightBackend:565`
  未注册对话框监听 ⇒ **对话框应答与留档零现役覆盖**。③ 快照裁剪：`applySnapshotBudget`（`:1220`，
  配套 `SnapshotBudget:1206`/`SnapshotFold:1285`）按 `max_nodes/max_depth` 结构化裁剪并如实算出
  隐藏数——是 `_compress_snapshot` 头截断的**超集**，旧截断可弃、不构成保留理由。
- **判定**：**需人裁**。删＝永久失去「CDP 直连任意方法」与「JS 对话框自动应答＋留档」两项唯一实装
  （后者今天连读的人都没有）；接线＝要么把 `DialogHandler` 挂进真后端的事件流并让留档可读，
  要么按 `806c7047` 的旧通道重建 ws_url 来源——**且必须先撤掉 `test_computer_use_browser_integration.py:124`
  那条反挂接守卫**，否则接线即红。两条路都不是改测试。

#### M1 已裁记录（2026-10-24，§6-410 批 O-4）

用户裁：**接线对话框应答**。走的是上面第一条路（挂进真后端的事件流＋留档可读），落地见 §6-410。

- 已接：`PlaywrightBackend` 在 `initialize()` 建 context 处注册 `dialog` 监听（context 级，覆盖全部 tab），
  `BrowserManager` 把自己那份 handler 交下去（`be._dialog_handler is mgr._dialog_handler` 有判据钉），
  并新增具名读口 `BrowserManager.dialogLog()` ⇒ 写→读成环。
- **本档案当时那句"必须先撤掉反挂接守卫"是不准确的，在此更正**：`test_computer_use_browser_integration.py:124`
  钉的是 `not hasattr(BrowserManager, "_supervisor")`——对象是 `BrowserSupervisor`（需要 CDP ws_url 的那个死类），
  与 `DialogHandler`／`_dialog_handler` 不是同一个东西。按"挂进真后端事件流"这条路接线**碰不到那条裁决**，
  复跑该档 579 passed 仍绿即为证。⇒ 反挂接守卫原样保留。
- **仍未接的是另一半**：`BrowserSupervisor` 握着的「任意 CDP JSON-RPC 方法调用」本批没动也不该顺手动——
  那要先重建 `ws_url` 来源（`806c7047` 的旧通道已被 `b1dfb744` 随 `CamofoxAdapter` 摘除）。
  所以 M1 从"两项唯一实装都悬空"变成"**对话框应答已落地；CDP 直连这一项仍无人裁**"。
- 另记一条本批核实到的事实，供日后判 CDP 那半时用：仓内第二处用 playwright 的是
  `web_reach/browser_read.py:120`，它自己 `browser.new_page()`、**不经过** `BrowserManager`，
  靠 Playwright 无监听时的默认行为（`alert` dismiss／`confirm`·`prompt` 取消）读完不挂住。

### M2 `security/cognitive_security.py`（整文件 663 行）

- **原功能**：一套输入／输出／记忆三面的分级安全判定——`PromptInjectionDetector:109`（英文／中文
  注入模式、角色切换、自定义模式）；`SensitiveInfoDetector:202`（手机／邮箱／身份证／api_key 等
  按**内容**正则识别，配 `sanitize():265` 脱敏）；`OutputFilter:289`（`filter()` 返回
  `(text, findings)` 2 元组）；`CognitiveSafetyChecker:352`（意图安全＋执行监控）；
  `MemorySecurityGuard:492`（`sanitize_memory:509`/`should_remember:517`/`check_memory_safety:535`）；
  门面 `CognitiveSecuritySystem:563`（`check_input_safety:578`/`check_output_safety:613`/
  `sanitize_memory:645`/`check_memory_safety:649`/`monitor_execution:653`/两个 detect 转发）。
  枚举与数据类：`SafetyLevel:26`＝LOW/MEDIUM/HIGH/CRITICAL，`ThreatType:35`，`ThreatFinding:48`，
  `SafetyCheckResult:72`。
- **关键入口**：`CognitiveSecuritySystem:563`（无 `get_*` 单例口，全靠手工构造）。
- **来历**：✅ `git log -S "from neurova.security.cognitive_security import" --all -- neurova` 为空
  ⇒ **生产从未 import 过这个模块**；它随 `7835c367`(2026-06-04「pyc 骨架恢复」，703 文件) 一次性入库，
  测试是它唯一的调用者。
- **现役替代（这里必须逐项，不能一句"有安全模块"了事）**：
  ① 提示注入——**有活的替代**：`security/skill_scanner.py:286 PromptInjectionAnalyzer` 被
  `tool_executor.py:2303` 在 `create_skill` 路径上 fail-closed 调用；同一分析器还被
  `skills/skill_install_gate.py:232-237`（`scan_text_for_injection:224`）用在 NL 合成注册闸上，
  调用点 `agent/chat_pipeline.py:1299-1301` ⇒ 这一项删了不丢能力，但两处替身只覆盖**技能创建/安装**这条面，
  不覆盖"每轮用户输入"。② 敏感信息（PII／密钥按内容识别＋脱敏）——**无现役替代**：
  `security/privacy_gate.py:18 _SENSITIVE_KEY` 只按**键名**脱敏 tool messages
  （判定在 `:40`；消费点 `chat_pipeline.py:2518` 与 `:2708` 的
  `redact_tool_messages_for_channel`），不看内容里的手机／身份证／银行卡／IP；
  `core/firewall.py:408 sanitize_output` 虽按 `_sensitive_patterns`（`:147`）逐条 `[REDACTED]`，
  但它在生产侧**零调用方**（✅ 复核：grep `sanitize_output` 排除自身后无命中）。
  ③ 记忆侧——`cognitive_layers/memory_layer/security.py MemorySecurity` 经
  `memory/__init__.py:54` 再导出（`__all__` 条目在 `:117`），除这层再导出外零消费者。⇒ "按内容分级识别 PII 并产出 sanitized_text"是**全仓唯一实装**，
  而唯一的另一份（`firewall.sanitize_output`）同样没接线。
- **判定**：**需人裁**，不得进可删清单。三态各自的影响面：
  删＝永久失去内容级 PII/密钥识别与分级结果（回合链上任何位置要用时都得重写）；
  接线＝要定"输入面每轮都过一遍检测"的性能与误杀预算（`check_input_safety` 是纯正则遍历，
  但输出面 `check_output_safety` 会扫全文），并需指明接在 `chat_pipeline` 的哪一拍；
  收口单源＝与 `firewall.sanitize_output`/`memory_layer/security.py`/`privacy_gate` 四份规则
  比对后合并（教义第 6/7 条），那是**一批**的工作，不是本批的顺手事。
- **待补口径**（不写成结论）：`SensitiveInfoDetector:207-214` 的正则清单与
  `memory_layer/security.py`、`core/firewall.py:147` 的 `_sensitive_patterns` 三份**未逐项比对过**，
  谁覆盖谁、有无互相冲突的脱敏格式，须由裁定者拍板后再动。

#### M2 已裁记录（2026-10-24，§6-411 批 O-5）

用户裁：**先收口单源，暂不进回合链**。落地＝§6-411（`1e3eedf3`），本档案据此更正两处读数：

- **"内容级 PII 识别＋脱敏无现役替代"这句仍然成立，但形状变了**：本档案当时数到 4 份表；
  第 5 条扫荡复算实为 **7 份**——除本档案列的三份外，还有三处**在役**的自有小抄
  （`context/summarizing_compressor.py:31`、`llm/providers/error_mapping.py:173`、
  `skills/evolution_inputs_guard.py:22-27`），以及唯一在役且功能不同的 `security/privacy_gate.py:18`
  （按**键名**递归脱敏，不并）。⇒ 单源表已把七份里的**全部形状**收进去（`ghp_`／`nvk_` 由此进来），
  接线进度是"4 份已改接、3 处在役的未改接"（后者另立批 P-5：要先裁出口 token 是否统一）。
- **本模块的接缝错位已消失**：`SensitiveInfoDetector` 不再自带 `SENSITIVE_PATTERNS`，
  也不再自写 sanitize（那条 `split("=")[0]+"=***"` 会让冒号形 `password: abc` 输出
  `password: abc=***`——值一个没少还缀垃圾，本档案的"验证实质"栏当时没验到这一层）。
  `custom_patterns=` 这个从无人传过的构造形参随批撤广告。
- **仍未裁的部分**：`PromptInjectionDetector`（提示注入）与 `OutputFilter`（不当内容/危险命令）
  两张表不属本票、留在原文件；`CognitiveSecuritySystem:563` 依旧零生产引用。
  所以 M2 的"整文件删不删"仍是开着的票，只是它现在**不再握着敏感信息识别这项唯一实装**——
  那项能力已经搬到 `security/sensitive_info.py` 并被三处消费者共用。


### M3 `core/state_manager.py`（整文件 395 行）

- **原功能**：点号分隔嵌套键的状态容器（`get:74`/`set:88`/`delete:106`）＋键监听器
  `on_change`（`:179`）与全局监听器 `on_any_change`（`:192`）＋快照
  `create_snapshot`（`:228`）＋变更日志 `StateChange:38`＋落盘 `save:294`/`load:310`；
  状态机标签 `StateStatus:28`；单例工厂 `get_state_manager:387`/`reset_state_manager:392`。
- **关键入口**：`StateManager:57`、`get_state_manager():387`。
- **来历**：✅ `git log -S "from neurova.core.state_manager import" --all -- neurova` 为空，
  命中文件只有 `docs/plans/2026-05-08-phase5-awakening-foundation.md`、
  `docs/plugin-architecture-design.md` 与四个测试文件 ⇒ **引入即孤岛，不是被摘链**。
- **接缝是"存在但恒不赋值"，且契约错位**：`core/base_module.py:53` 与
  `plugins/base_plugin.py:109` 都只把 `_state_manager` 初始化成 `None`；
  `base_plugin.py:164` 有 setter，**全仓无调用方**；`idle_tracker.py:90` 的构造形参
  `state_manager=None`，而唯一的构造点 `agent_core.py:679` 是 `IdleTimeTracker()`——不传参 ⇒
  永远为 `None`。更硬的一条：`base_plugin.py:300/:311` 真去调
  `self._state_manager.get_state(plugin_id, key, default)` / `set_state(plugin_id, key, value)`，
  而本类的方法名是 `get`/`set` 且**没有 `plugin_id` 这一位**——就算有人把它接上，第一次调用就是
  AttributeError。⇒ 这三处"预期消费方"的契约与本类不同源，接线不是低成本选项。
- **名实不符一处**（本批立案、未改）：`set()` 走的第二个通知是 `_emit_state_event:220`，
  名字承诺"发事件"，函数体只是遍历 `_any_listeners` 调本地回调，**不碰 EventBus**。
  退役掉的想象档正是被这个名字骗去断言"总线上会出现 `state.changed`"。
  本批新增的 `tests/integration/test_event_workflow.py::TestStateManagementSeam::test_setDoesNotPublishOnEventBus`
  把"当前不发"钉成哨兵：若裁定接线（发到 `get_event_bus()` 单例），该格当场变红，提醒同步改判据与档案。
- **现役替代**：语义不等价。`api/app.py:41 AppState` ＋ `endpoints/__init__.py:55-92` 是扁平 dict
  装配面（无点号嵌套／监听／快照／变更日志）；`core/event_bus.py` 只 pub-sub 不持有状态；
  `core/settings_manager.py` 只落盘配置（无监听与回滚）；`checkpoints/` 是文件级 git 快照。
  ⇒ `on_change` ＋ `create_snapshot` ＋ `save` 三项组合在仓内**无第二份**。
- **判定**：**需人裁**（三态里我倾向删除，但删除即失去上述组合，须由拍板者承担）。
  若裁定保留，正确动作是：先给"预期消费方"定契约（`base_plugin` 那两个不存在的方法要么改名要么删接缝），
  再决定事件语义（改名 `_emit_state_event` 还是真发事件），最后才谈接线——顺序反了就是拿测试补想象。

#### M3 已裁记录（2026-10-24，§6-409 批 O-3）

用户裁：**先修错位接缝，再定去留**。接缝那一半已落地，**模块去留仍待裁**，本档案继续留着：

- 已修（`da32c4d7`）：按上面那句"要么改名要么删接缝"选了**删接缝**——`BasePlugin.get_state/set_state`、
  `state_manager` 属性对、`_state_manager` 字段整体退役，插件族改挂仓内既有的那份键值状态袋实装
  （新建 `core/base_module.StateValuesStore`，把原来散在三处的同功能实装收成一处；
  现查这一对方法全仓零调用方、`tests/unit/test_base_plugin.py` 也从未测过它们 ⇒ 删它不带走任何覆盖）。
  同根一起清的还有 `base_module.py:53-55` 那三个**全仓零读者**的字段
  （`_state_manager`/`_log_manager`/`_error_handler`）与 `idle_tracker` 构造函数上三个收下即丢的注入位。
  **没有**给 `StateManager` 补出那两个方法——那正是"拿测试补想象"的反面教材。
- 裁后读数（这是留给"定去留"那一拍的关键变化）：`StateManager` 的生产消费者**仍是 0**
  （`get_state_manager()` 只在 `state_manager.py:387` 自己出现、`StateManager(` 只被自己的工厂调用），
  原先那三处"看起来要用它"的接缝（`base_module.py:53`／`base_plugin.py:109/164`／`idle_tracker` 形参）
  本批全部消失 ⇒ **删它不再有任何名义上的消费方需要一并处置**，"接线不是低成本选项"这句
  在接缝退役后已无对象可接。名实不符那条（`_emit_state_event:220` 不发事件）原样留着，
  哨兵格 `test_setDoesNotPublishOnEventBus` 仍在。
- 档案内的行号已随批次漂移（`idle_tracker.py:90`→`:116`、`agent_core.py:679`→`:663`、
  `base_plugin.py:109/164/300/311` 随本批消失）；复核请按**符号**定位，勿按本档案的行号。

## 3. 附带两件（都不是票，是记录）

1. **幻影模块 `ProjectManager`**：`neurova.projects` 包不存在、`class ProjectManager` 全仓零命中，
   而两档测试（12 格）用 `try/except ImportError → 整档 skipIf` 把它变成永久 skip。生产侧口径早已裁定：
   `neurova/api/endpoints/projects_api.py:19-21` 明写"历史上曾用内存 dict / **不存在的 ProjectManager**
   做兜底……该路径已删除"。⇒ 两档测试本批直接退役，无需人裁（被试对象不存在，谈不上失去能力）。
2. **一条新暴露的告警**：`neurova/core/event_bus.py:91` 在 `EventBus()` 构造路径上调
   `asyncio.get_event_loop()`，py3.12 下打 `DeprecationWarning: There is no current event loop`。
   本批重写 `test_event_workflow.py` 后这条第一次被稳定看到（旧档在 setUp 就 TypeError，跑不到）。
   未修——它是总线自己的生命周期写法问题，与本批的测试退役不同根，留待单独一拍处理。

## 4. 本批据此已做与未做的界线

已做（全部只动测试面）：退役 4 档想象／空壳测试；把唯一真缺口补进真实档
（`tests/unit/security/test_cognitive_security.py::test_checkMemorySafetyDelegatesToGuard`，变异探针验过有牙）；
`tests/integration/test_event_workflow.py` 重写为总线契约＋状态监听器真实接缝（6 passed）；
拆掉另外 4 档的"整档静默 skip"形状（57 passed，零 skip）；新增常驻守卫
`tests/unit/ci/test_imaginedApiSuitesRetired.py`（含静默 skip 判据）。
**未做**（写档案那一拍的状态，2026-10-23）：M1/M2/M3 的任何生产改动、任何接线、任何删除——那三张票等人拍。

**三票其后的下落**（2026-10-24 现查，逐票按上面的"已裁记录"同一口径补记）：
用户已对三票都拍了方向，落地进度不同——**M1** 裁"接线对话框应答"，**已落地**（§6-410 批 O-4），
本档案那句"必须先撤反挂接守卫"随批更正；剩下的只有 CDP 直连那半（见上"已裁记录"）；
**M3** 裁"先修错位接缝，再定去留"，接缝已随 §6-409（批 O-3，`da32c4d7`）收口，模块去留仍待裁；
**M2** 裁"先收口单源，暂不进回合链"，**规则面已落地**（§6-411 批 O-5，`1e3eedf3`）——七份表（本档案当时数到四份，扫荡后复算为七份）里的形状全并进 `security/sensitive_info.py`，四份改接、三处在役的待接（批 P-5）；详见上「M2 已裁记录」。三票都**没有**做删除动作。

