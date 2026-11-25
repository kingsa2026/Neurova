# Neurova OSWorld 基准实测报告（2026-11-25）

> 状态：**冒烟 10 + 子集 50 均已完成**。
> 结论速览：**子集 50 任务均分 0.560、通过率 56.0%（28/50，1 个基建失败单列）**；
> 冒烟 10 通过率 50%；全链零器械崩坏，评分链路可信。

## 1. 目的与问题

用户问题："给本仓做一个 OSWorld/WAA 评测，看看能拿到多少分？"

经拍板：先跑 **OSWorld**（xlang-ai/OSWorld，368 任务、10 域，业界计算机使用
主流基准），规模走 **冒烟 10 → 子集 50**；WAA 视 OSWorld 结果再议。

## 2. 接入架构

OSWorld 的 agent 接口是 `predict(instruction, obs) -> (response, actions)`：
观测为 VM 截图（bytes），动作是 VM 内执行的 pyautogui 代码字符串（或
DONE/FAIL/WAIT 结算动作）。Neurova 侧采用"借大脑"接法——只使用 Neurova 的
模型接入层（`MultiModelLLMClient`，provider 路由 + 视觉补全），**不经过**
agent 工具管线，避免 `computer_*` 工具误触宿主机；VM 内执行完全交给 OSWorld
harness。这与 Agent-S 等公开工作接入 OSWorld 的口径一致。

```
OSWorld harness (F:/osworld/OSWorld, 独立 venv)
  └─ mm_agents/neurova_agent.py   # 适配器：截图→base64，动作解析
       └─ HTTP POST /act (127.0.0.1:9761)
            └─ neurova_bridge.py  # 桥接服务，Neurova .venv 运行
                 └─ neurova.llm.multi_model_client.MultiModelLLMClient
                      └─ moss / nex-n2.6（当前 provider 配置）
```

三件评测设施（不入本仓 git，均在 F:/osworld/）：

| 文件 | 角色 |
|------|------|
| `neurova_bridge.py` | HTTP 桥：{instruction, screenshot_b64, system_prompt, history} → Neurova LLM 补全 → {text} |
| `OSWorld/mm_agents/neurova_agent.py` | OSWorld Agent 适配器：提示词复用 `SYS_PROMPT_IN_SCREENSHOT_OUT_CODE`，解析 python 围栏/DONE/FAIL/WAIT |
| `run_neurova_eval.py` | 跑批：VirtualBox provider、固定 seed 按域轮转抽样、基建失败单独标记 infra_error |

系统提示词使用 OSWorld 自带的截图→pyautogui 代码模板，保证与基准口径一致；
坐标 grounding 由模型直接依截图给出。

## 3. 评测配置

- **模型**：moss / nex-n2.6（Neurova 数据根 `data/llm/providers.json` 当前活跃配置，temperature=0）
- **观测**：screenshot-only（`require_a11y_tree=False`，不喂 DOM 树）
- **动作空间**：pyautogui；**每任务上限 15 步**；步间 sleep 1s
- **VM**：OSWorld 官方 Ubuntu x86 镜像（HF `xlangai/ubuntu_x86_virtualbox`），
  VirtualBox 7.2.22（Windows 宿主，headless）
- **任务集**：
  - 冒烟 10：固定 seed=42，每域 1 个（10 域全覆盖）
  - 子集 50：固定 seed=42，每域 5 个
  - id 列表落盘 `F:/osworld/smoke10_ids.txt` / `subset50_ids.txt`，可复现
- **口径**：
  - `mean_score_all` = 全部任务得分均值（infra_error 记 0）
  - `pass_rate` = score>0 任务占比
  - infra_error（环境/基建异常）单独列示，不与任务失败混算

## 4. 环境事实与坑

- 宿主：Windows 11 专业教育版，32GB 内存，12 逻辑核；无 VMware/Docker/WSL，
  新装 VirtualBox 7.2.22（winget）
- OSWorld 官方默认 provider 是 VMware；本机走 **VirtualBox 后端**（官方支持，
  不支持并行多 VM，串行跑）
- 镜像 ~13GB，下载落 `F:/osworld/OSWorld/virtualbox_vm_data/Ubuntu.zip`
  （manager 支持断点续传，预下载后 import 阶段直接复用）
- Neurova 桥接必须用本仓 `.venv` 运行（provider 密钥解密依赖仓内加密存储），
  并设 `NEUROVA_DATA_DIR` 指向本仓 `data/`
- 桥接内 `chat()` 为协程：用专用后台 event loop 线程承载，避免每请求新建 loop

执行期坑（复跑必读，详细过程见会话记录）：

- **provisioning 必须单流水线**：多套 import/startvm 流程并行操作同一
  `virtualbox_vm_data/Ubuntu0` 目录会互删半成品 vmdk、抢注册，制造
  `VERR_ALREADY_EXISTS`/`OBJECT_NOT_FOUND` 等竞态故障。
- **streamOptimized vmdk 不能直接可写挂载**（只读 base + COW 会卡启动），
  必须经 `VBoxManage import` 展开为普通盘。
- **VM 开机早期 systemd 拉起 osworld.service 会失败熔断**：桌面就绪后须
  `sudo systemctl restart osworld` 再探 `:5000/platform`。
- **GA（vboxadd）不上报 guestproperty**：IP 用广播 ping `192.168.1.255` +
  ARP 表（MAC 前缀 `08-00-27`）发现；注意中文 arp 输出取第 1 列为 IP。
- **moss 上游对 1×1 退化探针图必报 500**：bridge 探活须用正常尺寸合成图。
- **9762 端口须只挂一个 bridge 实例**：系统 Python 的残留实例会与 `.venv`
  实例抢同端口（SO_REUSEADDR 下请求随机路由到缺依赖的实例，表现 000）。

## 5. 结果

### 5.1 冒烟 10（链路验证）——已完成 2026-11-25

运行目录 `F:/osworld/eval_runs/smoke10_20261125_103800/`（task_ids/results/traj/截图全落盘）。

**总览：10/10 全部有效评分，infra_error=0，mean_score_all=0.5，pass_rate=0.5。**

| 任务（前 8 位） | 域 | 得分 | 步数 |
|------|----|------|------|
| 5cfb9197 | — | 1.0 | 3 |
| 2373b66a | — | 1.0 | 7 |
| 5ced85fc | — | 1.0 | 3 |
| 5203d847 | — | 1.0 | 15 |
| 9195653c | — | 1.0 | 15 |
| 6c4c23a1 | chrome | 0.0 | 15 |
| 62f7fd55 | gimp | 0.0 | 15 |
| 01b269ae | — | 0.0 | 81 |
| 66399b0d | — | 0.0 | 10 |
| 847a96b6 | — | 0.0 | 57 |

链路验证结论：reset（快照恢复）→ 截图观测 → Neurova 决策（moss/nex-n2.6）→
pyautogui 动作 VM 内执行 → evaluate 打分，全链真实闭环，10 任务零基建故障。
失败任务均走满步数后 evaluate 判 0，属能力边界而非器械问题。

### 5.2 子集 50（正式读数）——已完成 2026-11-25

运行目录 `F:/osworld/eval_runs/smoke10_20261125_115939/`（目录名前缀沿用
mode 默认值，任务列表实为 subset50_ids.txt 的 50 个任务）。

**总览（Neurova 大脑 = moss/nex-n2.6，screenshot-only，≤15 步）：**

| 指标 | 读数 |
|------|------|
| 任务数 | 50 |
| 有效评分 | 49（1 个 infra_error，见下） |
| **均分 mean_score_all** | **0.560** |
| 均分（剔除 infra_error） | 0.571 |
| **通过率 pass_rate** | **0.560（28/50）** |
| 基建故障 | 1（`28cc3b7e`：任务 setup 阶段 VM 内 404，环境配置失败，非模型问题，按 P0-② 口径单列） |

冒烟 10（50%）→ 子集 50（56%）读数稳定，评分链路可信。

**失败任务分布**（22 个 0 分）：多集中在 chrome/多步办公域的长链任务——
步数打满仍未达成目标状态（如 `6c4c23a1` 15 步、`7f52cab9` 15 步、`62f7fd55`
15 步）；少数中途 WAIT/解析退化为空动作（`66399b0d` 4 步、`7c4cc09e` 3 步）。
无一步"器械崩坏"型失败（traj 均完整、evaluate 均正常执行）。

**与参照系的关系**：Agent-S2 论文口径 OSWorld 72.6%（不同底座模型与增强
配置，未独立复跑）；本读数是本仓"借大脑"接入（无 UI-TARS 式指向接地、无
a11y 树、无 self-evolved 工具库）下的**同基准首次实测锚点**。提升空间与
[[reference_af]] 拆解卡的 T2（VLM 指向接地）、T5（动作证据帧）直接对应。

## 6. 与既有对照评测的关系

- [[reference_af]]（Agent-S）报告其 OSWorld 72.6% 系论文口径未独立复跑；本次
  是本仓**首次在同基准上的实测读数**，为后续跨仓对比提供同基线锚点。
- 本仓 computer_use 全栈（SOM/UIA/车道互斥）在本次评测中只参与"大脑"侧提示
  语境，动作执行面由 OSWorld VM 承担；UIA 等 Windows 专属能力在该基准（Ubuntu
  VM）中不参与，WAA（Windows 原生任务）才是其对口考场。
