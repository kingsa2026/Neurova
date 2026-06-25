// AgentFormPage 智能体表单页单元测试 - TDD 红绿灯垂直切片
//
// 测试范围：AgentFormValidator 字段校验、buildAgentPayload 载荷组装、executeAgentSave 保存流程事件契约。
// 说明：@Component 结构体依赖 HarmonyOS UI 运行时，无法在纯单元测试中实例化，
//       因此针对页面导出的纯函数（AgentFormValidator / buildAgentPayload / executeAgentSave）
//       进行验证，覆盖页面 handleSubmit 的核心数据流与 'navigation:back' 事件契约。
// 模式：参考 ChatPage.test.ets —— 通过 EventBus 事件契约与 Mock API 验证页面行为。
import { describe, it, expect, beforeEach } from '@ohos/hypium';
import { EventBus } from '../../../../main/ets/libs/bus/EventBus';
import { Agent, ApiResponse } from '../../../../main/ets/libs/types';
import {
  AgentFormValidator,
  buildAgentPayload,
  executeAgentSave,
  AgentFormData,
  AgentSaveApi,
} from '../../../../main/ets/pages/AgentFormPage';

// ===========================================================================
// Mock AgentSaveApi：记录调用参数并返回预设响应，用于验证保存流程事件契约
// ===========================================================================
class MockAgentApi implements AgentSaveApi {
  public createData: Partial<Agent> | null = null;
  public updateId: string | null = null;
  public updateData: Partial<Agent> | null = null;
  public response: ApiResponse<Agent> = { code: 0, message: 'ok', data: {} as Agent };
  public shouldThrow: boolean = false;

  async create(data: Partial<Agent>): Promise<ApiResponse<Agent>> {
    this.createData = data;
    if (this.shouldThrow) throw new Error('network error');
    return this.response;
  }

  async update(agentId: string, data: Partial<Agent>): Promise<ApiResponse<Agent>> {
    this.updateId = agentId;
    this.updateData = data;
    if (this.shouldThrow) throw new Error('network error');
    return this.response;
  }
}

// 构造默认表单数据（各字段合法），测试中按需覆盖
function makeForm(overrides: Partial<AgentFormData> = {}): AgentFormData {
  return {
    name: '默认智能体',
    description: '',
    model: '',
    provider: '',
    systemPrompt: '',
    temperature: 0.7,
    maxTokens: 2048,
    topP: 0.9,
    ...overrides,
  };
}

export default function agentFormPageTest() {
  describe('AgentFormPage', () => {
    let bus: EventBus;

    beforeEach(() => {
      bus = EventBus.getInstance();
      bus.clearAll();
    });

    // ========== 切片 1: 名称空值校验 ==========

    it('validate_name_empty_returns_error', 0, () => {
      const err = AgentFormValidator.validateName('');
      expect(err).assertEqual('名称不能为空');
    });

    // ========== 切片 2: 名称超长校验（上限 50 字符） ==========

    it('validate_name_too_long_returns_error', 0, () => {
      const longName = 'a'.repeat(51);
      const err = AgentFormValidator.validateName(longName);
      expect(err).assertEqual('名称不能超过50个字符');
    });

    // ========== 切片 3: 温度越界校验（0-2） ==========

    it('validate_temperature_out_of_range_returns_error', 0, () => {
      expect(AgentFormValidator.validateTemperature(-0.1)).assertEqual('温度必须在0到2之间');
      expect(AgentFormValidator.validateTemperature(2.1)).assertEqual('温度必须在0到2之间');
      expect(AgentFormValidator.validateTemperature(0)).assertNull();
      expect(AgentFormValidator.validateTemperature(2)).assertNull();
      expect(AgentFormValidator.validateTemperature(0.7)).assertNull();
    });

    // ========== 切片 4: 最大 token 越界校验（256-8192） ==========

    it('validate_max_tokens_out_of_range_returns_error', 0, () => {
      expect(AgentFormValidator.validateMaxTokens(255)).assertEqual('最大token必须在256到8192之间');
      expect(AgentFormValidator.validateMaxTokens(8193)).assertEqual('最大token必须在256到8192之间');
      expect(AgentFormValidator.validateMaxTokens(256)).assertNull();
      expect(AgentFormValidator.validateMaxTokens(8192)).assertNull();
      expect(AgentFormValidator.validateMaxTokens(2048)).assertNull();
    });

    // ========== 切片 5: buildAgentPayload create 模式（不含 id） ==========

    it('build_payload_create_mode', 0, () => {
      const form = makeForm({
        name: '助手A',
        description: '测试描述',
        model: 'gpt-4',
        provider: 'openai',
        systemPrompt: '你是助手',
        temperature: 0.5,
        maxTokens: 1024,
        topP: 0.8,
      });
      const payload = buildAgentPayload('create', form);
      // create 模式不应包含 id
      expect((payload as Record<string, Object>)['id']).assertUndefined();
      // 基本字段映射
      expect(payload.name).assertEqual('助手A');
      expect(payload.description).assertEqual('测试描述');
      expect(payload.model).assertEqual('gpt-4');
      expect(payload.provider).assertEqual('openai');
      // config 嵌套结构
      expect(payload.config!.systemPrompt).assertEqual('你是助手');
      expect(payload.config!.temperature).assertEqual(0.5);
      expect(payload.config!.maxTokens).assertEqual(1024);
      expect(payload.config!.topP).assertEqual(0.8);
    });

    // ========== 切片 6: buildAgentPayload edit 模式（含 id） ==========

    it('build_payload_edit_mode_includes_id', 0, () => {
      const form = makeForm({ name: '助手B' });
      const payload = buildAgentPayload('edit', form, 'agent-123');
      expect(payload.id).assertEqual('agent-123');
      expect(payload.name).assertEqual('助手B');
      // config 仍正确组装
      expect(payload.config!.temperature).assertEqual(0.7);
      expect(payload.config!.maxTokens).assertEqual(2048);
      expect(payload.config!.topP).assertEqual(0.9);
    });

    // ========== 切片 7: 保存成功 emit 'navigation:back' ==========

    it('save_success_emits_back_event', 0, () => {
      const api = new MockAgentApi();
      api.response = { code: 0, message: 'ok', data: {} as Agent };
      let backEmitted = false;
      bus.on('navigation:back', () => { backEmitted = true; });

      const form = makeForm({ name: '新智能体' });
      let result = false;
      executeAgentSave('create', form, undefined, api, bus).then(r => { result = r; });
      // 触发微任务刷新
      setTimeout(() => {
        expect(result).assertTrue();
        expect(backEmitted).assertTrue();
        // create 模式应调用 api.create
        expect(api.createData!.name).assertEqual('新智能体');
      }, 10);
    });

    // ========== 切片 8: 保存失败不 emit back，但 emit form:error ==========

    it('save_api_failure_does_not_emit_back', 0, () => {
      const api = new MockAgentApi();
      api.response = { code: 1001, message: '名称已存在', data: {} as Agent };
      let backEmitted = false;
      let errorEmitted = false;
      let errorMsg = '';
      bus.on('navigation:back', () => { backEmitted = true; });
      bus.on('form:error', (data) => {
        errorEmitted = true;
        errorMsg = (data as Record<string, string>)['message'] ?? '';
      });

      const form = makeForm({ name: '重名智能体' });
      let result = true;
      executeAgentSave('create', form, undefined, api, bus).then(r => { result = r; });
      setTimeout(() => {
        // 失败：返回 false，不 emit back
        expect(result).assertFalse();
        expect(backEmitted).assertFalse();
        // 失败：emit form:error 并携带后端消息
        expect(errorEmitted).assertTrue();
        expect(errorMsg).assertEqual('名称已存在');
      }, 10);
    });
  });
}
