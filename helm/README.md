# Neurova Kubernetes Helm Chart

Neurova AI Agent 框架的 Kubernetes 部署包，提供完整的生产级部署方案。

## 快速开始

### 前提条件

- Kubernetes 1.19+
- Helm 3.0+
- kubectl 已配置

### 一键部署

```bash
# Linux/macOS
./helm/deploy.sh deploy -e production

# Windows
helm\deploy.bat deploy -e production
```

### 手动部署

```bash
# 1. 安装 Helm Chart
helm install neurova helm/neurova --namespace neurova --create-namespace

# 2. 查看部署状态
kubectl get pods -n neurova -l app.kubernetes.io/name=neurova

# 3. 获取服务访问地址
kubectl get svc -n neurova
```

## 架构概览

```
┌─────────────────────────────────────────────────────────────┐
│                    外部访问层                                  │
├─────────────────────────────────────────────────────────────┤
│  Ingress Controller (Nginx)  ←→  Load Balancer              │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                      服务层                                  │
├─────────────────────────────────────────────────────────────┤
│  Backend Service (9527)  ←→  Frontend Service (8100)        │
│  ConfigMap (配置)        ←→  Secret (密钥)                  │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                      应用层                                  │
├─────────────────────────────────────────────────────────────┤
│  Backend Deployment (FastAPI)  ←→  Frontend Deployment (Vue)│
│  健康检查: /health              ←→  健康检查: /              │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                      数据层                                  │
├─────────────────────────────────────────────────────────────┤
│  PersistentVolume (SQLite)  ←→  EmptyDir (日志/缓存)        │
└─────────────────────────────────────────────────────────────┘
```

## 配置选项

### 环境配置

| 环境 | 配置文件 | 说明 |
|------|----------|------|
| 开发 | `values-development.yaml` | 单副本，无持久化 |
| 测试 | `values.yaml` | 默认配置 |
| 生产 | `values-production.yaml` | 多副本，高可用 |

### 主要参数

```yaml
# 后端配置
backend:
  replicaCount: 1          # 副本数
  image:
    repository: neurova/backend
    tag: latest
  service:
    type: ClusterIP
    port: 9527
  resources:
    requests:
      cpu: 500m
      memory: 1Gi
    limits:
      cpu: 2000m
      memory: 4Gi

# 数据库配置
database:
  persistence:
    enabled: true
    size: 10Gi
    storageClass: standard

# LLM 配置
llm:
  apiKeySecret: neurova-llm-secret
  defaultModel: gpt-4

# Ingress 配置
ingress:
  enabled: true
  className: nginx
  hosts:
    - host: neurova.example.com
      paths:
        - path: /
          pathType: Prefix
```

## 部署命令

### 安装

```bash
# 开发环境
helm install neurova helm/neurova -f helm/neurova/values-development.yaml

# 生产环境
helm install neurova helm/neurova -f helm/neurova/values-production.yaml

# 自定义配置
helm install neurova helm/neurova -f custom-values.yaml
```

### 升级

```bash
# 升级到新版本
helm upgrade neurova helm/neurova

# 使用新配置升级
helm upgrade neurova helm/neurova -f helm/neurova/values-production.yaml
```

### 卸载

```bash
# 卸载 Helm Chart
helm uninstall neurova

# 删除 PersistentVolumeClaim（可选）
kubectl delete pvc neurova-data
```

## 故障排查

### 查看 Pod 状态

```bash
kubectl get pods -n neurova -l app.kubernetes.io/name=neurova
```

### 查看日志

```bash
# 后端日志
kubectl logs -f deployment/neurova-backend -n neurova

# 前端日志（如果启用）
kubectl logs -f deployment/neurova-frontend -n neurova
```

### 进入 Pod 调试

```bash
kubectl exec -it deployment/neurova-backend -n neurova -- /bin/bash
```

### 检查服务状态

```bash
kubectl get svc -n neurova
kubectl get ingress -n neurova
kubectl get pvc -n neurova
```

## 生产环境建议

### 1. 启用高可用

```yaml
# values-production.yaml
backend:
  replicaCount: 3
  
hpa:
  enabled: true
  minReplicas: 2
  maxReplicas: 10
  targetCPUUtilizationPercentage: 70
```

### 2. 配置 Ingress

```yaml
ingress:
  enabled: true
  className: nginx
  annotations:
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
    nginx.ingress.kubernetes.io/proxy-body-size: "50m"
  hosts:
    - host: neurova.example.com
      paths:
        - path: /
          pathType: Prefix
  tls:
    - secretName: neurova-tls
      hosts:
        - neurova.example.com
```

### 3. 配置持久化存储

```yaml
database:
  persistence:
    enabled: true
    storageClass: ssd
    size: 100Gi
    accessMode: ReadWriteOnce
```

### 4. 配置密钥

```bash
# 创建 LLM API 密钥 Secret
kubectl create secret generic neurova-llm-secret \
  --from-literal=api-key=your-api-key-here \
  -n neurova
```

### 5. 监控和日志

```yaml
monitoring:
  enabled: true
  serviceMonitor:
    enabled: true
    namespace: monitoring
    interval: 30s

logging:
  level: INFO
  format: json
```

## 文件结构

```
helm/
├── neurova/                    # Helm Chart 目录
│   ├── Chart.yaml              # Chart 元数据
│   ├── values.yaml             # 默认配置
│   ├── values-production.yaml  # 生产环境配置
│   ├── values-development.yaml # 开发环境配置
│   ├── README.md               # Chart 文档
│   └── templates/              # 模板文件
│       ├── _helpers.tpl        # 辅助模板
│       ├── deployment-backend.yaml
│       ├── deployment-frontend.yaml
│       ├── service-backend.yaml
│       ├── service-frontend.yaml
│       ├── configmap.yaml
│       ├── secret.yaml
│       ├── pvc.yaml
│       ├── ingress.yaml
│       ├── hpa.yaml
│       ├── serviceaccount.yaml
│       └── NOTES.txt           # 安装说明
├── deploy.sh                   # Linux/macOS 部署脚本
├── deploy.bat                  # Windows 部署脚本
├── README.md                   # 部署文档
└── neurova-architecture.html   # 架构图
```

## Docker 构建

### 构建镜像

```bash
# 构建后端镜像
docker build -t neurova/backend:latest .

# 推送到镜像仓库
docker push neurova/backend:latest
```

### 本地测试

```bash
# 使用 docker-compose 启动
docker-compose up -d

# 访问服务
curl http://localhost:9527/health
```

## 故障排除

### 常见问题

1. **Pod 无法启动**
   - 检查镜像是否正确：`kubectl describe pod <pod-name>`
   - 检查资源限制：`kubectl top pod`

2. **服务无法访问**
   - 检查 Service 状态：`kubectl get svc`
   - 检查 Endpoints：`kubectl get endpoints`

3. **持久化存储问题**
   - 检查 PVC 状态：`kubectl get pvc`
   - 检查 StorageClass：`kubectl get sc`

4. **健康检查失败**
   - 检查应用日志：`kubectl logs <pod-name>`
   - 检查健康检查端点：`curl http://localhost:9527/health`

### 获取帮助

```bash
# 查看 Helm Chart 信息
helm list -n neurova
helm history neurova -n neurova

# 查看 Kubernetes 资源
kubectl get all -n neurova
```

## 许可证

MIT License