# ============================================================================
# Neurova 云原生开发环境
# ============================================================================
#
# 用途：分支页面点「云原生开发」时启动的开发容器。它与生产镜像、CI 三面共用
# 同一套口径，而不是各写各的：
#
#   · 解释器 python:3.12 —— 事实源是仓库根 `Dockerfile` 的 `FROM python:`
#     （生产镜像与受保护子集那一腿跑的就是它，见 Issue #301）。开发环境
#     跑另一个版本，等于同一个 commit 在两处行为分叉，而故障只在其中一侧可见。
#   · Node 20 —— 事实源是 `.github/workflows/ci.yml` 的 `node-version`
#     （compose 前端镜像同源，见 scripts/ci/deploy_config_consistency_check.py 的 R4）。
#
# 三处口径由 tests/unit/ci/test_dev_environment_contract.py 常驻钉住：本文件
# 的解释器 / Node 大版本与上述事实源脱钩即红。
#
# 为什么是这个基础镜像而不是 `cnbcool/default-dev-env`：
#   默认镜像里没有本仓的生产解释器，也没有前端工具链 —— 用它只能得到一个
#   "能开 WebIDE、但跑不了本仓测试"的壳。故本文件以 `python:3.12-slim` 为基，
#   在其上装 Node 20 与 code-server。
#
# 单/双容器模式（官方《单/双容器模式》）：
#   下文装了 code-server ⇒ 平台走**单容器模式**，WebIDE 与开发环境同容器，
#   直接访问得到本仓工具链。基础镜像中若没有 code-server，平台会另起一个
#   code-server 容器（双容器模式），WebIDE 连的是那一侧，开发容器反而要多
#   一层跨容器终端。故 code-server 是"能进得去"的必要件，不是可选项。
#
# 客户端版本控制（官方《常见问题解答》）：code-server 来自社区，个别版本有
#   导致 WebIDE 不可用的 bug。此处不钉版本、随 install.sh 取稳定版；若某次
#   环境创建后 WebIDE 打不开，按官方指引钉 `--version <可用版本>` 即可。
#
# 预装口径：**整装运行环境**，不是"薄壳等 stages 补"。
#   本文件在构建期就把本仓后端全量依赖装上（`requirements-full.lock`，与生产
#   镜像的 `requirements.txt` 同源编译），前端 `npm ci` 与 playwright 浏览器
#   也一并装机。理由：开发环境的用途是"开箱即可开发与验证"，而本仓大半功能
#   路径（语义检索 onnxruntime/transformers、TTS edge-tts、抓取 playwright、
#   桌面自动化 pyautogui）都在 `requirements-ci.txt` 刻意排除的重依赖之列。
#   用薄环境当开发环境，这些路径开箱即 import 失败 —— 而"预装好运行环境"
#   正是本项的诉求。
# ============================================================================

FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LANGUAGE=C.UTF-8 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# 系统依赖：
#   git/wget/unzip/curl —— 常规开发工具；
#   openssh-server —— VSCode / Cursor / CodeBuddy 客户端经 Remote-SSH 连入的前提；
#   build-essential —— 本仓若干依赖（如 bcrypt / pycryptodome）在无 wheel 时需就地编译；
#   bash-completion/vim —— 交互便利，无功能耦合。
RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        curl \
        wget \
        unzip \
        openssh-server \
        build-essential \
        bash-completion \
        vim \
    && rm -rf /var/lib/apt/lists/*

# Node 20（大版本与 CI 同源）：用 NodeSource 官方源装，不用 `apt install nodejs`
# —— 后者在 Debian 系给出的是旧大版本，与 CI 的 node-version 分叉。
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# code-server（WebIDE 服务端）与 cnb-welcome（进入环境时自动执行 CNB_WELCOME_CMD）。
# cnb-welcome 在默认镜像里预装，自定义环境必须自己装，否则欢迎命令静默不执行。
RUN curl -fsSL https://code-server.dev/install.sh | sh \
    && code-server --install-extension cnbcool.cnb-welcome \
    && code-server --install-extension redhat.vscode-yaml \
    && code-server --install-extension ms-python.python \
    && code-server --install-extension charliermarsh.ruff \
    && code-server --install-extension dbaeumer.vscode-eslint \
    && code-server --install-extension vue.volar \
    && rm -rf /root/.cache/code-server

# CodeBuddy Code CLI（`codebuddy` 命令）。
#
# 官方《CodeBuddy Web》：云开发入口页（WebIDE / CodeBuddy Web / 我的云原生开发）
# 只在镜像装有 `codebuddy` 且版本 >= 2.137.0 时展示 CodeBuddy Web 入口。
# 自定义镜像不装它，就等于把平台自带的一条入口静默丢掉 —— 而症状只是"入口页
# 少一个按钮"，没人会把它和本文件联系起来。
#
# 本仓的协作流程大量借助 AI 角色（NPC + CodeBuddy），这条入口是它的浏览器端。
RUN npm install -g @tencent-ai/codebuddy-code \
    && codebuddy --version

# 后端全量运行环境（构建期装机，不留给 stages）。
#
# 装的是 `requirements-full.lock` —— 它与生产镜像装的 `requirements.txt` 同源
# （`uv pip compile --universal requirements.txt -o requirements-full.lock`），
# 是同一份依赖的**锁定形态**，不是第二份清单（教义第 6 条）。
#
# 为什么不用 `requirements-ci.lock`：那份是"够 CI 跑静态门禁与审计回归的薄子集"，
# 文件头明文列了被刻意排除的重依赖（onnxruntime / sentence-transformers /
# transformers / tokenizers / edge-tts / playwright / pyautogui ...）。开发环境
# 装它，本仓语义检索 / TTS / 抓取 / 桌面自动化四条链开箱即不可用。
COPY requirements-full.lock /tmp/requirements-full.lock
# 装到**系统** site-packages（不 `--user`）：`--user` 落 `/root/.local`，只有 root
# 的 `sys.path` 认它 —— 平台若以非 root 起会话，`import onnxruntime` 立刻 ModuleNotFound，
# 而镜像里明明装着。系统级安装对任何用户一致。
RUN pip install --no-cache-dir -r /tmp/requirements-full.lock \
    && rm -f /tmp/requirements-full.lock

# playwright 浏览器二进制（pip 装包 ≠ 能跑浏览器）。
#
# `requirements-full.lock` 里的 playwright 只是**客户端**：真正抓取/截图时它去
# `~/.cache/ms-playwright` 找浏览器，找不到就报 "Executable doesn't exist"。
# 这是"依赖装了却跑不动"最典型的一种，必须在构建期一次装好。
#
# `--with-deps` 一并装无图形界面容器所需的系统库（X11 / 字体 / 音视频编解码），
# 缺了它表现为"包都装了、一跑就崩在 libXXX.so"，且报错点在运行时而不是安装时。
# 装到镜像级的 `/ms-playwright` 并显式导 PLAYWRIGHT_BROWSERS_PATH，让**非 root
# 用户与 stages** 都能找到同一份（默认落 `~/.cache`，用户一切换就丢）。
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN python -m playwright install --with-deps chromium \
    && chmod -R a+rX /ms-playwright

# 非 root 会话也要能读到整套依赖：系统 site-packages 默认组可读，
# 但 `pip install --with-deps` 顺手改过权限的目录在这里统一放宽一次。
RUN chmod -R a+rX /usr/local/lib/python3.12/site-packages

WORKDIR /workspace
