# Neurova Backend Dockerfile
# 生产模式：后端服务静态文件

# 多阶段构建
#
# 本文件是 CI 解释器版本的事实源：受保护子集（unit-tests）自 Issue #301 起
# 只跑一腿，那一腿跑的就是这里的基础镜像版本——此前是 3.10-slim，等于生产
# 解释器从未过 CI 门禁。判据见 tests/unit/ci/test_unit_tests_single_leg.py。
# 同时须 ≥ scripts/config.py 的 MIN_PYTHON_VERSION(3,10)。
FROM python:3.12-slim as builder

# 设置工作目录
WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY requirements.txt .

# 安装 Python 依赖
RUN pip install --no-cache-dir --user -r requirements.txt

# 生产阶段
FROM python:3.12-slim as production

# 设置工作目录
WORKDIR /app

# 安装运行时依赖
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 创建非 root 用户
#
# `-m` 不是装饰：不建家目录时 shadow 的默认 HOME 仍是 `/<user>`（= `/neurova`），
# 而它不存在、也归 root 所有。那不只是"少个目录"——**Python 对不可写 HOME 只
# 告警不退出**（site 的 `Can't create user site-packages directory` 之后照旧
# 执行），于是非 root 身份带着一个写不进的 HOME 把问题推迟到运行期：
#   * `modelscope` 的 SDK 缓存根 `~/.modelscope` 建不出来（E1022 Permission denied）；
#   * `huggingface_hub` 的 `~/.cache` 落点不可写（curl/xet 侧 os error 13）；
#   * 用户站点 `~/.local/lib/pythonX.Y/site-packages` 与 pip 的落点分叉。
# 三源依次失败 ⇒ `ensure_model("bge-small-zh-v1.5")` 全败 ⇒ 后端起不来，
# 而 `docker build` 全绿（实测见 Issue #330，构建 cnb-h61-1k3lf1duo）。
# 守卫：tests/unit/deploy/test_image_runtime_selfproof.py。
RUN groupadd -r neurova && useradd -r -m -d /home/neurova -g neurova neurova

# 从构建阶段复制依赖
#
# `--chown` 与 `-m` 是一对：`pip install --user` 把包装进 `/home/neurova/.local`，
# 而 Python 的**用户站点**（`site.getusersitepackages()`）按 `$HOME` 推导——两者
# 必须指向同一个可写目录，否则包在盘上、`import` 却找不到（非 root 运行时 HOME
# 隶属 root ⇒ 用户站点直接不挂载，镜像在 `import uvicorn` 处崩）。
# `PYTHONPATH=/app` 不含 `.local`，导入面全靠用户站点这一处成立。
COPY --from=builder --chown=neurova:neurova /root/.local /home/neurova/.local

# 复制应用代码
COPY neurova/ ./neurova/
COPY start_server.py .
COPY requirements.txt .

# 复制配置文件
COPY config/ ./config/

# 复制随代码走的模型资产（数据根/仓库根契约的"仓库根"那一半）
#
# 不拷进镜像的后果不是启动失败，而是**运行时静默降级**：
# neurova/embedding/onnx_embedding.py 经 repoAsset("models","embedding",
# "bge-small-zh-v1.5") 从仓库根读权重，容器里读不到 ⇒ 初始化失败 ⇒
# unified_vector_store 只 logger.warning 一句就降级 TF-IDF（语义检索质量
# 整体退化，日志里无线索）。判据：tests/unit/deploy/test_image_model_assets.py
# 与 .dockerignore 的模型段白名单必须成对成立（放行 + 拷贝）。
#
# 只拷必需那一份：权重本体（model.onnx）与元数据。同目录的
# model.safetensors / pytorch_model.bin 由 .dockerignore 挡掉——它们是同一
# 权重的另两种编码（sentence-transformers / torch 形态），onnx 路径不需要。
# MANIFEST.json 是模型清单（models/MANIFEST.json），运行时靠它判断资产是否齐全。
COPY models/embedding/bge-small-zh-v1.5/ ./models/embedding/bge-small-zh-v1.5/
COPY models/MANIFEST.json ./models/MANIFEST.json

# 创建数据目录
#
# 家目录一起交给运行用户：容器里所有"默认落 $HOME"的缓存（modelscope / HF /
# xet）都写在这里，运行期 drop 到 neurova 之后再 chown 已经晚了。
RUN mkdir -p /app/data /app/logs /app/config && \
    chown -R neurova:neurova /app && \
    chown -R neurova:neurova /home/neurova

# 设置环境变量
ENV PYTHONPATH=/app
ENV PATH=/home/neurova/.local/bin:$PATH
ENV PYTHONUNBUFFERED=1

# 切换到非 root 用户
USER neurova

# 暴露端口
EXPOSE 9527

# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:9527/health || exit 1

# 启动命令
CMD ["python", "start_server.py"]