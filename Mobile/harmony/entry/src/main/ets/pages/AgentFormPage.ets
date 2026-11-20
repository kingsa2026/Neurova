/**
 * AgentFormPage - 智能体表单页（创建/编辑共用，功能对齐 PC AgentFormPage.vue）
 *
 * 职责：提供智能体创建/编辑表单，含字段校验、载荷组装、保存提交流程
 * 设计：Stack [Column TopNavMenu(动态标题+返回) + Scroll 表单] + [通用选择器浮层]；
 *       通过路由参数 mode('create'|'edit') + agentId? 区分模式；
 *       edit 模式 aboutToAppear 调用 api.agents.get 回填表单；
 *       服务商/模型/执行档位/音色走通用选择器浮层（模型随服务商过滤）；
 *       成功后 router.back()；失败 emit 'form:error' 并提示
 *
 * 与 PC AgentFormPage.vue 的字段面对齐（2026-11-21）：
 *   agent_id(建) / name* / provider(选) / model(选，随服务商过滤) /
 *   所属分组(只读) / 描述 / 执行档位(不设置|lite|standard|heavy) /
 *   温度 0-2 / 最大Token 100-128000 / 性格 / 宪法 / TTS(开关+音色+语速+音调)
 * 诚实边界：
 *   - 系统提示词/TopP 不做（PC P1-5 已裁：后端 AgentConfig 无 system_prompt、
 *     top_p 无消费方，表单收集即丢属谎报）
 *   - 音色试听不做（试听文件在 PC 站点 /tts-preview/，端侧无该资源）
 *   - 载荷 config 用后端实吃的 snake_case 键（max_tokens/tts_enabled/tts_voice/
 *     tts_speed/tts_pitch——agent.py _tts_fields_from_body_config 只认这些键；
 *     PC 发 camelCase 会被端点静默丢弃）
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassInput、GlassButton
 *   - ../components/common/IconBtn：返回钮
 *   - ../libs/api/ApiFacade：统一 API 门面（agents/providers/admin）
 *   - ../libs/state/stores/AgentsStore：Agent 状态
 *   - ../routing/Router：统一路由跳转 + RouteNames
 *   - ../libs/style/StyleManager、../libs/logger/Logger、../libs/message/MessageManager
 *   - ../libs/bus/EventBus、../libs/types
 *
 * 用法：
 *   Router.push(RouteNames.AGENT_FORM, { mode: 'create' });
 *   Router.push(RouteNames.AGENT_FORM, { mode: 'edit', agentId: 'a1' });
 */

import { TopNavMenu, GlassInput, GlassButton } from '../components/glass';
import { AppIcon } from '../components/common/AppIcon';
import { ApiFacade } from '../libs/api/ApiFacade';
import { AgentsApi } from '../libs/api/modules/AgentsApi';
import { AgentsStore } from '../libs/state/stores/AgentsStore';
import { Router, RouteNames } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { EventBus } from '../libs/bus/EventBus';
import { Agent, AgentConfig, ApiResponse } from '../libs/types';

/** 日志标签 */
const TAG = 'AgentFormPage';

// ===========================================================================
// 通用选择器选项（服务商/模型/执行档位/音色共用）
// ===========================================================================

/** 选择器选项（header 非空 = 分组头行，不可点） */
export interface PickerOption {
  label: string;
  value: string;
  header: string;
}

/** 服务商选项（/providers 已启用且有模型的子集投影） */
export interface ProviderOption {
  id: string;
  name: string;
}

/** 模型选项（/models 投影，provider=所属服务商 id） */
export interface ModelOption {
  id: string;
  name: string;
  provider: string;
}

// ===========================================================================
// 表单数据结构（导出供测试用）
// ===========================================================================

/** 智能体表单数据（字段面与 PC AgentFormPage.vue 对齐） */
export interface AgentFormData {
  /** 自定义 Agent ID（create 可选，空=自动生成；edit 只读回显） */
  agentId: string;
  name: string;
  description: string;
  provider: string;
  model: string;
  /** 执行档位：''=跟随部署档位 */
  execProfile: string;
  temperature: number;
  maxTokens: number;
  personality: string;
  constitution: string;
  ttsEnabled: boolean;
  ttsVoice: string;
  ttsSpeed: number;
  ttsPitch: number;
}

// ===========================================================================
// AgentFormValidator - 字段校验器（纯函数，导出供测试用）
// ===========================================================================

/**
 * 智能体表单校验器
 * 约定：返回 null 表示通过，返回非空字符串表示错误消息
 */
export class AgentFormValidator {
  /** 校验名称：非空且 1-50 字符 */
  static validateName(name: string): string | null {
    if (!name || name.length === 0) {
      return '名称不能为空';
    }
    if (name.length > 50) {
      return '名称不能超过50个字符';
    }
    return null;
  }

  /** 校验温度：0-2 范围 */
  static validateTemperature(t: number): string | null {
    if (t < 0 || t > 2) {
      return '温度必须在0到2之间';
    }
    return null;
  }

  /** 校验最大 token：100-128000 范围（对齐 PC a-input-number :min=100 :max=128000） */
  static validateMaxTokens(n: number): string | null {
    if (n < 100 || n > 128000) {
      return '最大Token必须在100到128000之间';
    }
    return null;
  }
}

// ===========================================================================
// buildAgentPayload - 组装提交载荷（导出供测试用）
// ===========================================================================

/** 表单错误事件载荷（EventBus emit 字面量必须对应声明类型） */
export interface FormErrorPayload {
  field: string;
  message: string;
}

/** 保存完成事件载荷 */
export interface SaveDonePayload {
  success: boolean;
  mode: string;
}

/** 提交载荷（键名与后端 CreateAgentRequest/UpdateAgentRequest 实吃字段一致） */
export interface AgentFormPayload {
  /** create 且用户自填 id 时携带；edit 走 URL 不走体（冗余键后端忽略） */
  agent_id?: string;
  id?: string;
  name: string;
  description?: string;
  model?: string;
  provider?: string;
  personality?: string;
  constitution?: string;
  /** ''=清除回退部署档位 */
  exec_profile?: string;
  config: Record<string, Object>;
}

/**
 * 组装提交载荷（config 键为后端实吃的 snake_case：
 * temperature/max_tokens/tts_enabled/tts_voice/tts_speed/tts_pitch）
 */
export function buildAgentPayload(
  mode: 'create' | 'edit',
  form: AgentFormData,
  agentId?: string,
): AgentFormPayload {
  const config: Record<string, Object> = {
    'temperature': form.temperature,
    'max_tokens': form.maxTokens,
    'tts_enabled': form.ttsEnabled,
    'tts_voice': form.ttsVoice,
    'tts_speed': form.ttsSpeed,
    'tts_pitch': form.ttsPitch,
  };
  const payload: AgentFormPayload = {
    name: form.name,
    description: form.description,
    model: form.model || undefined,
    provider: form.provider || undefined,
    personality: form.personality,
    constitution: form.constitution,
    exec_profile: form.execProfile,
    config: config,
  };
  if (mode === 'create' && form.agentId.trim().length > 0) {
    payload.agent_id = form.agentId.trim();
  }
  if (mode === 'edit' && agentId) {
    payload.id = agentId;
  }
  return payload;
}

// ===========================================================================
// executeAgentSave - 保存流程纯函数（导出供测试用）
// ===========================================================================

/**
 * 执行保存流程：校验 → 组装载荷 → 调用 API → emit 事件
 * @param mode 'create' | 'edit'
 * @param form 表单数据
 * @param agentId edit 模式必填
 * @param api 保存 API 抽象（页面传 ApiFacade.agents，测试传 Mock）
 * @param bus 事件总线（成功 emit 'navigation:back'，失败 emit 'form:error'）
 * @returns true 表示成功；false 表示失败
 */
export async function executeAgentSave(
  mode: 'create' | 'edit',
  form: AgentFormData,
  agentId: string | undefined,
  api: AgentsApi,
  bus: EventBus,
): Promise<boolean> {
  // 1. 前端校验：名称非空
  const nameError = AgentFormValidator.validateName(form.name);
  if (nameError) {
    const err: FormErrorPayload = { field: 'name', message: nameError };
    bus.emit('form:error', err);
    return false;
  }

  // 2. 组装载荷
  const payload = buildAgentPayload(mode, form, agentId);

  // 3. 调用 API
  try {
    if (mode === 'create') {
      await api.create(payload);
    } else {
      await api.update(agentId as string, payload);
    }
    // 成功：emit 'navigation:back'
    const done: SaveDonePayload = { success: true, mode: mode };
    bus.emit('navigation:back', done);
    return true;
  } catch (e) {
    // 失败：emit 'form:error' 携带后端 detail / 兜底消息
    const exErr: FormErrorPayload = { field: '', message: (e as Error).message };
    bus.emit('form:error', exErr);
    return false;
  }
}

// ===========================================================================
// AgentFormPage - 页面组件
// ===========================================================================

@Component
export struct AgentFormPage {
  // 表单字段（受控）
  @State agentIdText: string = '';
  @State name: string = '';
  @State description: string = '';
  @State provider: string = '';
  @State providerLabel: string = '';
  @State model: string = '';
  @State modelLabel: string = '';
  @State execProfile: string = '';
  @State execProfileLabel: string = '不设置（跟随部署档位）';
  @State temperature: number = 0.7;
  @State maxTokensText: string = '4096';
  @State personality: string = '';
  @State constitution: string = '';
  @State ttsEnabled: boolean = false;
  @State ttsVoice: string = '';
  @State ttsVoiceLabel: string = '';
  @State ttsSpeed: number = 1.0;
  @State ttsPitch: number = 1.0;
  // 分组只读展示（跟随创建者部门组；edit 回显当前组名）
  @State groupName: string = '';
  // 加载态（edit 模式加载详情 / 提交中）
  @State loading: boolean = false;
  // 路由模式
  @State mode: 'create' | 'edit' = 'create';
  private agentId: string = '';

  // 服务商/模型选项（provider.py /providers + model.py /models）
  @State private providers: ProviderOption[] = [];
  @State private models: ModelOption[] = [];

  // 通用选择器浮层状态
  @State private pickerShow: boolean = false;
  @State private pickerTitle: string = '';
  @State private pickerOptions: PickerOption[] = [];
  @State private pickerCurrent: string = '';
  private pickerCallback: (value: string) => void = () => {};

  // 统一库单例
  private api = ApiFacade.getInstance();
  private agentsStore = new AgentsStore();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private msg = MessageManager.getInstance();
  private bus = EventBus.getInstance();

  /**
   * 页面出现：解析路由参数；并行拉服务商/模型/分组选项；edit 模式回填详情；
   * 订阅 form:error 事件
   */
  aboutToAppear() {
    const param = this.router.getCurrentParam() as Record<string, Object> | undefined;
    if (param) {
      const m = param['mode'] as string;
      if (m === 'edit') {
        this.mode = 'edit';
      }
      const id = param['agentId'] as string;
      if (id) {
        this.agentId = id;
      }
    }
    this.bus.on('form:error', this.onFormError);
    this.loadFormOptions();
    if (this.mode === 'edit' && this.agentId) {
      this.loadAgent();
    } else {
      this.groupName = '跟随创建者部门组';
    }
  }

  /** 页面消失：取消订阅 form:error，避免内存泄漏 */
  aboutToDisappear() {
    this.bus.off('form:error', this.onFormError);
  }

  /** form:error 事件处理器：展示错误消息（arrow function 保留 this 绑定） */
  private onFormError = (data: Object): void => {
    const rec = data as Record<string, string>;
    const message = rec && rec['message'] ? rec['message'] : '保存失败';
    this.msg.error(message);
  };

  /** 拉服务商/模型/分组选项（fail-soft：失败置空，选择器退化为基础输入） */
  private async loadFormOptions(): Promise<void> {
    try {
      const providers = await this.api.providers.list();
      const list: ProviderOption[] = [];
      for (const p of providers) {
        // 对齐 PC：只收已启用且有模型的服务商
        if (p.is_active !== false && p.models_count > 0) {
          const opt: ProviderOption = { id: p.provider_id, name: p.name || p.provider_id };
          list.push(opt);
        }
      }
      this.providers = list;
      const models = await this.api.providers.listModels();
      const mList: ModelOption[] = [];
      for (const m of models) {
        if (m.provider.length > 0 && m.provider !== 'system') {
          const opt: ModelOption = { id: m.model_id, name: m.name || m.model_id, provider: m.provider };
          mList.push(opt);
        }
      }
      this.models = mList;
    } catch (e) {
      this.logger.warn(TAG, '服务商/模型选项加载失败', e as Error);
    }
    try {
      const groups = await this.api.admin.listGroups();
      if (this.mode === 'edit' && this.groupName === '') {
        // 编辑态回显当前组名（id→名映射，失败保留原 id）
        for (const g of groups) {
          if (g.group_id === this.currentGroupId) {
            this.groupName = g.name;
          }
        }
      }
    } catch (e) {
      this.logger.warn(TAG, '分组列表加载失败', e as Error);
    }
  }

  /** 当前绑定的分组 id（edit 回填用） */
  private currentGroupId: string = '';

  /**
   * 加载智能体详情（edit 模式）：api.agents.get → 回填表单字段
   * 失败：MessageManager.error + router.back()
   */
  private async loadAgent(): Promise<void> {
    this.loading = true;
    try {
      const a = await this.api.agents.get(this.agentId);
      this.agentIdText = a.id;
      this.name = a.name;
      this.description = a.description ?? '';
      this.provider = a.provider ?? '';
      this.providerLabel = a.provider ?? '';
      this.model = a.model ?? '';
      this.modelLabel = a.model ?? '';
      this.personality = a.personality ?? '';
      this.constitution = a.constitution ?? '';
      this.execProfile = a.execProfile ?? '';
      this.execProfileLabel = a.execProfile ?? '不设置（跟随部署档位）';
      this.temperature = a.config?.temperature ?? 0.7;
      this.maxTokensText = (a.config?.maxTokens ?? 4096).toString();
      this.ttsEnabled = a.config?.ttsEnabled ?? false;
      this.ttsVoice = a.config?.ttsVoice ?? '';
      this.ttsVoiceLabel = a.config?.ttsVoice ?? '';
      this.ttsSpeed = a.config?.ttsSpeed ?? 1.0;
      this.ttsPitch = a.config?.ttsPitch ?? 1.0;
      this.currentGroupId = a.groupId ?? '';
      if (this.currentGroupId.length > 0) {
        this.groupName = this.currentGroupId;
      } else {
        this.groupName = '跟随创建者部门组';
      }
    } catch (e) {
      this.logger.error(TAG, '加载智能体失败', e as Error);
      this.msg.error('加载智能体失败');
      this.router.back();
    } finally {
      this.loading = false;
    }
  }

  /**
   * 提交保存：组装表单数据 → executeAgentSave → 成功 router.back()
   */
  private async handleSubmit(): Promise<void> {
    const parsedMaxTokens = Number(this.maxTokensText);
    const form: AgentFormData = {
      agentId: this.agentIdText,
      name: this.name,
      description: this.description,
      provider: this.provider,
      model: this.model,
      execProfile: this.execProfile,
      temperature: this.temperature,
      maxTokens: Number.isNaN(parsedMaxTokens) ? -1 : parsedMaxTokens,
      personality: this.personality,
      constitution: this.constitution,
      ttsEnabled: this.ttsEnabled,
      ttsVoice: this.ttsVoice,
      ttsSpeed: this.ttsSpeed,
      ttsPitch: this.ttsPitch,
    };
    this.loading = true;
    try {
      const ok = await executeAgentSave(
        this.mode, form, this.agentId || undefined, this.api.agents, this.bus,
      );
      if (ok) {
        this.msg.success('保存成功');
        this.router.back();
      }
      // 失败时由 onFormError 事件处理器展示错误
    } catch (e) {
      this.logger.error(TAG, '保存失败', e as Error);
      this.msg.error('保存失败');
    } finally {
      this.loading = false;
    }
  }

  /** 取消：直接返回上一页 */
  private handleCancel(): void {
    this.router.back();
  }

  /** 动态标题：create→"创建智能体"，edit→"编辑智能体" */
  private title(): string {
    return this.mode === 'edit' ? '编辑智能体' : '创建智能体';
  }

  // -----------------------------------------------------------------------
  // 通用选择器浮层
  // -----------------------------------------------------------------------

  /** 打开选择器（current=当前值，命中项打勾） */
  private showPicker(title: string, options: PickerOption[], current: string,
    cb: (value: string) => void): void {
    this.pickerTitle = title;
    this.pickerOptions = options;
    this.pickerCurrent = current;
    this.pickerCallback = cb;
    this.pickerShow = true;
  }

  /** 选中回写并关闭浮层 */
  private pickOption(value: string): void {
    this.pickerShow = false;
    this.pickerCallback(value);
  }

  /** 服务商选择器（已启用且有模型的服务商） */
  private openProviderPicker(): void {
    const options: PickerOption[] = [];
    for (const p of this.providers) {
      const opt: PickerOption = { label: p.name, value: p.id, header: '' };
      options.push(opt);
    }
    this.showPicker('选择服务商', options, this.provider, (v: string) => {
      this.provider = v;
      for (const p of this.providers) {
        if (p.id === v) {
          this.providerLabel = p.name;
        }
      }
      // 对齐 PC onProviderChange：模型不属于新服务商时清空
      let valid = false;
      for (const m of this.models) {
        if (m.id === this.model && m.provider === v) {
          valid = true;
        }
      }
      if (!valid) {
        this.model = '';
        this.modelLabel = '';
      }
    });
  }

  /** 模型选择器（随服务商过滤） */
  private openModelPicker(): void {
    if (this.provider.length === 0) {
      this.msg.info('请先选择服务商');
      return;
    }
    const options: PickerOption[] = [];
    for (const m of this.models) {
      if (m.provider === this.provider) {
        const opt: PickerOption = { label: m.name, value: m.id, header: '' };
        options.push(opt);
      }
    }
    this.showPicker('选择模型', options, this.model, (v: string) => {
      this.model = v;
      for (const m of this.models) {
        if (m.id === v) {
          this.modelLabel = m.name;
        }
      }
    });
  }

  /** 执行档位选择器（''=跟随部署档位，对齐 PC allow-clear 语义） */
  private openExecProfilePicker(): void {
    const options: PickerOption[] = [];
    const unset: PickerOption = { label: '不设置（跟随部署档位）', value: '', header: '' };
    const lite: PickerOption = { label: 'lite', value: 'lite', header: '' };
    const standard: PickerOption = { label: 'standard', value: 'standard', header: '' };
    const heavy: PickerOption = { label: 'heavy', value: 'heavy', header: '' };
    options.push(unset);
    options.push(lite);
    options.push(standard);
    options.push(heavy);
    this.showPicker('执行档位', options, this.execProfile, (v: string) => {
      this.execProfile = v;
      this.execProfileLabel = v.length > 0 ? v : '不设置（跟随部署档位）';
    });
  }

  /** 音色选择器（本地 moss 10 音色 + 在线 edge 4 音色，带分组头） */
  private openVoicePicker(): void {
    const options: PickerOption[] = [];
    const localHeader: PickerOption = { label: '', value: '', header: '本地音色（moss）' };
    options.push(localHeader);
    const moss: string[][] = [
      ['Junhao', '俊豪'], ['Zhiming', '志明'], ['Weiguo', '卫国'], ['Xiaoyu', '小宇'],
      ['Yuewen', '悦文'], ['Lingyu', '灵雨'], ['Trump', '川普'], ['Adam', '亚当'],
      ['Ava', '艾娃'], ['Bella', '贝拉'],
    ];
    for (const v of moss) {
      const opt: PickerOption = { label: v[1], value: v[0], header: '' };
      options.push(opt);
    }
    const onlineHeader: PickerOption = { label: '', value: '', header: '在线音色（edge-tts）' };
    options.push(onlineHeader);
    const edge: string[][] = [
      ['zh-CN-XiaoxiaoNeural', '晓晓 · 在线'], ['zh-CN-XiaoyiNeural', '晓伊 · 在线'],
      ['zh-CN-YunxiNeural', '云希 · 在线'], ['zh-CN-YunyangNeural', '云扬 · 在线'],
    ];
    for (const v of edge) {
      const opt: PickerOption = { label: v[1], value: v[0], header: '' };
      options.push(opt);
    }
    this.showPicker('选择音色', options, this.ttsVoice, (v: string) => {
      this.ttsVoice = v;
      this.ttsVoiceLabel = v.length > 0 ? v : '';
    });
  }

  build() {
    Stack() {
      Column() {
        // 顶部导航栏：动态标题 + 返回按钮
        TopNavMenu({
          title: this.title(),
          showBack: true,
          showMenu: false,
          onBack: () => { this.handleCancel(); }
        })

        // 表单容器：可滚动
        Scroll() {
          Column() {
            // 名称（必填，1-50 字符）
            Text('名称 *')
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .alignSelf(ItemAlign.Start)
            GlassInput({
              placeholder: '请输入智能体名称',
              value: this.name,
              type: 'text',
              maxLength: 50,
              onChange: (v: string) => { this.name = v; }
            })
              .margin({ top: 4 })

            // Agent ID（create 可选自定义；edit 只读回显）
            Text(this.mode === 'edit' ? 'Agent ID（只读）' : 'Agent ID（选填，留空自动生成）')
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .alignSelf(ItemAlign.Start)
              .margin({ top: this.sm.getSpacing('md') })
            GlassInput({
              placeholder: '自定义 Agent ID',
              value: this.mode === 'edit' ? this.agentIdText : this.agentIdText,
              type: 'text',
              maxLength: 64,
              disabled: this.mode === 'edit',
              onChange: (v: string) => { this.agentIdText = v; }
            })
              .margin({ top: 4 })

            // 服务商（下拉选择，随 PC 同源 /providers）
            Text('服务商')
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .alignSelf(ItemAlign.Start)
              .margin({ top: this.sm.getSpacing('md') })
            this.selectorRow(this.providerLabel !== '' ? this.providerLabel : '请选择服务商',
              () => { this.openProviderPicker(); })

            // 模型（下拉选择，随服务商过滤）
            Text('模型')
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .alignSelf(ItemAlign.Start)
              .margin({ top: this.sm.getSpacing('md') })
            this.selectorRow(this.modelLabel !== '' ? this.modelLabel : (this.provider.length > 0 ? '请选择模型' : '请先选服务商'),
              () => { this.openModelPicker(); })

            // 所属分组（只读：跟随创建者部门组）
            Text('所属分组')
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .alignSelf(ItemAlign.Start)
              .margin({ top: this.sm.getSpacing('md') })
            this.selectorRow(this.groupName, () => {})

            // 描述
            Text('描述')
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .alignSelf(ItemAlign.Start)
              .margin({ top: this.sm.getSpacing('md') })
            GlassInput({
              placeholder: '请输入描述（选填）',
              value: this.description,
              type: 'text',
              maxLength: 200,
              onChange: (v: string) => { this.description = v; }
            })
              .margin({ top: 4 })

            // 执行档位（lite/standard/heavy；空=跟随部署档位）
            Text('执行档位')
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .alignSelf(ItemAlign.Start)
              .margin({ top: this.sm.getSpacing('md') })
            this.selectorRow(this.execProfileLabel, () => { this.openExecProfilePicker(); })

            // 温度 Slider（0-2，步长 0.1，默认 0.7）
            Row() {
              Text('温度')
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.sm.getColor('text_secondary'))
              Text(this.temperature.toFixed(1))
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.sm.getColor('primary'))
                .margin({ left: 8 })
            }
            .width('100%')
            .justifyContent(FlexAlign.SpaceBetween)
            .margin({ top: this.sm.getSpacing('md') })
            Slider({
              value: this.temperature,
              min: 0,
              max: 2,
              step: 0.1,
            })
              .selectedColor(this.sm.getColor('primary'))
              .onChange((v: number) => { this.temperature = v; })

            // 最大 Token（输入框，100-128000 步长 100，对齐 PC a-input-number）
            Row() {
              Text('最大 Token')
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.sm.getColor('text_secondary'))
              Text('(100 - 128000)')
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.sm.getColor('text_tertiary'))
                .margin({ left: 8 })
            }
            .width('100%')
            .justifyContent(FlexAlign.SpaceBetween)
            .margin({ top: this.sm.getSpacing('md') })
            GlassInput({
              placeholder: '4096',
              value: this.maxTokensText,
              type: 'text',
              maxLength: 7,
              onChange: (v: string) => { this.maxTokensText = v; }
            })

            // 性格（textarea）
            Text('性格')
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .alignSelf(ItemAlign.Start)
              .margin({ top: this.sm.getSpacing('md') })
            GlassInput({
              placeholder: '请输入性格设定（选填）',
              value: this.personality,
              type: 'text',
              maxLength: 2000,
              onChange: (v: string) => { this.personality = v; }
            })
              .margin({ top: 4 })

            // 宪法（textarea）
            Text('宪法')
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .alignSelf(ItemAlign.Start)
              .margin({ top: this.sm.getSpacing('md') })
            GlassInput({
              placeholder: '请输入行为准则（选填）',
              value: this.constitution,
              type: 'text',
              maxLength: 2000,
              onChange: (v: string) => { this.constitution = v; }
            })
              .margin({ top: 4 })

            // TTS 配置卡
            Row() {
              Text('语音合成')
                .fontSize(this.sm.getFontSize('body'))
                .fontColor(this.sm.getColor('text_primary'))
                .layoutWeight(1)
              Toggle({ type: ToggleType.Switch, isOn: this.ttsEnabled })
                .selectedColor(this.sm.getColor('primary'))
                .onChange((isOn: boolean) => { this.ttsEnabled = isOn; })
            }
            .width('100%')
            .margin({ top: this.sm.getSpacing('md') })

            if (this.ttsEnabled) {
              Text('音色')
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.sm.getColor('text_secondary'))
                .alignSelf(ItemAlign.Start)
                .margin({ top: this.sm.getSpacing('md') })
              this.selectorRow(this.ttsVoiceLabel !== '' ? this.ttsVoiceLabel : '请选择音色',
                () => { this.openVoicePicker(); })

              Row() {
                Text('语速')
                  .fontSize(this.sm.getFontSize('caption'))
                  .fontColor(this.sm.getColor('text_secondary'))
                Text(this.ttsSpeed.toFixed(1))
                  .fontSize(this.sm.getFontSize('caption'))
                  .fontColor(this.sm.getColor('primary'))
                  .margin({ left: 8 })
              }
              .width('100%')
              .justifyContent(FlexAlign.SpaceBetween)
              .margin({ top: this.sm.getSpacing('md') })
              Slider({
                value: this.ttsSpeed,
                min: 0.5,
                max: 2,
                step: 0.1,
              })
                .selectedColor(this.sm.getColor('primary'))
                .onChange((v: number) => { this.ttsSpeed = v; })

              Row() {
                Text('音调')
                  .fontSize(this.sm.getFontSize('caption'))
                  .fontColor(this.sm.getColor('text_secondary'))
                Text(this.ttsPitch.toFixed(1))
                  .fontSize(this.sm.getFontSize('caption'))
                  .fontColor(this.sm.getColor('primary'))
                  .margin({ left: 8 })
              }
              .width('100%')
              .justifyContent(FlexAlign.SpaceBetween)
              .margin({ top: this.sm.getSpacing('md') })
              Slider({
                value: this.ttsPitch,
                min: 0.5,
                max: 2,
                step: 0.1,
              })
                .selectedColor(this.sm.getColor('primary'))
                .onChange((v: number) => { this.ttsPitch = v; })
            }

            // 保存按钮（primary, block）
            GlassButton({
              text: this.loading ? '保存中...' : '保存',
              type: 'primary',
              block: true,
              disabled: this.loading,
              onTap: () => { this.handleSubmit(); }
            })
              .margin({ top: this.sm.getSpacing('lg') })

            // 取消按钮（default, block）
            GlassButton({
              text: '取消',
              type: 'default',
              block: true,
              disabled: this.loading,
              onTap: () => { this.handleCancel(); }
            })
              .margin({ top: this.sm.getSpacing('sm') })
          }
          .width('100%')
          .alignItems(HorizontalAlign.Start)
        }
        .width('100%')
        .layoutWeight(1)
        .scrollBar(BarState.Auto)
        .padding({
          left: this.sm.getSpacing('md'),
          right: this.sm.getSpacing('md'),
          top: this.sm.getSpacing('sm'),
          bottom: this.sm.getSpacing('sm'),
        })
      }
      .width('100%')
      .height('100%')
      // 通用选择器浮层（服务商/模型/执行档位/音色共用）
      if (this.pickerShow) {
        this.buildPickerOverlay()
      }
    }
    .width('100%')
    .height('100%')
    .backgroundColor(this.sm.getColor('background'))
  }

  /** 表单选择行：伪输入框观感（label/占位 + 箭头），点击弹选择器 */
  @Builder
  selectorRow(value: string, onTap: () => void) {
    Row() {
      Text(value)
        .fontSize(this.sm.getFontSize('body'))
        .fontColor(this.sm.getColor(value === '' ? 'text_tertiary' : 'text_primary'))
      Blank()
      AppIcon({ name: 'chev', iconSize: 14, color: this.sm.getColor('text_tertiary') })
    }
    .width('100%')
    .padding({ left: 14, right: 14, top: 12, bottom: 12 })
    .borderRadius(12)
    .backgroundColor(this.sm.getColor('glass'))
    .border({ width: 1, color: this.sm.getColor('border') })
    .margin({ top: 4 })
    .onClick(() => { onTap(); })
  }

  /** 通用选择器浮层：遮罩 + 居中面板（标题 + 可滚选项 + 当前项打勾）；Stack 让面板叠在遮罩上 */
  @Builder
  buildPickerOverlay() {
    Stack() {
      // 遮罩：点击关闭
      Column()
        .width('100%')
        .height('100%')
        .backgroundColor('rgba(4,6,14,0.60)')
        .onClick(() => { this.pickerShow = false; })

      Column() {
        Text(this.pickerTitle)
          .fontSize(this.sm.getFontSize('subtitle'))
          .fontWeight(FontWeight.Bold)
          .fontColor(this.sm.getColor('text_primary'))
          .margin({ bottom: this.sm.getSpacing('sm') })
        Scroll() {
          Column() {
            ForEach(this.pickerOptions, (opt: PickerOption) => {
              if (opt.header !== '') {
                // 分组头（不可点）
                Text(opt.header)
                  .fontSize(this.sm.getFontSize('caption'))
                  .fontColor(this.sm.getColor('text_tertiary'))
                  .width('100%')
                  .padding({ left: 12, top: 10, bottom: 4 })
                  .alignSelf(ItemAlign.Start)
              } else {
                Row() {
                  Text(opt.label)
                    .fontSize(this.sm.getFontSize('body'))
                    .fontColor(this.sm.getColor('text_primary'))
                  Blank()
                  if (opt.value === this.pickerCurrent) {
                    AppIcon({ name: 'check', iconSize: 16, color: this.sm.getColor('primary') })
                  }
                }
                .width('100%')
                .padding({ left: 12, right: 12, top: 11, bottom: 11 })
                .borderRadius(10)
                .onClick(() => { this.pickOption(opt.value); })
              }
            }, (opt: PickerOption) => opt.header + opt.value + opt.label)
          }
          .width('100%')
        }
        .width('100%')
        .height(360)
        .scrollBar(BarState.Off)
      }
      .width('80%')
      .padding(16)
      .borderRadius(16)
      .backgroundColor(this.sm.getColor('surface'))
      .alignItems(HorizontalAlign.Start)
    }
    .width('100%')
    .height('100%')
  }
}
