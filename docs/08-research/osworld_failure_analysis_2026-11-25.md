# OSWorld 子集 50 失败分析（2026-11-25）

> 数据源：`F:/osworld/eval_runs/smoke10_20261125_115939/`（每任务 traj.jsonl
> 逐步动作、initial_state.png、results.json）+ 冒烟轮
> `smoke10_20261125_103800`。配置见
> [neurova_osworld_vm_benchmark_run_2026-11-25.md](neurova_osworld_vm_benchmark_run_2026-11-25.md)。
> 结论速览：**28/50 通过；22 个失败可归为 5 类模式，其中"动作空间误用"
> （输出宏/裸 python/bash 而非 pyautogui）与"无核验假 DONE"合计占失败的
> ~2/3**——两者都可在本仓 computer_use 评测与工具面直接改进。

## 1. 全景

| 域 | 通过 | 域 | 通过 |
|----|------|----|------|
| vlc | 4/5 | chrome | 3/5 |
| gimp | 4/5 | thunderbird | 3/5 |
| libreoffice_calc | 4/5 | libreoffice_writer | 3/5 |
| libreoffice_impress | 2/5 | os | 2/5 |
| vs_code | 2/5 | **multi_apps** | **1/5** |

单应用 GUI 操作类（vlc/gimp/calc）最好；**跨应用协作（multi_apps 1/5）与
终端/IDE 类（os、vs_code 各 2/5）最难**。

## 2. 失败模式（按证据归类）

### M1 动作空间误用：输出宏/裸 python/bash（≥7 个失败任务）

harness 只执行 **pyautogui** 代码；模型却大量输出其他形态：

- `30e3e107`（calc 透视表，109 步）：第 1 步起输出 **LibreOffice Basic 宏**
  （`Sub CreateDemographic...`），pyautogui 执行器无法执行，屏幕无变化，
  挣扎 109 步；末两步才改用 `python subprocess` 写宏文件（方向转对但步数耗尽）。
- `847a96b6`（vs_code，36 步）：前几步输出 **bash**（`code --add ...`），
  同样不可执行；中途转 sqlite3/subprocess 大段 python，最后 DONE 判 0。
- `0b17a146`（writer，24 步）：Basic 宏（H2O 下标）+ 4 次 DONE，判 0。
- `f918266a`（multi_apps，75 步）、`23393935`（os，27 步）、`51f5801c`、
  `68a25bd4`：输出裸 python（zipfile 读 pptx、shutil 拷贝、排序算法），
  意图用"写代码"替代"GUI 操作"。

反例：`01b269ae`（calc，PASS 1.0）也输出过同款 Basic 宏但最终靠后续 GUI
步骤完成；`70bca0cc`（impress，PASS）python 只作辅助验证。说明代码倾向
本身不必然失败，但**在动作空间不受控时是主要陷阱**。

### M2 无核验假 DONE（6 个失败任务）

`5cfb9197`（impress，6 步）、`66399b0d`（writer，4 步）、`7c4cc09e`
（vs_code，3 步）、`08c73485`（thunderbird，11 步）、`0b17a146`、
`847a96b6`——模型声明 DONE 但 checker 判 0。其中 4 个 ≤6 步即宣布完成：
只执行了任务的一部分（如改了 1 个标签、设置了 1 个选项）就结算。
全轮 DONE 声明共 20 次，**假完成率 30%**。

### M3 无反馈卡死循环（dup≥7 的失败任务）

截图观测无法区分"命令没进终端"与"执行了但界面无变化"：

- `9bc3cc16`（thunderbird，28 步，相邻重复 12 次）
- `23393935`（os，27 步，重复 11 次）
- `c288e301`（os，15 步全 type，重复 7 次）：反复向终端 typewrite 同一段
  `ls /usr/bin | grep -i python ...`，终端始终无回显（焦点/终端未开），
  模型无感知直到步数耗尽。
- `3b27600c`（impress，15 步，重复 9 次）

### M4 逐字符打字长任务

`f918266a`（75 步）：向 VSCode/终端 `typewrite(interval=0.03)` 敲入整段
python 代码，步数几乎全部耗在打字上；`68a25bd4`、`c288e301` 同型。
长文本输入应走剪贴板粘贴而非逐字符敲击。

### M5 跨 run 方差

`5cfb9197`（impress 表格标签）：冒烟轮 3 步 PASS 1.0，子集轮 6 步
DONE 判 0——**同任务、同 temperature=0、不同 run 结果翻转**（上游服务端
采样非确定）。单 run 50 任务的读数存在可见方差，结论引用需谨慎。

## 3. 成功侧对照（有效行为）

- 短平快任务 3-5 步 DONE 且先核验（`d16c99dc`/`734d6579` gimp 5 步、
  `2373b66a` multi_apps 7 步）——**先操作后确认再 DONE** 的节奏与 PASS
  高度相关；14 个 PASS 带 DONE 声明，多数在 DONE 前有明确的目标态描述。
- `930fdb3b`（vs_code 53 步 PASS）、`70bca0cc`（impress 49 步 PASS）：
  长任务里模型把 python 只用于**只读验证**（读文件核对状态），GUI 动作
  才做变更——这是 M1 的正确打开方式。
- thunderbird/vlc 的点选-滚动类任务通过率高：单窗口、目标控件视觉显著，
  截图 grounding 足够。

## 4. 经验教训与本仓改进点

| # | 教训 | 本仓落点 |
|---|------|----------|
| 1 | 动作空间必须在提示词里强约束（只许 pyautogui 原子操作，禁宏/裸 python/bash），并在解析层拒绝非白名单代码 | T3 `benchmark/cua_eval.py` 评测器与 computer_use 提示词加"动作空间纪律"段；解析层对非 pyautogui 代码显式记 `invalid_action` 而非静默 no-op |
| 2 | DONE 前必须核验目标状态（截屏对照任务目标），否则假完成率 30% | computer_use 工具链加"DONE 前强制 verify"门：模型声明完成时先回一张核验截图/对照清单再结算（T5 证据帧可复用） |
| 3 | 屏幕连续无变化 ≥N 步应触发"操作可能未生效"提示或强制换策略 | computer_use 会话层加**屏幕指纹差分检测**（evidence_frames 已有前后帧能力，扩展为卡顿熔断信号注入） |
| 4 | 长文本输入走剪贴板粘贴，禁止逐字符 typewrite | computer_use 输入动作面提供"长文本注入"专用动作（写剪贴板+ctrl+v），提示词引导 |
| 5 | 单 run 读数有方差，评测需多 run 聚合 | `benchmark/cua_eval.py` 支持同任务集重复运行聚合（均值±方差、逐任务翻转标记） |
| 6 | 跨应用任务（multi_apps 1/5）是最大短板：需要任务分解与跨应用状态跟踪 | 正是本仓 swarm/规划强项——可实验"规划器拆步 + 执行器单步"两阶段接入 OSWorld，替代单模型直接出动作 |
| 7 | LibreOffice 系任务模型自发改走宏路径（Basic/UNO），说明"让模型用最短路径完成任务"的倾向很强 | 本仓 agent 侧若开放脚本通道（如 T4 结构化直写），应与 GUI 车道做**显式路由约定**，避免动作空间混用 |

## 5. 逐任务一览（50 任务）

| 任务 | 域 | 得分 | 步数 | 失败归因 |
|------|----|------|------|----------|
| 8f080098 | vlc | 0.99 | 15 | — |
| 4bcb1253 | writer | 1.00 | 15 | — |
| 930fdb3b | vs_code | 1.00 | 53 | — |
| 70bca0cc | impress | 1.00 | 49 | — |
| 01b269ae | calc | 1.00 | 25 | — |
| 1334ca3e | calc | 1.00 | 16 | — |
| 35253b65 | chrome | 1.00 | 15 | — |
| 82bc8d6a | chrome | 1.00 | 15 | — |
| 21ab7b40 | calc | 1.00 | 15 | — |
| 6a33f9b9 | writer | 1.00 | 15 | — |
| bedcedc4 | os | 1.00 | 15 | — |
| 5203d847 | thunderbird | 1.00 | 15 | — |
| d38192b0 | thunderbird | 1.00 | 15 | — |
| f201fbc3 | thunderbird | 1.00 | 15 | — |
| 9195653c | vlc | 1.00 | 15 | — |
| 59f21cfb | vlc | 1.00 | 15 | — |
| 982d12a5 | vs_code | 1.00 | 15 | — |
| bb5e4c0d | chrome | 1.00 | 13 | — |
| 554785e9 | gimp | 1.00 | 13 | — |
| e2dd0213 | gimp | 1.00 | 11 | — |
| a5bbbcd5 | vlc | 1.00 | 10 | — |
| 0bf05a7d | calc | 1.00 | 8 | — |
| 2373b66a | multi_apps | 1.00 | 7 | — |
| d16c99dc | gimp | 1.00 | 5 | — |
| 734d6579 | gimp | 1.00 | 5 | — |
| 9ec204e4 | impress | 1.00 | 5 | — |
| 5ced85fc | os | 1.00 | 5 | — |
| 72b810ef | writer | 1.00 | 4 | — |
| 30e3e107 | calc | 0.00 | 109 | M1 Basic 宏 + M3 |
| f918266a | multi_apps | 0.00 | 75 | M1 裸 python + M4 打字 |
| 847a96b6 | vs_code | 0.00 | 36 | M1 bash + M2 假 DONE |
| 9bc3cc16 | thunderbird | 0.00 | 28 | M3 卡死（dup12） |
| 23393935 | os | 0.00 | 27 | M1/M3（dup11） |
| ec71221e | vs_code | 0.00 | 27 | M1 代码块 |
| 0b17a146 | writer | 0.00 | 24 | M1 宏 + M2 假 DONE |
| 51f5801c | multi_apps | 0.00 | 21 | M1 裸 python |
| 6c4c23a1 | chrome | 0.00 | 15 | 步数不足（cookie 弹窗/语言切换链长） |
| 7f52cab9 | chrome | 0.00 | 15 | 步数不足（末步 sleep 空转） |
| 62f7fd55 | gimp | 0.00 | 15 | GUI 操作链偏差（错误对话框打断） |
| 3b27600c | impress | 0.00 | 15 | M3（dup9） |
| 550ce7e7 | impress | 0.00 | 15 | 文本编辑定位偏差 |
| 68a25bd4 | multi_apps | 0.00 | 15 | M1/M4（typewrite 读表） |
| 36037439 | multi_apps | 0.00 | 15 | 多应用协作链断裂 |
| c288e301 | os | 0.00 | 15 | M3/M4（终端无回显反复输入） |
| 215dfd39 | vlc | 0.00 | 15 | 滚动定位偏差 |
| 08c73485 | thunderbird | 0.00 | 11 | M2 假 DONE |
| 5cfb9197 | impress | 0.00 | 6 | M2 假 DONE（冒烟轮同任务 1.0，M5 方差） |
| 66399b0d | writer | 0.00 | 4 | M2 假 DONE |
| 7c4cc09e | vs_code | 0.00 | 3 | M2 假 DONE |
| 28cc3b7e | os | 0.00 | 0 | 基建：setup 404（单列，不计任务失败） |

> 归因依据：traj.jsonl 逐步动作文本 + 各任务 initial_state.png + results.json，
> 分析脚本与中间产物在 `D:/osworld-tmp/analyze_failures.py`、
> `D:/osworld-tmp/failure_analysis.json`。
