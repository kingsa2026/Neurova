# Neurova Backend Dockerfile
# 生产模式：后端服务静态文件

# 多阶段构建
#
# 基础镜像版本必须落在 CI 实测矩阵内（.github/workflows/ci.yml 与 .cnb.yml 的
# unit-tests 跑 3.11/3.12）：此前是 3.10-slim，等于生产解释器从未过 CI 门禁。
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