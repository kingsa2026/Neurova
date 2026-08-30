# Neurova 完整单元测试报告
生成时间: 2026-05-20 07:09:54

## 📊 总体统计
- 测试模块: 32
- 总测试数: 75
- 通过率: 78.7%
- 通过: 59 ✅
- 失败: 16 ❌
- 总耗时: 5.85秒

## 📦 各模块详情

### ✅ core.logger
- 总测试: 3
- 通过: 3
- 失败: 0
- 通过率: 100.0%
- 耗时: 0.46秒

### ✅ core.state_manager
- 总测试: 5
- 通过: 5
- 失败: 0
- 通过率: 100.0%
- 耗时: 0.00秒

### ✅ core.config
- 总测试: 5
- 通过: 5
- 失败: 0
- 通过率: 100.0%
- 耗时: 0.00秒

### ❌ core.event_bus
- 总测试: 3
- 通过: 2
- 失败: 1
- 通过率: 66.7%
- 耗时: 0.00秒

#### 失败测试:
- ❌ 事件总线测试
  TypeError: EventBus.publish() takes 2 positional arguments but 3 were given

### ✅ llm.secret_store
- 总测试: 4
- 通过: 4
- 失败: 0
- 通过率: 100.0%
- 耗时: 0.01秒

### ✅ llm.providers.base
- 总测试: 2
- 通过: 2
- 失败: 0
- 通过率: 100.0%
- 耗时: 0.00秒

### ❌ llm.provider_manager
- 总测试: 1
- 通过: 0
- 失败: 1
- 通过率: 0.0%
- 耗时: 0.00秒

#### 失败测试:
- ❌ Provider管理器测试
  ImportError: cannot import name 'ProviderManager' from 'neurova.llm.provider_manager' (E:\项目\Neurova\neurova\llm\provider_manager.py)

### ❌ llm.multi_model_client
- 总测试: 1
- 通过: 0
- 失败: 1
- 通过率: 0.0%
- 耗时: 0.00秒

#### 失败测试:
- ❌ 多模型客户端测试
  ImportError: cannot import name 'MultiModelClient' from 'neurova.llm.multi_model_client' (E:\项目\Neurova\neurova\llm\multi_model_client.py)

### ✅ auth.password_hasher
- 总测试: 5
- 通过: 5
- 失败: 0
- 通过率: 100.0%
- 耗时: 0.72秒

### ✅ auth.user_model
- 总测试: 5
- 通过: 5
- 失败: 0
- 通过率: 100.0%
- 耗时: 0.26秒

### ❌ auth.verification_code
- 总测试: 1
- 通过: 0
- 失败: 1
- 通过率: 0.0%
- 耗时: 0.00秒

#### 失败测试:
- ❌ 验证码测试
  ImportError: cannot import name 'VerificationCodeManager' from 'neurova.auth.verification_code' (E:\项目\Neurova\neurova\auth\verification_code.py)

### ❌ auth.invitation_code
- 总测试: 1
- 通过: 0
- 失败: 1
- 通过率: 0.0%
- 耗时: 0.00秒

#### 失败测试:
- ❌ 邀请码测试
  ImportError: cannot import name 'InvitationCodeManager' from 'neurova.auth.invitation_code' (E:\项目\Neurova\neurova\auth\invitation_code.py)

### ❌ auth.qclaw_binding_model
- 总测试: 2
- 通过: 1
- 失败: 1
- 通过率: 50.0%
- 耗时: 0.08秒

#### 失败测试:
- ❌ QClaw绑定模型测试
  TypeError: QClawBindingModel.create_binding() got an unexpected keyword argument 'qclaw_id'

### ❌ auth.enhanced_user_model
- 总测试: 1
- 通过: 0
- 失败: 1
- 通过率: 0.0%
- 耗时: 0.02秒

#### 失败测试:
- ❌ 增强用户模型测试
  AttributeError: 'str' object has no attribute 'get'

### ✅ security.rbac
- 总测试: 3
- 通过: 3
- 失败: 0
- 通过率: 100.0%
- 耗时: 0.28秒

### ✅ security.data_masking
- 总测试: 3
- 通过: 3
- 失败: 0
- 通过率: 100.0%
- 耗时: 0.00秒

### ❌ security.api_keys
- 总测试: 1
- 通过: 0
- 失败: 1
- 通过率: 0.0%
- 耗时: 0.00秒

#### 失败测试:
- ❌ API密钥测试
  ImportError: cannot import name 'ApiKeyManager' from 'neurova.security.api_keys' (E:\项目\Neurova\neurova\security\api_keys.py)

### ❌ security.firewall
- 总测试: 1
- 通过: 0
- 失败: 1
- 通过率: 0.0%
- 耗时: 0.00秒

#### 失败测试:
- ❌ 防火墙测试
  ImportError: cannot import name 'Firewall' from 'neurova.core.firewall' (E:\项目\Neurova\neurova\core\firewall.py)

### ✅ security.auth_system
- 总测试: 1
- 通过: 1
- 失败: 0
- 通过率: 100.0%
- 耗时: 0.19秒

### ✅ projects.project_manager
- 总测试: 4
- 通过: 4
- 失败: 0
- 通过率: 100.0%
- 耗时: 2.01秒

### ✅ projects.team_manager
- 总测试: 5
- 通过: 5
- 失败: 0
- 通过率: 100.0%
- 耗时: 0.32秒

### ✅ projects.exceptions
- 总测试: 4
- 通过: 4
- 失败: 0
- 通过率: 100.0%
- 耗时: 0.00秒

### ❌ skills.registry
- 总测试: 1
- 通过: 0
- 失败: 1
- 通过率: 0.0%
- 耗时: 0.30秒

#### 失败测试:
- ❌ 技能注册表测试
  TypeError: SkillRegistry.__new__() got an unexpected keyword argument 'base_path'

### ❌ skills.market_searcher
- 总测试: 1
- 通过: 0
- 失败: 1
- 通过率: 0.0%
- 耗时: 0.00秒

#### 失败测试:
- ❌ 市场搜索器测试
  ImportError: cannot import name 'MarketSearcher' from 'neurova.skills.market_searcher' (E:\项目\Neurova\neurova\skills\market_searcher.py)

### ❌ skills.evolution_engine
- 总测试: 1
- 通过: 0
- 失败: 1
- 通过率: 0.0%
- 耗时: 0.00秒

#### 失败测试:
- ❌ 技能进化引擎测试
  ImportError: cannot import name 'EvolutionEngine' from 'neurova.skills.evolution_engine' (E:\项目\Neurova\neurova\skills\evolution_engine.py)

### ✅ channels.manager
- 总测试: 2
- 通过: 2
- 失败: 0
- 通过率: 100.0%
- 耗时: 0.00秒

### ✅ execution_engine.tool_engine
- 总测试: 1
- 通过: 1
- 失败: 0
- 通过率: 100.0%
- 耗时: 0.00秒

### ✅ execution_engine.plan_orchestrator
- 总测试: 1
- 通过: 1
- 失败: 0
- 通过率: 100.0%
- 耗时: 0.00秒

### ❌ cognitive_layers.memory_layer
- 总测试: 4
- 通过: 3
- 失败: 1
- 通过率: 75.0%
- 耗时: 0.92秒

#### 失败测试:
- ❌ 记忆层测试
  PermissionError: [WinError 32] 另一个程序正在使用此文件，进程无法访问。: 'E:\\AppData\\Local\\Temp\\tmpohwmku0l\\memory.db'

### ❌ api.api_router
- 总测试: 1
- 通过: 0
- 失败: 1
- 通过率: 0.0%
- 耗时: 0.00秒

#### 失败测试:
- ❌ API路由测试
  ImportError: cannot import name 'ApiRouter' from 'neurova.core.api_router' (E:\项目\Neurova\neurova\core\api_router.py)

### ❌ admin.admin_service
- 总测试: 1
- 通过: 0
- 失败: 1
- 通过率: 0.0%
- 耗时: 0.00秒

#### 失败测试:
- ❌ 管理员服务测试
  TypeError: AdminService.__init__() missing 1 required positional argument: 'config'

### ❌ admin.resource_quota_manager
- 总测试: 1
- 通过: 0
- 失败: 1
- 通过率: 0.0%
- 耗时: 0.27秒

#### 失败测试:
- ❌ 资源配额管理测试
  TypeError: ResourceQuotaManager.__init__() got an unexpected keyword argument 'base_path'
