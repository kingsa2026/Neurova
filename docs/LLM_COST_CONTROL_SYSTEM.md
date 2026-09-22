# Neurova LLM Cost Control System

## 🎯 执行摘要

本文档描述 Neurova 的 LLM 成本控制机制设计，解决当前成本追踪粗放的问题。

**核心改进**:
- ✅ **Architecture Guards **(CI-enforced): 4 个强制 guard 防止成本失控
- ✅ **Universal Cost Ledger**: 所有 LLM 调用必须记账
- ✅ **Big-brain Model Guard**: 仅允许 agent turn 使用昂贵模型
- ✅ **Hourly Rollup**: 性能优化的成本聚合表
- ✅ **Budget & Alerting**: 实时预算监控和告警

---

## 📊 现状分析

### Current State: Cost Tracking Issues

| Issue | Impact | Severity |
|-------|--------|----------|
| ❌ 缺少 CI-enforced guards | 可能绕过成本追踪 | 🔴 Critical |
| ❌ 无 Big-brain model 限制 | 可能在非关键路径使用昂贵模型 | 🟠 High |
| ❌ 缺少 hourly rollup | 查询慢，Dashboard 性能差 | 🟡 Medium |
| ❌ 无预算告警 | 无法及时发现成本异常 | 🟠 High |

### Target State

| Feature | Implementation | Benefit |
|---------|---------------|---------|
| ✅ Architecture Guards | CI scripts + pre-commit hooks | 100% 合规 |
| ✅ Universal Cost Ledger | All calls logged to `llm_calls` | Full observability |
| ✅ Big-brain Guard | Only agent turns can use expensive models | 60-80% cost reduction |
| ✅ Hourly Rollup | Pre-aggregated cost data | 10x query performance |
| ✅ Budget Alerts | Real-time monitoring | Proactive cost control |

---

## 🏗️ 系统架构

### 1. Database Schema

```sql
-- ============================================================================
-- Core Cost Ledger Table
-- ============================================================================
CREATE TABLE IF NOT EXISTS llm_calls (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id TEXT NOT NULL,
    turn_id TEXT,
    session_id TEXT,
    
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    
    direction TEXT CHECK (direction IN ('input', 'output')) NOT NULL,
    input_tokens INT NOT NULL,
    output_tokens INT,
    
    cache_read_tokens INT DEFAULT 0,
    cache_write_tokens INT DEFAULT 0,
    
    cost_usd DECIMAL(10,6) NOT NULL,
    called_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for common queries
CREATE INDEX idx_llm_calls_agent_time ON llm_calls(agent_id, called_at);
CREATE INDEX idx_llm_calls_provider_model ON llm_calls(provider, model);
CREATE INDEX idx_llm_calls_session ON llm_calls(session_id);

-- ============================================================================
-- Hourly Rollup Table (Performance Optimization)
-- ============================================================================
CREATE TABLE IF NOT EXISTS llm_calls_rollup (
    agent_id TEXT,
    hour TIMESTAMPTZ NOT NULL,
    provider TEXT,
    model TEXT,
    
    total_input BIGINT,
    total_output BIGINT,
    total_cache_read BIGINT,
    total_cache_write BIGINT,
    total_cost DECIMAL(12,6),
    
    PRIMARY KEY (agent_id, hour, provider, model)
);

-- Auto-materialized view for fast queries
CREATE MATERIALIZED VIEW IF NOT EXISTS llm_calls_hourly_summary AS
SELECT 
    agent_id,
    date_trunc('hour', called_at) as hour,
    provider,
    model,
    SUM(input_tokens) as total_input,
    SUM(output_tokens) as total_output,
    SUM(cache_read_tokens) as total_cache_read,
    SUM(cache_write_tokens) as total_cache_write,
    SUM(cost_usd) as total_cost,
    COUNT(*) as call_count
FROM llm_calls
GROUP BY agent_id, hour, provider, model;

-- Refresh materialized view every hour
-- SELECT refresh_materialized_view_concurrently('llm_calls_hourly_summary');

-- ============================================================================
-- Daily/Weekly/Monthly Aggregates (for admin dashboard)
-- ============================================================================
CREATE TABLE IF NOT EXISTS llm_calls_daily_agg (
    agent_id TEXT,
    day DATE NOT NULL,
    provider TEXT,
    model TEXT,
    total_input BIGINT,
    total_output BIGINT,
    total_cost DECIMAL(12,6),
    call_count BIGINT,
    PRIMARY KEY (agent_id, day, provider, model)
);
```

---

### 2. Architecture Guards (CI-enforced)

#### Guard 1: Big-brain Model Guard ⭐⭐⭐⭐⭐

**Purpose**: 防止在非关键路径使用昂贵模型（如 gpt-4, claude-3-opus）

**Implementation Location**: `scripts/guard-big-brain.mjs`

**Rules**:
```javascript
// Expensive models (only allowed in agent turns)
const EXPENSIVE_MODELS = [
    'gpt-4', 'gpt-4-turbo', 'gpt-4o',
    'claude-3-opus', 'claude-3.5-opus',
    'gemini-1.5-pro',
];

// Allowed contexts for expensive models
const ALLOWED_CONTEXTS = [
    'agent_turn',      // Agent response generation
    'summarization',   // Conversation summarization
];

// Forbidden contexts
const FORBIDDEN_CONTEXTS = [
    'triage',          // Small-brain classification
    'embedding',       // Vector search
    'metadata',        // Quick lookups
    'validation',      // Input validation
];
```

**Enforcement**:
```bash
# CI check
npm run guard:big-brain

# Pre-commit hook
git commit --allow-empty
# → Fails if code uses expensive models in forbidden contexts
```

**Example Violation**:
```python
# ❌ BAD: Using gpt-4 for triage
@track_llm_call(provider="openai", model="gpt-4")
def classify_message(message):
    # Triage should use small model!
    pass

# ✅ GOOD: Using small model for triage
@track_llm_call(provider="openai", model="gpt-3.5-turbo")
def classify_message(message):
    pass
```

---

#### Guard 2: Tracking Guard ⭐⭐⭐⭐⭐

**Purpose**: 确保所有 LLM 调用都记录到 `llm_calls` 表

**Implementation Location**: `scripts/guard-llm-tracked.mjs`

**Rules**:
```javascript
// Scan all Python files for LLM API calls
const LLM_CALL_PATTERNS = [
    'client.chat.completions.create',  // OpenAI
    'anthropic.messages.create',       // Claude
    'google.genai...',                 // Gemini
    'ollama.chat',                     // Ollama
];

// Check if each call is decorated with @track_llm_call
```

**Enforcement**:
```bash
# CI check
npm run guard:llm-tracked

# Must pass before merge
```

**Example Violation**:
```python
# ❌ BAD: No cost tracking decorator
async def call_llm(messages):
    response = await client.chat.completions.create(...)
    return response

# ✅ GOOD: With cost tracking
@track_llm_call(provider=LLMProvider.OPENAI, model="gpt-3.5-turbo", agent_id="default")
async def call_llm(messages):
    response = await client.chat.completions.create(...)
    return response
```

---

#### Guard 3: Engine Registry Guard ⭐⭐⭐⭐

**Purpose**: 新引擎必须完整集成，不允许部分实现

**Rules**:
- ✅ 完整的 Adapter 实现
- ✅ 完整的 Cost Tracking
- ✅ 完整的 Error Handling
- ✅ 完整的 Tests

---

#### Guard 4: Migration Lock Guard ⭐⭐⭐

**Purpose**: 禁止危险的 DDL 模式

**Forbidden Patterns**:
```sql
-- ❌ BAD: Full table rewrite
ALTER TABLE conversations ADD COLUMN new_field UUID DEFAULT gen_random_uuid();

-- ❌ BAD: Blocking index creation
CREATE INDEX idx_messages_created_at ON messages(created_at);

-- ✅ GOOD: Non-blocking migration
ALTER TABLE conversations ADD COLUMN new_field UUID NULL;
UPDATE conversations SET new_field = gen_random_uuid() WHERE id > $1 LIMIT 1000;
ALTER TABLE conversations ALTER COLUMN new_field SET NOT NULL;

-- ✅ GOOD: Concurrent index
CREATE INDEX CONCURRENTLY idx_messages_created_at ON messages(created_at);
```

---

### 3. Cost Budget & Alerting System

#### Budget Configuration

```python
# neurova/config/cost_budgets.py

class CostBudget:
    """Cost budget configuration"""
    
    # Hourly budgets per agent
    HOURLY_BUDGETS = {
        "default": Decimal("0.05"),      # $0.05/hour
        "premium": Decimal("0.20"),      # $0.20/hour
        "enterprise": Decimal("1.00"),   # $1.00/hour
    }
    
    # Daily budgets per company
    DAILY_BUDGETS = {
        "company_1": Decimal("50.00"),   # $50/day
        "company_2": Decimal("100.00"),  # $100/day
    }
    
    # Monthly budgets
    MONTHLY_BUDGETS = {
        "company_1": Decimal("1500.00"), # $1500/month
    }
    
    # Alert thresholds (percentage of budget)
    ALERT_THRESHOLDS = [0.50, 0.75, 0.90, 0.95, 1.00]
```

#### Real-time Monitoring

```python
# neurova/services/cost_monitor.py

class CostMonitor:
    """Real-time cost monitoring and alerting"""
    
    async def check_budget_violations(self):
        """Check for budget violations and send alerts"""
        
        # Get current hour usage
        current_usage = await self.get_current_hour_usage()
        
        for agent_id, usage in current_usage.items():
            budget = COST_BUDGETS.HOURLY_BUDGETS.get(agent_id)
            if not budget:
                continue
            
            violation_ratio = usage.total_cost / budget
            
            if violation_ratio >= 0.90:
                await self.send_alert(
                    agent_id=agent_id,
                    type="budget_warning",
                    ratio=violation_ratio,
                    message=f"⚠️  Agent {agent_id} at {violation_ratio*100:.0f}% of hourly budget"
                )
            
            if violation_ratio >= 1.00:
                await self.enforce_limit(
                    agent_id=agent_id,
                    action="throttle_or_block",
                    message=f"🚫 Agent {agent_id} exceeded hourly budget - throttling"
                )
    
    async def get_current_hour_usage(self) -> Dict[str, dict]:
        """Get current hour usage from rollup table"""
        
        async with self.db_pool.acquire() as conn:
            hour_start = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
            
            rows = await conn.fetch("""
                SELECT 
                    agent_id,
                    SUM(cost_usd) as total_cost,
                    SUM(input_tokens) as total_input,
                    SUM(output_tokens) as total_output,
                    COUNT(*) as call_count
                FROM llm_calls_rollup
                WHERE hour = $1
                GROUP BY agent_id
            """, hour_start)
            
            return {row['agent_id']: dict(row) for row in rows}
```

---

## 🔄 实施计划

### Phase 1: Database Schema Updates (1 人日)

- [ ] Create `llm_calls` table (if not exists)
- [ ] Create `llm_calls_rollup` table
- [ ] Create materialized views
- [ ] Add indexes
- [ ] Write migration script

### Phase 2: Architecture Guards (2 人日)

- [ ] Implement `guard-big-brain.mjs`
- [ ] Implement `guard-llm-tracked.mjs`
- [ ] Integrate with CI pipeline
- [ ] Add pre-commit hooks
- [ ] Write tests

### Phase 3: Budget & Alerting (2 人日)

- [ ] Implement `CostMonitor` service
- [ ] Add budget configuration
- [ ] Integrate with notification system
- [ ] Create admin dashboard endpoints
- [ ] Write tests

### Phase 4: Optimization (1 人日)

- [ ] Add hourly rollup automation
- [ ] Optimize queries
- [ ] Add caching layer
- [ ] Performance testing

---

## 📈 预期收益

### Cost Reduction

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| Expensive model misuse | ~30% of calls | <5% of calls | **83% reduction** |
| Untracked calls | ~15% of calls | 0% | **100% elimination** |
| Query performance | 5-10s | <500ms | **10-20x faster** |
| Budget overruns | Frequent | Rare | **90% reduction** |

### Operational Benefits

- ✅ **Full Observability**: Every LLM call tracked
- ✅ **Proactive Control**: Budget alerts prevent overspending
- ✅ **Performance**: Fast queries for real-time dashboards
- ✅ **Compliance**: CI-enforced guards ensure consistency

---

## 📝 相关文档

- [Neurova Cost Tracker](../neurova/models/cost_tracking.py)
- [成本聚合端点](../neurova/api/endpoints/cost_rollup_api.py)
- [预算端点](../neurova/api/endpoints/budget_api.py)

> 原「Cost API Endpoints」指向 `neurova/api/endpoints/cost_api.py`。该模块与
> `/api/v1/cost-rollup`、`/api/v1/budgets` 逐条重叠、口径不同，按修复教义第 6 条
> 收口为一份后删除（处置见 `tests/unit/endpointWiringBaseline.txt`）。

---

**Status**: Design Complete  
**Priority**: High  
**Estimated Effort**: 6 人日  
**Impact**: ⭐⭐⭐⭐⭐
