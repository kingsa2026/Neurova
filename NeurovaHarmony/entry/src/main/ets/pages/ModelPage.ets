/**
 * ModelPage - 模型管理页
 *
 * 职责：展示所有 LLM Provider 及其模型列表，支持切换默认模型、调整生成参数、查看 Provider 状态
 * 设计：
 *   - ModelViewHelper（导出）：纯视图模型，封装 Provider 状态颜色映射、健康状态图标、
 *     模型类型图标、上下文窗口格式化，无 UI 运行时依赖，可独立单元测试；
 *   - ModelPage（@Component）：Column [TopNavMenu(标题+返回+刷新)] + [默认模型卡]
 *     + [生成参数卡（温度/最大 token/流式）] + [Provider 列表（展开显示 ModelItem）]
 *     + [加载态/空态]；
 *     颜色统一走 StyleManager，路由走 Router，API 走 ApiFacade.models，
 *     状态走 @State，日志走 Logger，提示走 MessageManager；
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassCard、GlassButton、GlassPanel
 *   - ../libs/api/ApiFacade：统一 API 门面（models.listProviders/getGenerationParams/
 *     setDefault/updateGenerationParams/listModels/updateProvider）
 *   - ../routing/Router：统一路由跳转 + RouteNames
 *   - ../libs/style/StyleManager：统一样式 token
 *   - ../libs/logger/Logger：统一日志
 *   - ../libs/message/MessageManager：统一消息提示
 *   - ../libs/types：Provider、ModelItem、DefaultLLMConfig、GenerationParams、
 *     ProviderStatus、ProviderHealth、ModelType
 *
 * 用法：
 *   由 Router.push(RouteNames.MODEL) 跳转进入；
 *   aboutToAppear 并行加载 providers + generationParams；
 *   "切换默认模型" 弹出选择器 → api.models.setDefault → 刷新；
 *   "保存参数" 组装 GenerationParams → api.models.updateGenerationParams → 成功提示；
 *   展开 Provider → 加载该 Provider 下的模型列表；
 *   模型项支持"设为默认"与"启用/禁用"（通过 updateProvider 局部更新）
 *
 * TDD：ModelViewHelper 各方法按红绿灯垂直切片逐步实现，详见 ModelPage.test.ets
 */

import { TopNavMenu, GlassCard, GlassButton, GlassPanel } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { Router, RouteNames } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import {
  Provider,
  ModelItem,
  DefaultLLMConfig,
  GenerationParams,
  ProviderStatus,
  ProviderHealth,
  ModelType,
} from '../libs/types';

/** 日志标签 */
const TAG = 'ModelPage';

// ===========================================================================
// ModelViewHelper - 模型视图模型（纯函数，无 UI 依赖，可独立单元测试）
//
// 设计：所有方法为 static，输入 → 输出，无副作用；
//       颜色方法返回 StyleManager 的 token 名（如 'success'），由页面解析为实际颜色值；
//       图标方法返回 emoji 字符串直接渲染；
//       通过本文件 export，供 ohosTest 直接导入测试
// ===========================================================================

export class ModelViewHelper {
  /**
   * 获取 Provider 状态对应的颜色 token 名
   * 映射：available→success，unavailable→text_disabled，
   *       not_configured→warning，not_ready→error，其他→text_disabled
   * @param status Provider 状态
   * @return StyleManager 颜色 token 名
   */
  static getStatusColor(status: ProviderStatus): string {
    if (status === 'available') return 'success';
    if (status === 'unavailable') return 'text_disabled';
    if (status === 'not_configured') return 'warning';
    if (status === 'not_ready') return 'error';
    // 未覆盖的状态抛错，强制 TDD 红灯逐项补齐
    throw new Error(`getStatusColor 未实现: ${status}`);
  }

  /**
   * 获取 Provider 健康状态对应的图标 emoji
   * 映射：healthy→✅，unhealthy→⚠️，unknown→❓，其他→❓
   * @param health 健康状态
   * @return emoji 字符串
   */
  static getHealthIcon(health: ProviderHealth): string {
    if (health === 'healthy') return '✅';
    if (health === 'unhealthy') return '⚠️';
    if (health === 'unknown') return '❓';
    // 未覆盖的健康状态抛错，强制 TDD 红灯逐项补齐
    throw new Error(`getHealthIcon 未实现: ${health}`);
  }

  /**
   * 获取模型类型对应的图标 emoji
   * 映射：text→📝，image→🖼️，audio→🎵，其他→📝
   * @param type 模型类型
   * @return emoji 字符串
   */
  static getModelTypeIcon(type: ModelType): string {
    if (type === 'text') return '📝';
    if (type === 'image') return '🖼️';
    if (type === 'audio') return '🎵';
    // 未覆盖的模型类型抛错，强制 TDD 红灯逐项补齐
    throw new Error(`getModelTypeIcon 未实现: ${type}`);
  }

  /**
   * 格式化上下文窗口大小为人类可读字符串
   * 映射：1024 整数倍 → "{n}K"，1048576 整数倍 → "{n}M"，
   *       0 或 undefined → "无限制"（切片12 补齐），其他 → 抛错
   * @param cw 上下文窗口大小（token 数）
   * @return 人类可读字符串，如 "8K"、"16K"、"1M"、"无限制"
   */
  static formatContextWindow(cw?: number): string {
    // 0 或 undefined 表示无上下文限制
    if (cw === undefined || cw === 0) return '无限制';
    if (cw >= 1048576 && cw % 1048576 === 0) return `${cw / 1048576}M`;
    if (cw >= 1024 && cw % 1024 === 0) return `${cw / 1024}K`;
    // 未覆盖的输入抛错，强制 TDD 红灯逐项补齐
    throw new Error(`formatContextWindow 未实现: ${cw}`);
  }
}

// ===========================================================================
// ModelPage - 模型管理页 @Component
//
// 结构：Stack [主内容列] + [模型选择弹窗（条件渲染）]
//   主内容列：TopNavMenu(标题+返回+刷新) +
//             加载态 / 空态 / Scroll[默认模型卡 + 生成参数卡 + Provider 列表]
//   模型选择弹窗：半透明遮罩 + GlassPanel + 全部 (Provider, ModelItem) 平铺列表
//
// 数据流：
//   aboutToAppear → 并行 listProviders + getGenerationParams
//   切换默认 → 弹窗选择 → setDefault → 刷新
//   保存参数 → 组装 GenerationParams → updateGenerationParams → 成功提示
//   展开 Provider → 直接读取 Provider.models（已在 listProviders 中预加载）
//   启用/禁用模型 → updateProvider(局部 models) → 刷新
// ===========================================================================

@Component
export struct ModelPage {
  // Provider 列表（含嵌套 models，由 API 加载驱动列表渲染）
  @State providers: Provider[] = [];
  // 当前生成参数（null 表示尚未加载）
  @State generationParams: GenerationParams | null = null;
  // 加载态
  @State loading: boolean = true;
  // 当前展开的 Provider id（空串表示全部折叠）
  @State expandedProviderId: string = '';
  // 生成参数表单临时态（编辑中未保存的值）
  @State tempTemperature: number = 0.7;
  @State tempMaxTokens: number = 2048;
  @State tempStreamMode: boolean = true;
  // 保存中态（防止重复提交）
  @State saving: boolean = false;
  // 是否显示默认模型选择弹窗
  @State showDefaultPicker: boolean = false;

  // 统一库单例
  private api = ApiFacade.getInstance();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private msg = MessageManager.getInstance();

  aboutToAppear() {
    this.loadAll();
  }

  /**
   * 并行加载 Provider 列表 + 生成参数
   * 流程：Promise.all 并行拉取 → 写入 state → 同步表单临时态
   * 异常：记录日志并提示用户；finally 关闭 loading
   */
  private async loadAll(): Promise<void> {
    this.loading = true;
    try {
      const [providersRes, paramsRes] = await Promise.all([
        this.api.models.listProviders(),
        this.api.models.getGenerationParams(),
      ]);
      if (providersRes.code === 0 && providersRes.data) {
        this.providers = providersRes.data;
      }
      if (paramsRes.code === 0 && paramsRes.data) {
        this.generationParams = paramsRes.data;
        // 同步表单临时态，避免编辑时回退到旧值
        this.tempTemperature = paramsRes.data.temperature;
        this.tempMaxTokens = paramsRes.data.max_tokens;
        this.tempStreamMode = paramsRes.data.stream_mode;
      }
    } catch (e) {
      this.logger.error(TAG, '加载失败', e as Error);
      this.msg.error('加载模型数据失败');
    } finally {
      this.loading = false;
    }
  }

  /**
   * 查找当前默认模型的展示信息
   * 规则：遍历 providers → models，返回第一个 is_active=true 的模型
   * @return { providerName, modelName }，无匹配时返回 '未设置'
   */
  private getDefaultDisplay(): { providerName: string; modelName: string } {
    for (const p of this.providers) {
      for (const m of p.models) {
        if (m.is_active) {
          return { providerName: p.name, modelName: m.name };
        }
      }
    }
    return { providerName: '未设置', modelName: '未设置' };
  }

  /**
   * 切换默认模型
   * 流程：调用 api.models.setDefault → 成功后关闭弹窗并刷新
   * 异常：记录日志并提示用户
   */
  private async setDefault(providerId: string, modelId: string): Promise<void> {
    try {
      const res = await this.api.models.setDefault({ provider_id: providerId, model_id: modelId });
      if (res.code === 0) {
        this.msg.success('默认模型已切换');
        this.showDefaultPicker = false;
        this.loadAll();
      } else {
        this.msg.error(res.message || '切换失败');
      }
    } catch (e) {
      this.logger.error(TAG, '切换默认失败', e as Error);
      this.msg.error('切换默认模型失败');
    }
  }

  /**
   * 保存生成参数
   * 流程：组装 GenerationParams → 调用 updateGenerationParams → 成功提示
   * 异常：记录日志并提示用户；finally 关闭 saving
   */
  private async saveParams(): Promise<void> {
    this.saving = true;
    try {
      const params: GenerationParams = {
        temperature: this.tempTemperature,
        max_tokens: this.tempMaxTokens,
        stream_mode: this.tempStreamMode,
      };
      const res = await this.api.models.updateGenerationParams(params);
      if (res.code === 0) {
        this.generationParams = params;
        this.msg.success('参数已保存');
      } else {
        this.msg.error(res.message || '保存失败');
      }
    } catch (e) {
      this.logger.error(TAG, '保存参数失败', e as Error);
      this.msg.error('保存参数失败');
    } finally {
      this.saving = false;
    }
  }

  /**
   * 切换 Provider 展开状态
   * 规则：再次点击同一 Provider 折叠；点击不同 Provider 切换展开
   */
  private toggleProvider(providerId: string): void {
    this.expandedProviderId = this.expandedProviderId === providerId ? '' : providerId;
  }

  /**
   * 切换模型启用/禁用
   * 流程：基于当前 Provider.models 生成新数组（反转目标模型 enabled）→
   *       调用 updateProvider 局部更新 → 成功后刷新
   * 异常：记录日志并提示用户
   */
  private async toggleModelEnabled(provider: Provider, model: ModelItem): Promise<void> {
    const updatedModels: ModelItem[] = provider.models.map((m: ModelItem) => {
      if (m.id === model.id) {
        return { ...m, enabled: !m.enabled };
      }
      return m;
    });
    try {
      const res = await this.api.models.updateProvider(provider.id, { models: updatedModels });
      if (res.code === 0) {
        this.msg.success(model.enabled ? '已禁用' : '已启用');
        this.loadAll();
      } else {
        this.msg.error(res.message || '操作失败');
      }
    } catch (e) {
      this.logger.error(TAG, '切换启用失败', e as Error);
      this.msg.error('操作失败');
    }
  }

  build() {
    Stack() {
      Column() {
        // 顶部导航栏：标题"模型管理" + 返回 + 刷新
        TopNavMenu({
          title: '模型管理',
          showBack: true,
          showMenu: false,
          onBack: () => { this.router.back(); }
        }) {
          GlassButton({
            text: '刷新',
            type: 'default',
            size: 'small',
            onClick: () => { this.loadAll(); }
          })
        }

        if (this.loading) {
          // 加载态：居中"加载中..."
          Column() {
            Text('加载中...')
              .fontSize(this.sm.getFontSize('body'))
              .fontColor(this.sm.getColor('text_secondary'))
          }
          .width('100%')
          .layoutWeight(1)
          .justifyContent(FlexAlign.Center)
          .alignItems(HorizontalAlign.Center)
        } else if (this.providers.length === 0) {
          // 空态：居中"暂无 Provider" + 刷新按钮
          Column() {
            Text('暂无 Provider')
              .fontSize(this.sm.getFontSize('subtitle'))
              .fontColor(this.sm.getColor('text_secondary'))
              .margin({ bottom: this.sm.getSpacing('md') })
            GlassButton({
              text: '重新加载',
              type: 'primary',
              size: 'medium',
              onClick: () => { this.loadAll(); }
            })
          }
          .width('100%')
          .layoutWeight(1)
          .justifyContent(FlexAlign.Center)
          .alignItems(HorizontalAlign.Center)
        } else {
          // 主内容：纵向滚动 [默认模型卡 + 生成参数卡 + Provider 列表]
          Scroll() {
            Column() {
              this.buildDefaultCard()
              this.buildGenerationParamsCard()
              this.buildProviderList()
            }
            .width('100%')
            .alignItems(HorizontalAlign.Start)
          }
          .layoutWeight(1)
          .scrollBar(BarState.Off)
          .padding({
            left: this.sm.getSpacing('md'),
            right: this.sm.getSpacing('md'),
            top: this.sm.getSpacing('sm'),
            bottom: this.sm.getSpacing('sm'),
          })
        }
      }
      .width('100%')
      .height('100%')
      .backgroundColor(this.sm.getColor('background'))

      // 默认模型选择弹窗（条件渲染覆盖层）
      if (this.showDefaultPicker) {
        this.buildDefaultPicker()
      }
    }
    .width('100%')
    .height('100%')
  }

  // ===========================================================================
  // 区块1：默认模型卡片
  // ===========================================================================

  @Builder
  buildDefaultCard() {
    const def = this.getDefaultDisplay();
    GlassCard() {
      Column() {
        Text('默认模型')
          .fontSize(this.sm.getFontSize('subtitle'))
          .fontWeight(FontWeight.Bold)
          .fontColor(this.sm.getColor('text_primary'))

        Row() {
          Text('Provider:')
            .fontSize(this.sm.getFontSize('body'))
            .fontColor(this.sm.getColor('text_secondary'))
          Text(def.providerName)
            .fontSize(this.sm.getFontSize('body'))
            .fontWeight(FontWeight.Medium)
            .fontColor(this.sm.getColor('text_primary'))
            .margin({ left: 4 })
        }
        .width('100%')
        .margin({ top: this.sm.getSpacing('sm') })

        Row() {
          Text('模型:')
            .fontSize(this.sm.getFontSize('body'))
            .fontColor(this.sm.getColor('text_secondary'))
          Text(def.modelName)
            .fontSize(this.sm.getFontSize('body'))
            .fontWeight(FontWeight.Medium)
            .fontColor(this.sm.getColor('text_primary'))
            .margin({ left: 4 })
        }
        .width('100%')
        .margin({ top: 4 })

        GlassButton({
          text: '切换默认模型',
          type: 'primary',
          size: 'medium',
          onClick: () => { this.showDefaultPicker = true; }
        })
          .margin({ top: this.sm.getSpacing('md') })
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
    .width('100%')
    .margin({ bottom: this.sm.getSpacing('md') })
  }

  // ===========================================================================
  // 区块2：生成参数卡片
  // ===========================================================================

  @Builder
  buildGenerationParamsCard() {
    GlassCard() {
      Column() {
        Text('生成参数')
          .fontSize(this.sm.getFontSize('subtitle'))
          .fontWeight(FontWeight.Bold)
          .fontColor(this.sm.getColor('text_primary'))

        // 温度 Slider：0-2，步长 0.1
        Row() {
          Text('温度')
            .fontSize(this.sm.getFontSize('body'))
            .fontColor(this.sm.getColor('text_secondary'))
            .layoutWeight(1)
          Text(this.tempTemperature.toFixed(1))
            .fontSize(this.sm.getFontSize('body'))
            .fontColor(this.sm.getColor('text_primary'))
        }
        .width('100%')
        .margin({ top: this.sm.getSpacing('sm') })
        Slider({
          value: this.tempTemperature,
          min: 0,
          max: 2,
          step: 0.1,
        })
          .width('100%')
          .onChange((value: number) => { this.tempTemperature = value; })

        // 最大 token Slider：256-8192，步长 256
        Row() {
          Text('最大 Token')
            .fontSize(this.sm.getFontSize('body'))
            .fontColor(this.sm.getColor('text_secondary'))
            .layoutWeight(1)
          Text(`${this.tempMaxTokens}`)
            .fontSize(this.sm.getFontSize('body'))
            .fontColor(this.sm.getColor('text_primary'))
        }
        .width('100%')
        .margin({ top: this.sm.getSpacing('sm') })
        Slider({
          value: this.tempMaxTokens,
          min: 256,
          max: 8192,
          step: 256,
        })
          .width('100%')
          .onChange((value: number) => { this.tempMaxTokens = value; })

        // 流式输出 Toggle
        Row() {
          Text('流式输出')
            .fontSize(this.sm.getFontSize('body'))
            .fontColor(this.sm.getColor('text_secondary'))
            .layoutWeight(1)
          Toggle({ type: ToggleType.Switch, isOn: this.tempStreamMode })
            .onChange((isOn: boolean) => { this.tempStreamMode = isOn; })
        }
        .width('100%')
        .margin({ top: this.sm.getSpacing('sm') })

        GlassButton({
          text: this.saving ? '保存中...' : '保存参数',
          type: 'primary',
          size: 'medium',
          onClick: () => { this.saveParams(); }
        })
          .margin({ top: this.sm.getSpacing('md') })
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
    .width('100%')
    .margin({ bottom: this.sm.getSpacing('md') })
  }

  // ===========================================================================
  // 区块3：Provider 列表
  // ===========================================================================

  @Builder
  buildProviderList() {
    List({ space: 12 }) {
      ForEach(this.providers, (provider: Provider) => {
        ListItem() {
          this.buildProviderCard(provider)
        }
      }, (provider: Provider) => provider.id)
    }
    .width('100%')
    .scrollBar(BarState.Off)
  }

  /** 单个 Provider 卡片：头部（图标/名称/状态/数量/健康） + 展开后模型列表 */
  @Builder
  buildProviderCard(provider: Provider) {
    GlassCard() {
      Column() {
        // 头部：图标 + 名称/状态/数量 + 健康图标
        Row() {
          Text(provider.icon)
            .fontSize(24)

          Column() {
            Text(provider.name)
              .fontSize(this.sm.getFontSize('subtitle'))
              .fontWeight(FontWeight.Bold)
              .fontColor(this.sm.getColor('text_primary'))
              .maxLines(1)
              .textOverflow({ overflow: TextOverflow.Ellipsis })

            Row() {
              // 状态圆点（颜色由 ModelViewHelper.getStatusColor 决定）
              Row()
                .width(8)
                .height(8)
                .borderRadius(4)
                .backgroundColor(this.sm.getColor(ModelViewHelper.getStatusColor(provider.status)))
              Text(provider.statusLabel || provider.status)
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.sm.getColor('text_secondary'))
                .margin({ left: 4 })
              Text('·')
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.sm.getColor('text_disabled'))
                .margin({ left: 4, right: 4 })
              Text(`${provider.model_count} 模型`)
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.sm.getColor('text_disabled'))
            }
            .margin({ top: 4 })
            .alignItems(VerticalAlign.Center)
          }
          .layoutWeight(1)
          .alignItems(HorizontalAlign.Start)
          .margin({ left: this.sm.getSpacing('sm') })

          // 健康状态图标
          Text(ModelViewHelper.getHealthIcon(provider.health))
            .fontSize(18)
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)
        .onClick(() => { this.toggleProvider(provider.id); })

        // 展开后：模型列表
        if (this.expandedProviderId === provider.id) {
          Column() {
            if (provider.models.length === 0) {
              Text('该 Provider 暂无模型')
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.sm.getColor('text_disabled'))
                .margin({ top: this.sm.getSpacing('sm') })
            } else {
              ForEach(provider.models, (model: ModelItem) => {
                this.buildModelItem(provider, model)
              }, (model: ModelItem) => model.id)
            }
          }
          .width('100%')
          .alignItems(HorizontalAlign.Start)
          .margin({ top: this.sm.getSpacing('sm') })
        }
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
    .width('100%')
  }

  /** 单个 ModelItem 行：类型图标 + 名称/标签 + 上下文窗口 + 启用状态 + 操作按钮 */
  @Builder
  buildModelItem(provider: Provider, model: ModelItem) {
    Column() {
      // 第一行：类型图标 + 名称 + 上下文窗口
      Row() {
        Text(ModelViewHelper.getModelTypeIcon(model.type))
          .fontSize(18)
        Text(model.name)
          .fontSize(this.sm.getFontSize('body'))
          .fontWeight(FontWeight.Medium)
          .fontColor(this.sm.getColor('text_primary'))
          .layoutWeight(1)
          .margin({ left: 6 })
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
        Text(ModelViewHelper.formatContextWindow(model.context_window))
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('text_disabled'))
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)

      // 第二行：标签 + 启用状态
      Row() {
        // 类型标签
        Text(model.type)
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('primary'))
          .padding({ left: 6, right: 6, top: 2, bottom: 2 })
          .borderRadius(this.sm.getRadius('sm'))
          .backgroundColor(this.sm.getColor('surface'))
        // tags
        if (model.tags.length > 0) {
          Text(model.tags.join(', '))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .margin({ left: this.sm.getSpacing('sm') })
            .layoutWeight(1)
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
        }
        // 启用状态
        Text(model.enabled ? '已启用' : '已禁用')
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(model.enabled ? this.sm.getColor('success') : this.sm.getColor('text_disabled'))
      }
      .width('100%')
      .margin({ top: 4 })
      .alignItems(VerticalAlign.Center)

      // 第三行：操作按钮
      Row() {
        GlassButton({
          text: model.is_active ? '当前默认' : '设为默认',
          type: model.is_active ? 'default' : 'primary',
          size: 'small',
          onClick: () => {
            if (!model.is_active) {
              this.setDefault(provider.id, model.id);
            }
          }
        })
        GlassButton({
          text: model.enabled ? '禁用' : '启用',
          type: 'default',
          size: 'small',
          onClick: () => { this.toggleModelEnabled(provider, model); }
        })
          .margin({ left: this.sm.getSpacing('sm') })
      }
      .width('100%')
      .justifyContent(FlexAlign.End)
      .margin({ top: this.sm.getSpacing('sm') })
    }
    .width('100%')
    .alignItems(HorizontalAlign.Start)
    .padding({
      top: this.sm.getSpacing('sm'),
      bottom: this.sm.getSpacing('sm'),
    })
    .border({
      width: { top: 0.5 },
      color: this.sm.getColor('divider'),
    })
  }

  // ===========================================================================
  // 默认模型选择弹窗（Stack 覆盖层）
  // ===========================================================================

  @Builder
  buildDefaultPicker() {
    // 半透明遮罩
    Column() {
      GlassPanel() {
        Column() {
          Text('选择默认模型')
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontWeight(FontWeight.Bold)
            .fontColor(this.sm.getColor('text_primary'))

          // 全部 (Provider, ModelItem) 列表
          Scroll() {
            Column() {
              ForEach(this.providers, (provider: Provider) => {
                Column() {
                  Text(provider.name)
                    .fontSize(this.sm.getFontSize('body'))
                    .fontWeight(FontWeight.Medium)
                    .fontColor(this.sm.getColor('text_primary'))
                    .margin({ top: this.sm.getSpacing('sm'), bottom: 4 })

                  ForEach(provider.models, (model: ModelItem) => {
                    Row() {
                      Text(ModelViewHelper.getModelTypeIcon(model.type))
                        .fontSize(16)
                      Text(model.name)
                        .fontSize(this.sm.getFontSize('body'))
                        .fontColor(this.sm.getColor('text_primary'))
                        .layoutWeight(1)
                        .margin({ left: 6 })
                      if (model.is_active) {
                        Text('当前')
                          .fontSize(this.sm.getFontSize('caption'))
                          .fontColor(this.sm.getColor('success'))
                      }
                    }
                    .width('100%')
                    .padding({ top: 8, bottom: 8 })
                    .onClick(() => {
                      if (!model.is_active) {
                        this.setDefault(provider.id, model.id);
                      }
                    })
                  }, (model: ModelItem) => model.id)
                }
                .width('100%')
                .alignItems(HorizontalAlign.Start)
              }, (provider: Provider) => provider.id)
            }
            .width('100%')
            .alignItems(HorizontalAlign.Start)
          }
          .layoutWeight(1)
          .scrollBar(BarState.Off)

          GlassButton({
            text: '取消',
            type: 'default',
            size: 'medium',
            onClick: () => { this.showDefaultPicker = false; }
          })
            .margin({ top: this.sm.getSpacing('sm') })
        }
        .width('100%')
        .height('90%')
        .padding(this.sm.getSpacing('md'))
        .alignItems(HorizontalAlign.Start)
      }
      .width('90%')
      .height('80%')
    }
    .width('100%')
    .height('100%')
    .justifyContent(FlexAlign.Center)
    .alignItems(HorizontalAlign.Center)
    .backgroundColor(this.sm.getColor('overlay_mask'))
    .onClick(() => { this.showDefaultPicker = false; })
  }
}
