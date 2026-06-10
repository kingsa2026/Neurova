# Neurova Helm Chart

Neurova AI Agent 框架的 Kubernetes 部署包。

## 前提条件

- Kubernetes 1.19+
- Helm 3.0+
- PV provisioner 支持（如果使用持久化存储）

## 安装

```bash
# 安装 Chart
helm install neurova ./helm/neurova

# 使用自定义配置安装
helm install neurova ./helm/neurova -f custom-values.yaml

# 安装到指定命名空间
helm install neurova ./helm/neurova --namespace neurova --create-namespace
```

## 配置

### 主要配置项

| 参数 | 描述 | 默认值 |
|------|------|--------|
| `backend.image.repository` | 后端镜像仓库 | `neurova/backend` |
| `backend.image.tag` | 后端镜像标签 | `latest` |
| `backend.replicaCount` | 后端副本数 | `1` |
| `backend.service.type` | 后端服务类型 | `ClusterIP` |
| `backend.service.port` | 后端服务端口 | `9527` |
| `backend.resources.requests.cpu` | CPU 请求 | `500m` |
| `backend.resources.requests.memory` | 内存请求 | `1Gi` |
| `backend.resources.limits.cpu` | CPU 限制 | `2000m` |
| `backend.resources.limits.memory` | 内存限制 | `4Gi` |
| `database.persistence.enabled` | 启用持久化存储 | `true` |
| `database.persistence.size` | 存储大小 | `10Gi` |
| `llm.apiKeySecret` | LLM API 密钥 Secret 名称 | `neurova-llm-secret` |
| `ingress.enabled` | 启用 Ingress | `false` |
| `hpa.enabled` | 启用自动扩缩容 | `false` |

### 高级配置

#### 环境变量

```yaml
backend:
  env:
    - name: NEUROVA_PORT
      value: "9527"
    - name: NEUROVA_ENV
      value: "production"
    - name: LOG_LEVEL
      value: "INFO"
```

#### 持久化存储

```yaml
database:
  persistence:
    enabled: true
    existingClaim: "neurova-data-pvc"
    storageClass: "standard"
    size: 20Gi
    mountPath: /app/data
```

#### Ingress 配置

```yaml
ingress:
  enabled: true
  className: nginx
  annotations:
    nginx.ingress.kubernetes.io/rewrite-target: /
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

#### 自动扩缩容

```yaml
hpa:
  enabled: true
  minReplicas: 2
  maxReplicas: 10
  targetCPUUtilizationPercentage: 80
  targetMemoryUtilizationPercentage: 80
```

## 升级

```bash
# 升级 Chart
helm upgrade neurova ./helm/neurova

# 使用新的配置文件升级
helm upgrade neurova ./helm/neurova -f custom-values.yaml

# 回滚到上一个版本
helm rollback neurova
```

## 卸载

```bash
# 卸载 Chart
helm uninstall neurova

# 删除 PersistentVolumeClaim（可选）
kubectl delete pvc neurova-data-neurova-0
```

## 故障排查

### 查看 Pod 状态

```bash
kubectl get pods -l app.kubernetes.io/name=neurova
```

### 查看日志

```bash
# 后端日志
kubectl logs -f deployment/neurova-backend

# 前端日志（如果启用）
kubectl logs -f deployment/neurova-frontend
```

### 进入 Pod 调试

```bash
kubectl exec -it deployment/neurova-backend -- /bin/bash
```

### 检查服务状态

```bash
kubectl get svc -l app.kubernetes.io/name=neurova
kubectl get ingress -l app.kubernetes.io/name=neurova
```

## 架构说明

### 组件

- **Backend**: FastAPI 应用，提供 REST API 和 WebSocket 服务
- **Frontend**（可选）: Vue 3 前端，生产模式下由后端服务静态文件
- **Database**: SQLite 数据库，存储 Agent 数据和记忆
- **ConfigMap**: 应用配置
- **Secret**: 敏感信息（LLM API 密钥等）

### 端口

- **9527**: 后端 API 服务端口
- **8100**: 前端开发服务器端口（仅开发模式）

### 存储

- `/app/data`: SQLite 数据库存储
- `/app/logs`: 应用日志
- `/app/config`: 配置文件挂载点

## 生产环境建议

1. **启用持久化存储**: 确保数据持久化
2. **配置 Ingress**: 使用 Ingress 控制器暴露服务
3. **启用自动扩缩容**: 根据负载自动调整副本数
4. **配置资源限制**: 避免资源耗尽
5. **启用健康检查**: 确保服务可用性
6. **配置 Secret**: 安全存储敏感信息
7. **监控和日志**: 集成 Prometheus 和日志收集系统

## 许可证

MIT License