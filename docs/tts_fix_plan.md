# TTS初始化失败修复方案

## 问题总结
EdgeTTS初始化失败，系统回退到Mock TTS。根本原因是缺少Microsoft Visual C++ Build Tools，导致aiohttp无法编译。

## 修复方案

### 方案1：安装Microsoft Visual C++ Build Tools（推荐）

#### 步骤1：下载Build Tools
1. 访问：https://visualstudio.microsoft.com/visual-cpp-build-tools/
2. 下载"Build Tools for Visual Studio 2022"

#### 步骤2：安装Build Tools
1. 运行安装程序
2. 选择"Workloads"标签
3. 勾选"Desktop development with C++"
4. 点击"Install"

#### 步骤3：安装aiohttp
```bash
pip install aiohttp>=3.8.0
```

#### 步骤4：安装edge-tts
```bash
pip install edge-tts>=6.1.0
```

#### 步骤5：验证安装
```bash
python -c "import aiohttp; print(f'aiohttp {aiohttp.__version__}')"
python -c "import edge_tts; print(f'edge_tts {edge_tts.__version__}')"
```

### 方案2：使用Docker容器

#### 步骤1：创建Dockerfile
```dockerfile
FROM python:3.12-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 复制requirements.txt
COPY requirements.txt .

# 安装Python依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY . .

# 暴露端口
EXPOSE 9527

# 启动命令
CMD ["python", "start_server.py"]
```

#### 步骤2：构建Docker镜像
```bash
docker build -t neurova-tts .
```

#### 步骤3：运行Docker容器
```bash
docker run -p 9527:9527 neurova-tts
```

### 方案3：降级Python版本

#### 步骤1：安装Python 3.12
1. 下载Python 3.12安装程序
2. 安装Python 3.12

#### 步骤2：创建虚拟环境
```bash
python3.12 -m venv venv
source venv/bin/activate  # Linux/Mac
# 或
.\venv\Scripts\activate  # Windows
```

#### 步骤3：安装依赖
```bash
pip install -r requirements.txt
```

### 方案4：使用其他TTS引擎

#### 步骤1：安装huggingface_hub
```bash
pip install huggingface_hub
```

#### 步骤2：下载MOSSNanTTS模型
```bash
# 手动下载模型
# 模型URL: https://huggingface.co/MOSSNanTTS/moss-tts-nano
```

#### 步骤3：配置TTS引擎
```python
# 在配置中指定使用MOSSNanTTS
tts_config = TTSConfig(
    engine="moss-nano",
    model_path="models/tts/moss-nano",
    tokenizer_path="models/tts/moss-nano",
)
```

## 实施建议

### 短期（立即）
1. **确认当前系统工作正常**: Mock TTS已回退，功能正常
2. **记录问题**: 在项目文档中记录TTS回退情况

### 中期（1-2天）
1. **安装C++ Build Tools**: 为编译aiohttp做准备
2. **安装edge-tts**: 实现高质量中文TTS
3. **测试TTS功能**: 验证真实语音合成

### 长期（1周）
1. **优化依赖管理**: 考虑使用预编译包或Docker容器
2. **添加TTS引擎选择**: 允许用户在UI中选择TTS引擎
3. **监控TTS质量**: 收集用户反馈，优化TTS体验

## 验证步骤

### 1. 验证C++ Build Tools安装
```bash
# 检查cl.exe是否存在
where cl.exe
```

### 2. 验证aiohttp安装
```bash
python -c "import aiohttp; print(f'aiohttp {aiohttp.__version__}')"
```

### 3. 验证edge-tts安装
```bash
python -c "import edge_tts; print(f'edge_tts {edge_tts.__version__}')"
```

### 4. 测试TTS合成
```bash
python test_edge_tts_direct.py
```

## 风险评估

### 风险1：C++ Build Tools安装失败
- **可能性**: 低
- **影响**: 高
- **缓解**: 提供详细安装指南，准备Docker方案

### 风险2：Python版本不兼容
- **可能性**: 中
- **影响**: 高
- **缓解**: 准备降级Python方案

### 风险3：网络问题导致模型下载失败
- **可能性**: 中
- **影响**: 中
- **缓解**: 提供手动下载指南，准备离线安装包

## 成功标准

### 功能标准
1. EdgeTTS初始化成功
2. 中文语音合成正常
3. 音频质量满足要求

### 性能标准
1. 合成延迟 < 2秒
2. 音频大小合理（< 1MB/分钟）
3. 内存使用稳定

### 用户体验标准
1. 语音清晰自然
2. 中文发音准确
3. 系统响应及时