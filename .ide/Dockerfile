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

# 后端依赖：装的是仓库里那份锁（`requirements-ci.lock`），**不**在此另列包名。
# 另列一份就是教义第 6 条点名的第二份依赖定义，与锁文件必然漂移 —— 而漂移的
# 代价是 CI 绿、开发环境装不上。镜像构建期尚无源码，故先只装锁里那份薄环境；
# 完整 `requirements.txt` 由 `.cnb.yml` 的 stages 在工作区就位后再装。
# 这一步让"开环境即可跑受保护子集"成立，不必等 stages 跑完。
COPY requirements-ci.lock /tmp/requirements-ci.lock
RUN pip install --no-cache-dir -r /tmp/requirements-ci.lock \
    && rm -f /tmp/requirements-ci.lock

# 前端依赖的安装（`npm ci`）留给 `.cnb.yml` 的 stages：它必须在工作区
# （NeurUI/ 目录）就位后才能跑，而该目录是启动时才挂进来的。

WORKDIR /workspace
