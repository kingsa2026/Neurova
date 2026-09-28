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
RUN groupadd -r neurova && useradd -r -g neurova neurova

# 从构建阶段复制依赖
COPY --from=builder /root/.local /home/neurova/.local

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
RUN mkdir -p /app/data /app/logs /app/config && \
    chown -R neurova:neurova /app

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