/**
 * AgentFormPage - 智能体表单页（创建/编辑共用）
 *
 * 职责：提供智能体创建/编辑表单，含字段校验、载荷组装、保存提交流程
 * 设计：Column [TopNavMenu(动态标题+返回)] + [GlassPanel 可滚动表单]；
 *       通过路由参数 mode('create'|'edit') + agentId? 区分模式；
 *       edit 模式 aboutToAppear 调用 api.agents.get 加载详情回填表单；
 *       提交流程抽取为纯函数 executeAgentSave（便于单元测试），由 handleSubmit 调用；
 *       成功后 emit 'navigation:back' 事件并 router.back()；失败 emit 'form:error' 并提示
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassPanel、GlassInput、GlassButton
 *   - ../libs/api/ApiFacade：统一 API 门面（agents.get/create/update）
 *   - ../libs/state/stores/AgentsStore：Agent 状态（保存成功后刷新列表）
 *   - ../routing/Router：统一路由跳转 + RouteNames
 *   - ../libs/style/StyleManager：统一样式 token
 *   - ../libs/logger/Logger：统一日志
 *   - ../libs/message/MessageManager：统一消息提示
 *   - ../libs/bus/EventBus：统一事件总线（navigation:back / form:error）
 *   - ../libs/types：Agent、AgentConfig、ApiResponse
 *
 * 用法：
 *   Router.push(RouteNames.AGENT_FORM, { mode: 'create' });
 *   Router.push(RouteNames.AGENT_FORM, { mode: 'edit', agentId: 'a1' });
 *
 * 导出（供单元测试）：
 *   - AgentFormData：表单数据结构
 *   - AgentFormValidator：字段校验器（validateName/validateTemperature/validateMaxTokens）
 *   - buildAgentPayload：组装提交载荷（create 不含 id，edit 含 id）
 *   - AgentSaveApi：保存 API 抽象接口（供 Mock 注入）
 *   - executeAgentSave：保存流程纯函数（校验→组装→调用 API→emit 事件）
 */

import { TopNavMenu, GlassPanel, GlassInput, GlassButton } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
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
// 表单数据结构（导出供测试用）
// ===========================================================================

/** 智能体表单数据 */
export interface AgentFormData {
  name: string;
  description: string;
  model: string;
  provider: string;
  systemPrompt: string;
  temperature: number;
  maxTokens: number;
  topP: number;
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

  /** 校验最大 token：256-8192 范围 */
  static validateMaxTokens(n: number): string | null {
    if (n < 256 || n > 8192) {
      return '最大token必须在256到8192之间';
    }
    return null;
  }
}

// ===========================================================================
// buildAgentPayload - 组装提交载荷（导出供测试用）
// 切片 5/6 实现具体逻辑，此处暂为 stub
// ===========================================================================

/** 保存 API 抽象接口（供 executeAgentSave 注入，便于测试 Mock） */
export interface AgentSaveApi {
  create(data: Partial<Agent>): Promise<ApiResponse<Agent>>;
  update(agentId: string, data: Partial<Agent>): Promise<ApiResponse<Agent>>;
}

/**
 * 组装提交载荷
 * @param mode 'create' | 'edit'
 * @param form 表单数据
 * @param agentId edit 模式必填
 * @returns create 模式返回不含 id 的 Partial<Agent>；edit 模式返回含 id 的 Partial<Agent>
 */
export function buildAgentPayload(
  mode: 'create' | 'edit',
  form: AgentFormData,
  agentId?: string,
): Partial<Agent> {
  const config: AgentConfig = {
    systemPrompt: form.systemPrompt || undefined,
    temperature: form.temperature,
    maxTokens: form.maxTokens,
    topP: form.topP,
  };
  const payload: Partial<Agent> = {
    name: form.name,
    description: form.description || undefined,
    model: form.model || undefined,
    provider: form.provider || undefined,
    config,
  };
  if (mode === 'edit' && agentId) {
    payload.id = agentId;
  }
  return payload;
}

// ===========================================================================
// executeAgentSave - 保存流程纯函数（导出供测试用）
// 切片 7/8 实现具体逻辑，此处暂为 stub
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
  api: AgentSaveApi,
  bus: EventBus,
): Promise<boolean> {
  // 1. 前端校验：名称非空
  const nameError = AgentFormValidator.validateName(form.name);
  if (nameError) {
    bus.emit('form:error', { field: 'name', message: nameError });
    return false;
  }

  // 2. 组装载荷
  const payload = buildAgentPayload(mode, form, agentId);

  // 3. 调用 API
  try {
    const res = mode === 'create'
      ? await api.create(payload)
      : await api.update(agentId!, payload);
    if (res.code === 0) {
      // 成功：emit 'navigation:back'
      bus.emit('navigation:back', { success: true, mode });
      return true;
    }
    // 业务失败：emit 'form:error' 携带后端消息
    bus.emit('form:error', { message: res.message });
    return false;
  } catch (e) {
    // 异常：emit 'form:error' 携带兜底消息
    bus.emit('form:error', { message: '保存失败' });
    return false;
  }
}

// ===========================================================================
// AgentFormPage - 页面组件
// ===========================================================================

@Component
export struct AgentFormPage {
  // 表单字段（受控）
  @State name: string = '';
  @State description: string = '';
  @State model: string = '';
  @State provider: string = '';
  @State systemPrompt: string = '';
  @State temperature: number = 0.7;
  @State maxTokens: number = 2048;
  @State topP: number = 0.9;
  // 加载态（edit 模式加载详情 / 提交中）
  @State loading: boolean = false;
  // 路由模式
  @State mode: 'create' | 'edit' = 'create';
  private agentId: string = '';

  // 统一库单例
  private api = ApiFacade.getInstance();
  private agentsStore = new AgentsStore();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private msg = MessageManager.getInstance();
  private bus = EventBus.getInstance();

  /**
   * 页面出现：解析路由参数；edit 模式加载智能体详情；订阅 form:error 事件
   * 路由参数：{ mode: 'create' | 'edit', agentId?: string }
   */
  aboutToAppear() {
    // 解析路由参数
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
    // 订阅表单错误事件（executeAgentSave 校验/提交失败时 emit）
    this.bus.on('form:error', this.onFormError);
    // edit 模式：加载智能体详情回填表单
    if (this.mode === 'edit' && this.agentId) {
      this.loadAgent();
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

  /**
   * 加载智能体详情（edit 模式）
   * 流程：调用 api.agents.get → 回填表单字段
   * 失败：MessageManager.error + router.back()
   */
  private async loadAgent(): Promise<void> {
    this.loading = true;
    try {
      const res = await this.api.agents.get(this.agentId);
      if (res.code === 0 && res.data) {
        const a = res.data;
        this.name = a.name;
        this.description = a.description ?? '';
        this.model = a.model ?? '';
        this.provider = a.provider ?? '';
        this.systemPrompt = a.config?.systemPrompt ?? '';
        this.temperature = a.config?.temperature ?? 0.7;
        this.maxTokens = a.config?.maxTokens ?? 2048;
        this.topP = a.config?.topP ?? 0.9;
      } else {
        this.msg.error(res.message || '加载失败');
        this.router.back();
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
   * 提交保存
   * 流程：组装表单数据 → 调用 executeAgentSave → 成功 router.back()；失败由 form:error 事件处理
   */
  private async handleSubmit(): Promise<void> {
    const form: AgentFormData = {
      name: this.name,
      description: this.description,
      model: this.model,
      provider: this.provider,
      systemPrompt: this.systemPrompt,
      temperature: this.temperature,
      maxTokens: this.maxTokens,
      topP: this.topP,
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

  build() {
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
        GlassPanel({ variant: 'elevated', padding: 16, radius: 12 }) {
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

            // 描述（选填，多行，maxLength 200）
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

            // 模型（选填）
            Text('模型')
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .alignSelf(ItemAlign.Start)
              .margin({ top: this.sm.getSpacing('md') })
            GlassInput({
              placeholder: '如 gpt-4、claude-3',
              value: this.model,
              type: 'text',
              maxLength: 100,
              onChange: (v: string) => { this.model = v; }
            })
              .margin({ top: 4 })

            // Provider（选填）
            Text('Provider')
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .alignSelf(ItemAlign.Start)
              .margin({ top: this.sm.getSpacing('md') })
            GlassInput({
              placeholder: '如 openai、anthropic',
              value: this.provider,
              type: 'text',
              maxLength: 50,
              onChange: (v: string) => { this.provider = v; }
            })
              .margin({ top: 4 })

            // 系统提示词（选填，多行，maxLength 2000）
            Text('系统提示词')
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .alignSelf(ItemAlign.Start)
              .margin({ top: this.sm.getSpacing('md') })
            GlassInput({
              placeholder: '请输入系统提示词（选填）',
              value: this.systemPrompt,
              type: 'text',
              maxLength: 2000,
              onChange: (v: string) => { this.systemPrompt = v; }
            })
              .margin({ top: 4 })

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

            // 最大 token Slider（256-8192，步长 256，默认 2048）
            Row() {
              Text('最大 Token')
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.sm.getColor('text_secondary'))
              Text(this.maxTokens.toString())
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.sm.getColor('primary'))
                .margin({ left: 8 })
            }
            .width('100%')
            .justifyContent(FlexAlign.SpaceBetween)
            .margin({ top: this.sm.getSpacing('md') })
            Slider({
              value: this.maxTokens,
              min: 256,
              max: 8192,
              step: 256,
            })
              .selectedColor(this.sm.getColor('primary'))
              .onChange((v: number) => { this.maxTokens = v; })

            // topP Slider（0-1，步长 0.05，默认 0.9）
            Row() {
              Text('Top P')
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.sm.getColor('text_secondary'))
              Text(this.topP.toFixed(2))
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.sm.getColor('primary'))
                .margin({ left: 8 })
            }
            .width('100%')
            .justifyContent(FlexAlign.SpaceBetween)
            .margin({ top: this.sm.getSpacing('md') })
            Slider({
              value: this.topP,
              min: 0,
              max: 1,
              step: 0.05,
            })
              .selectedColor(this.sm.getColor('primary'))
              .onChange((v: number) => { this.topP = v; })

            // 保存按钮（primary, block）
            GlassButton({
              text: this.loading ? '保存中...' : '保存',
              type: 'primary',
              block: true,
              disabled: this.loading,
              onClick: () => { this.handleSubmit(); }
            })
              .margin({ top: this.sm.getSpacing('lg') })

            // 取消按钮（default, block）
            GlassButton({
              text: '取消',
              type: 'default',
              block: true,
              disabled: this.loading,
              onClick: () => { this.handleCancel(); }
            })
              .margin({ top: this.sm.getSpacing('sm') })
          }
          .width('100%')
          .alignItems(HorizontalAlign.Start)
        }
        .width('100%')
      }
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
    .backgroundColor(this.sm.getColor('background'))
  }
}
