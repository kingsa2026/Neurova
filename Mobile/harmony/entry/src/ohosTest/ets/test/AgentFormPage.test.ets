// AgentFormPage 智能体表单页单元测试 - TDD 红绿灯垂直切片
//
// 测试范围：AgentFormValidator 字段校验、buildAgentPayload 载荷组装、executeAgentSave 保存流程事件契约。
// 说明：@Component 结构体依赖 HarmonyOS UI 运行时，无法在纯单元测试中实例化，
//       因此针对页面导出的纯函数（AgentFormValidator / buildAgentPayload / executeAgentSave）
//       进行验证，覆盖页面 handleSubmit 的核心数据流与 'navigation:back' 事件契约。
// 模式：参考 ChatPage.test.ets —— 通过 EventBus 事件契约与 Mock API 验证页面行为。
// 对齐批（2026-11-21）：字段面与 PC AgentFormPage.vue 对齐后同步更新——
//       AgentFormData 去 systemPrompt/topP、增 agentId/execProfile/personality/constitution/TTS；
//       maxTokens 校验范围对齐 PC（100-128000）；载荷 config 用后端实吃 snake_case 键。
import { describe, it, expect, beforeEach } from '@ohos/hypium';
import { EventBus } from '../../../main/ets/libs/bus/EventBus';
import { HttpClient } from '../../../main/ets/libs/api/HttpClient';
import { AgentsApi } from '../../../main/ets/libs/api/modules/AgentsApi';
import { Agent, ApiResponse } from '../../../main/ets/libs/types';
import {
  AgentFormValidator,
  buildAgentPayload,
  executeAgentSave,
  AgentFormData,
} from '../../../main/ets/pages/AgentFormPage';

// ===========================================================================
// Mock AgentsApi：继承具体类（ArkTS 禁结构化类型，executeAgentSave 形参为 AgentsApi），
// 记录调用参数并对齐真实契约（业务失败抛错），用于验证保存流程事件契约
// ===========================================================================
class MockAgentApi extends AgentsApi {
  public createData: Object | null = null;
  public updateId: string | null = null;
  public updateData: Object | null = null;
  public response: ApiResponse<Agent> = { code: 0, message: 'ok', data: {} as Agent };
  public shouldThrow: boolean = false;

  constructor() {
    // create/update 已被覆写，client 仅满足基类构造，不会触网
    super(HttpClient.getInstance());
  }

  async create(data: Object): Promise<Agent> {
    this.createData = data;
    if (this.shouldThrow) throw new Error('network error');
    // 对齐真实 AgentsApi：业务失败（code≠0）抛错，由 executeAgentSave 捕获转 form:error
    if (this.response.code !== 0) throw new Error(this.response.message);
    return this.response.data;
  }

  async update(agentId: string, data: Object): Promise<Agent> {
    this.updateId = agentId;
    this.updateData = data;
    if (this.shouldThrow) throw new Error('network error');
    if (this.response.code !== 0) throw new Error(this.response.message);
    return this.response.data;
  }
}

// 构造默认表单数据（各字段合法），测试中按需覆盖
function makeForm(overrides: Partial<AgentFormData> = {}): AgentFormData {
  const base: AgentFormData = {
    agentId: '',
    name: '默认智能体',
    description: '',
    provider: '',
    model: '',
    execProfile: '',
    temperature: 0.7,
    maxTokens: 4096,
    personality: '',
    constitution: '',
    ttsEnabled: false,
    ttsVoice: '',
    ttsSpeed: 1.0,
    ttsPitch: 1.0,
  };
  // ArkTS 禁 spread：逐字段拷贝覆盖值
  if (overrides.agentId !== undefined) { base.agentId = overrides.agentId; }
  if (overrides.name !== undefined) { base.name = overrides.name; }
  if (overrides.description !== undefined) { base.description = overrides.description; }
  if (overrides.provider !== undefined) { base.provider = overrides.provider; }
  if (overrides.model !== undefined) { base.model = overrides.model; }
  if (overrides.execProfile !== undefined) { base.execProfile = overrides.execProfile; }
  if (overrides.temperature !== undefined) { base.temperature = overrides.temperature; }
  if (overrides.maxTokens !== undefined) { base.maxTokens = overrides.maxTokens; }
  if (overrides.personality !== undefined) { base.personality = overrides.personality; }
  if (overrides.constitution !== undefined) { base.constitution = overrides.constitution; }
  if (overrides.ttsEnabled !== undefined) { base.ttsEnabled = overrides.ttsEnabled; }
  if (overrides.ttsVoice !== undefined) { base.ttsVoice = overrides.ttsVoice; }
  if (overrides.ttsSpeed !== undefined) { base.ttsSpeed = overrides.ttsSpeed; }
  if (overrides.ttsPitch !== undefined) { base.ttsPitch = overrides.ttsPitch; }
  return base;
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

    // ========== 切片 4: 最大 token 越界校验（100-128000，对齐 PC） ==========

    it('validate_max_tokens_out_of_range_returns_error', 0, () => {
      expect(AgentFormValidator.validateMaxTokens(99)).assertEqual('最大Token必须在100到128000之间');
      expect(AgentFormValidator.validateMaxTokens(128001)).assertEqual('最大Token必须在100到128000之间');
      expect(AgentFormValidator.validateMaxTokens(100)).assertNull();
      expect(AgentFormValidator.validateMaxTokens(128000)).assertNull();
      expect(AgentFormValidator.validateMaxTokens(4096)).assertNull();
    });

    // ========== 切片 5: buildAgentPayload create 模式（自定义 agent_id 入体） ==========

    it('build_payload_create_mode', 0, () => {
      const form = makeForm({
        agentId: 'my-agent',
        name: '助手A',
        description: '测试描述',
        provider: 'openai',
        model: 'gpt-4',
        execProfile: 'standard',
        personality: '沉稳',
        constitution: '不作恶',
        ttsEnabled: true,
        ttsVoice: 'Junhao',
        temperature: 0.5,
        maxTokens: 1024,
      });
      const payload = buildAgentPayload('create', form);
      const rec = payload as Object as Record<string, Object>;
      // create 模式：用户自填 agent_id 入体；不应包含 id
      expect(rec['agent_id']).assertEqual('my-agent');
      expect(rec['id']).assertUndefined();
      // 基本字段映射
      expect(payload.name).assertEqual('助手A');
      expect(payload.description).assertEqual('测试描述');
      expect(payload.model).assertEqual('gpt-4');
      expect(payload.provider).assertEqual('openai');
      expect(payload.personality).assertEqual('沉稳');
      expect(payload.constitution).assertEqual('不作恶');
      expect(payload.exec_profile).assertEqual('standard');
      // config 为后端实吃 snake_case 键
      const cfg = payload.config as Object as Record<string, Object>;
      expect(cfg['temperature']).assertEqual(0.5);
      expect(cfg['max_tokens']).assertEqual(1024);
      expect(cfg['tts_enabled']).assertTrue();
      expect(cfg['tts_voice']).assertEqual('Junhao');
    });

    // ========== 切片 6: buildAgentPayload edit 模式（含 id；空 agent_id 不入体） ==========

    it('build_payload_edit_mode_includes_id', 0, () => {
      const form = makeForm({ name: '助手B' });
      const payload = buildAgentPayload('edit', form, 'agent-123');
      expect(payload.id).assertEqual('agent-123');
      expect(payload.name).assertEqual('助手B');
      const rec = payload as Object as Record<string, Object>;
      expect(rec['agent_id']).assertUndefined();
      // config 仍正确组装（snake_case）
      const cfg = payload.config as Object as Record<string, Object>;
      expect(cfg['temperature']).assertEqual(0.7);
      expect(cfg['max_tokens']).assertEqual(4096);
      expect(cfg['tts_enabled']).assertFalse();
      expect(cfg['tts_speed']).assertEqual(1.0);
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
        const created = api.createData as Record<string, Object>;
        expect(created['name']).assertEqual('新智能体');
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
