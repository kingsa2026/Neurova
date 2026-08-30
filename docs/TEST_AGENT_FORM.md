# 测试 Agent 新建页面的服务商下拉列表

## 测试步骤

### 1. 打开浏览器并访问页面
- 访问 `http://localhost:5173/agents/new`
- 按 `F12` 打开开发者工具

### 2. 清除缓存并硬刷新
- 右键点击刷新按钮
- 选择"清空缓存并硬性重新加载"

### 3. 查看控制台日志
在 Console 标签中，应该看到以下日志：
```
[AgentForm] ========== onMounted 开始 ==========
[AgentForm] 开始调用 providerAPI.list()...
[AgentForm] API 响应 (pr): ...
[AgentForm] pr.data: ...
[AgentForm] pr.data?.providers: ...
[AgentForm] providers 数量: 23
[AgentForm] 已配置服务商 (has_api_key=true): [{…}, {…}]
[AgentForm] 已配置服务商数量: 2
[AgentForm] providerOpts: [{…}, {…}]
[AgentForm] providerOpts 长度: 2
[AgentForm] ========== onMounted 结束 ==========
```

### 4. 测试服务商下拉列表
1. 找到"自动路由"开关，关闭它
2. 找到"服务商"下拉列表
3. 点击下拉列表
4. 应该显示 **2 个选项**：
   - `DeepSeek (2个模型)`
   - `火山方舟 Coding Plan (10个模型)`

### 5. 如果看不到日志或下拉列表为空
截图控制台日志并发送给开发者。

## 预期结果

| 项目 | 预期结果 |
|------|------------|
| 控制台日志 | 显示 `[AgentForm]` 开头的日志 |
| 服务商数量 | 2 个 |
| 服务商名称 | DeepSeek, 火山方舟 Coding Plan |

## 实际结果

请在下面记录实际测试结果：

- [ ] 控制台有日志输出
- [ ] 服务商下拉列表有 2 个选项
- [ ] 可以选择服务商
- [ ] 选择服务商后，模型下拉列表会加载对应的模型

如果任何一项不符合预期，请截图并描述问题。
