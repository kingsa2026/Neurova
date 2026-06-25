/**
 * AgentPersonalityPage - 个性配置页
 *
 * 职责：展示当前 Agent 的 5 维度个性配置，支持编辑、保存、重置
 * 设计：
 *   - AgentPersonalityViewHelper（导出）：纯视图模型，封装维度图标、中文标签、维度颜色 token、
 *     百分比格式化、脏数据比较、维度描述文案生成（5 维度 × 3 档 = 15 种组合），
 *     无 UI 运行时依赖，可独立单元测试；
 *   - AgentPersonalityPage（@Component）：Stack[Column[TopNavMenu(标题"个性"+返回+重置)]
 *     + [加载态/空态/内容] + [底部保存按钮] + [重置确认 AlertDialog]]；
 *     内容区 5 张维度 GlassCard，每张含维度名 + 图标 + 当前值 slider（0-1）+ 描述文案；
 *     保存按钮在无变更时 disabled；重置走 AlertDialog 二次确认；
 *     编辑模式：所有 slider 可调，变更后整体重新赋值 @State（满足 ArkUI 浅观察约束）；
 *   - 颜色统一走 StyleManager（返回 token 名），路由走 Router，API 走 ApiFacade.personality，
 *     状态走 AgentsStore
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassCard、GlassButton
 *   - ../libs/api/ApiFacade：统一 API 门面（personality.getPersonality/updatePersonality/resetPersonality）
 *   - ../libs/state/stores/AgentsStore：Agent 状态（currentAgentId）
 *   - ../routing/Router：统一路由跳转 + RouteNames
 *   - ../libs/style/StyleManager：统一样式 token
 *   - ../libs/logger/Logger：统一日志
 *   - ../libs/message/MessageManager：统一消息提示
 *   - ../libs/types：Personality
 *
 * 用法：
 *   由 Router.push 跳转进入；
 *   aboutToAppear 调用 api.personality.getPersonality → 写入 current 与 original 快照；
 *   拖动 slider → 整体重新赋值 current（保持 @State 响应）；
 *   保存按钮 → 检查 isDirty → 调用 api.personality.updatePersonality → 同步 original；
 *   重置按钮 → AlertDialog 二次确认 → 调用 api.personality.resetPersonality → 刷新 current/original
 *
 * TDD：AgentPersonalityViewHelper 各方法按红绿灯垂直切片逐步实现，
 *      详见 AgentPersonalityPage.test.ets
 */

import { TopNavMenu, GlassCard, GlassButton } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { AgentsStore } from '../libs/state/stores/AgentsStore';
import { Router, RouteNames } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { Personality } from '../libs/types';

/** 日志标签 */
const TAG = 'AgentPersonalityPage';

/** Personality 5 维度联合类型别名（简化方法签名） */
type PersonalityDimension =
  | 'openness'
  | 'conscientiousness'
  | 'extraversion'
  | 'agreeableness'
  | 'neuroticism';

/** 全部 5 维度（用于渲染顺序） */
const ALL_DIMENSIONS: PersonalityDimension[] = [
  'openness',
  'conscientiousness',
  'extraversion',
  'agreeableness',
  'neuroticism',
];

/** 描述文案低/中/高阈值（与 §18 Personality 5 维度档位对齐） */
const LEVEL_LOW_MAX = 0.33;
const LEVEL_HIGH_MIN = 0.67;

// ===========================================================================
// AgentPersonalityViewHelper - 个性配置视图模型（纯函数，无 UI 依赖，可独立单元测试）
//
// 设计：所有方法为 static，输入 → 输出，无副作用；
//       颜色方法返回 StyleManager 的 token 名（如 'info'），由页面解析为实际颜色值；
//       buildDescription 覆盖 5 维度 × 3 档共 15 种组合，返回有意义中文文案；
//       通过本文件 export，供 ohosTest 直接导入测试
// ===========================================================================

export class AgentPersonalityViewHelper {
  /**
   * 获取维度对应的 emoji 图标
   * 映射：openness→🎨, conscientiousness→📋, extraversion→🎉,
   *       agreeableness→🤝, neuroticism→🌪️
   * @param dimension 个性维度
   * @return emoji 字符串
   */
  static getDimensionIcon(dimension: PersonalityDimension): string {
    if (dimension === 'openness') return '🎨';
    if (dimension === 'conscientiousness') return '📋';
    if (dimension === 'extraversion') return '🎉';
    if (dimension === 'agreeableness') return '🤝';
    return '🌪️'; // neuroticism
  }

  /**
   * 获取维度对应的中文标签
   * 映射：openness→开放性, conscientiousness→尽责性, extraversion→外向性,
   *       agreeableness→宜人性, neuroticism→神经质
   * @param dimension 个性维度
   * @return 中文标签
   */
  static getDimensionLabel(dimension: PersonalityDimension): string {
    if (dimension === 'openness') return '开放性';
    if (dimension === 'conscientiousness') return '尽责性';
    if (dimension === 'extraversion') return '外向性';
    if (dimension === 'agreeableness') return '宜人性';
    return '神经质'; // neuroticism
  }

  /**
   * 获取维度对应的颜色 token 名
   * 映射：openness→info, conscientiousness→primary, extraversion→warning,
   *       agreeableness→success, neuroticism→error
   * @param dimension 个性维度
   * @return StyleManager 颜色 token 名
   */
  static getDimensionColor(dimension: PersonalityDimension): string {
    if (dimension === 'openness') return 'info';
    if (dimension === 'conscientiousness') return 'primary';
    if (dimension === 'extraversion') return 'warning';
    if (dimension === 'agreeableness') return 'success';
    return 'error'; // neuroticism
  }

  /**
   * 格式化 0-1 维度值为百分比字符串
   * @param value 维度值 0-1
   * @return 百分比字符串，如 0.5 → "50%"
   */
  static formatPercent(value: number): string {
    return `${Math.round(value * 100)}%`;
  }

  /**
   * 判断当前 Personality 是否相对原始 Personality 有变更
   * 任一维度不同返回 true；全部相同返回 false
   * @param current 当前 Personality
   * @param original 原始 Personality
   * @return 是否有变更
   */
  static isDirty(current: Personality, original: Personality): boolean {
    if (current.openness !== original.openness) return true;
    if (current.conscientiousness !== original.conscientiousness) return true;
    if (current.extraversion !== original.extraversion) return true;
    if (current.agreeableness !== original.agreeableness) return true;
    if (current.neuroticism !== original.neuroticism) return true;
    return false;
  }

  /**
   * 根据维度与值生成中文描述文案
   * 档位划分：0-0.33 低 / 0.34-0.66 中 / 0.67-1 高
   * 覆盖 5 维度 × 3 档 = 15 种组合
   * @param dimension 个性维度
   * @param value 维度值 0-1
   * @return 中文描述文案
   */
  static buildDescription(dimension: PersonalityDimension, value: number): string {
    // 档位判定：先低，再高，剩下为中（同时覆盖 0.33/0.34/0.67 三个边界）
    const level: 'low' | 'mid' | 'high' =
      value <= LEVEL_LOW_MAX ? 'low' : (value >= LEVEL_HIGH_MIN ? 'high' : 'mid');

    if (dimension === 'openness') {
      if (level === 'low') return '开放性低：偏向传统与保守';
      if (level === 'high') return '开放性高：富有想象力与创新精神';
      return '开放性中：在传统与创新间平衡';
    }
    if (dimension === 'conscientiousness') {
      if (level === 'low') return '尽责性低：灵活随性，不喜约束';
      if (level === 'high') return '尽责性高：自律严谨，目标明确';
      return '尽责性中：在自律与灵活间平衡';
    }
    if (dimension === 'extraversion') {
      if (level === 'low') return '外向性低：偏内向，喜静独处';
      if (level === 'high') return '外向性高：热情开朗，善于社交';
      return '外向性中：内外向平衡';
    }
    if (dimension === 'agreeableness') {
      if (level === 'low') return '宜人性低：批判性强，坚持立场';
      if (level === 'high') return '宜人性高：友善合作，乐于助人';
      return '宜人性中：在合作与坚持间平衡';
    }
    // neuroticism
    if (level === 'low') return '神经质低：情绪稳定，从容镇定';
    if (level === 'high') return '神经质高：情绪敏感，易感压力';
    return '神经质中：情绪波动适中';
  }
}

// ===========================================================================
// AgentPersonalityPage - 个性配置页组件
//
// 设计：Stack[Column[TopNavMenu + 加载态/空态/内容(5 维度卡片+保存按钮)]]；
//       数据流：aboutToAppear → api.personality.getPersonality → 写入 current + original；
//       slider 拖动 → 整体重新赋值 current（满足 @State 浅观察的响应约束）；
//       保存按钮 → 检查 isDirty → api.personality.updatePersonality → 同步 original；
//       重置按钮 → AlertDialog 二次确认 → api.personality.resetPersonality → 刷新
// ===========================================================================

@Component
export struct AgentPersonalityPage {
  // 当前编辑中的 Personality（驱动 5 维度卡片渲染）
  @State current: Personality | null = null;
  // 原始快照（用于 isDirty 比较与保存后同步）
  @State original: Personality | null = null;
  // 加载态
  @State loading: boolean = true;
  // 保存中态（防止重复点击）
  @State saving: boolean = false;
  // 重置中态（防止重复点击）
  @State resetting: boolean = false;

  // 统一库单例
  private api = ApiFacade.getInstance();
  private agentsStore = new AgentsStore();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private msg = MessageManager.getInstance();

  aboutToAppear() {
    this.loadPersonality();
  }

  /**
   * 加载当前 Agent 的个性配置
   * 流程：取 currentAgentId → api.personality.getPersonality → 写入 current + original
   * 异常：记录日志并提示用户；finally 关闭 loading
   */
  private async loadPersonality(): Promise<void> {
    this.loading = true;
    try {
      const agentId = this.agentsStore.currentAgentId || '';
      if (!agentId) {
        this.current = null;
        this.original = null;
        return;
      }
      const res = await this.api.personality.getPersonality(agentId);
      if (res.code === 0 && res.data) {
        // 整体赋值（深拷贝以隔离 current 与 original）
        this.current = this.clonePersonality(res.data);
        this.original = this.clonePersonality(res.data);
      } else {
        this.current = null;
        this.original = null;
      }
    } catch (e) {
      this.logger.error(TAG, '加载个性配置失败', e as Error);
      this.msg.error('加载个性配置失败');
    } finally {
      this.loading = false;
    }
  }

  /**
   * 深拷贝 Personality（隔离 current 与 original，避免引用共享导致 isDirty 永真/永假）
   */
  private clonePersonality(p: Personality): Personality {
    return {
      agentId: p.agentId,
      openness: p.openness,
      conscientiousness: p.conscientiousness,
      extraversion: p.extraversion,
      agreeableness: p.agreeableness,
      neuroticism: p.neuroticism,
      description: p.description,
      updatedAt: p.updatedAt,
    };
  }

  /**
   * 更新指定维度值（slider 拖动回调）
   * 实现：整体重新赋值 current，满足 @State 浅观察的响应约束
   * @param dimension 维度名
   * @param value 新值（0-1）
   */
  private updateDimension(dimension: PersonalityDimension, value: number): void {
    if (this.current === null) return;
    // 整体重新赋值（嵌套属性变更必须整体重新赋值）
    const next: Personality = {
      agentId: this.current.agentId,
      openness: this.current.openness,
      conscientiousness: this.current.conscientiousness,
      extraversion: this.current.extraversion,
      agreeableness: this.current.agreeableness,
      neuroticism: this.current.neuroticism,
      description: this.current.description,
      updatedAt: this.current.updatedAt,
    };
    if (dimension === 'openness') next.openness = value;
    else if (dimension === 'conscientiousness') next.conscientiousness = value;
    else if (dimension === 'extraversion') next.extraversion = value;
    else if (dimension === 'agreeableness') next.agreeableness = value;
    else next.neuroticism = value;
    this.current = next;
  }

  /**
   * 保存变更到后端
   * 流程：检查 isDirty → 构造变更 payload → api.personality.updatePersonality → 同步 original
   * 异常：记录日志并提示用户
   * 防抖：saving 状态防止重复提交
   */
  private async saveChanges(): Promise<void> {
    if (this.saving) return;
    if (this.current === null || this.original === null) return;
    if (!AgentPersonalityViewHelper.isDirty(this.current, this.original)) {
      this.msg.info('无变更');
      return;
    }
    this.saving = true;
    try {
      const payload: Partial<Personality> = {
        openness: this.current.openness,
        conscientiousness: this.current.conscientiousness,
        extraversion: this.current.extraversion,
        agreeableness: this.current.agreeableness,
        neuroticism: this.current.neuroticism,
      };
      const res = await this.api.personality.updatePersonality(this.current.agentId, payload);
      if (res.code === 0 && res.data) {
        // 同步 original 为最新值
        this.original = this.clonePersonality(res.data);
        this.current = this.clonePersonality(res.data);
        this.msg.success('保存成功');
      } else {
        this.msg.error(res.message || '保存失败');
      }
    } catch (e) {
      this.logger.error(TAG, '保存个性配置失败', e as Error);
      this.msg.error('保存个性配置失败');
    } finally {
      this.saving = false;
    }
  }

  /**
   * 重置确认（AlertDialog 二次确认）
   * 重置会清除所有维度变更并恢复默认值，不可撤销
   */
  private confirmReset(): void {
    AlertDialog.show({
      title: '确认重置',
      message: '确定要将所有个性维度重置为默认值吗？此操作不可撤销。',
      autoCancel: true,
      alignment: DialogAlignment.Center,
      primaryButton: {
        value: '取消',
        action: () => {}
      },
      secondaryButton: {
        value: '重置',
        fontColor: this.sm.getColor('error'),
        action: () => { this.resetPersonality(); }
      }
    });
  }

  /**
   * 执行重置
   * 流程：调用 api.personality.resetPersonality → 用响应数据刷新 current + original
   * 异常：记录日志并提示用户
   * 防抖：resetting 状态防止重复提交
   */
  private async resetPersonality(): Promise<void> {
    if (this.resetting) return;
    if (this.current === null) return;
    this.resetting = true;
    try {
      const res = await this.api.personality.resetPersonality(this.current.agentId);
      if (res.code === 0 && res.data) {
        this.current = this.clonePersonality(res.data);
        this.original = this.clonePersonality(res.data);
        this.msg.success('已重置');
      } else {
        this.msg.error(res.message || '重置失败');
      }
    } catch (e) {
      this.logger.error(TAG, '重置个性配置失败', e as Error);
      this.msg.error('重置个性配置失败');
    } finally {
      this.resetting = false;
    }
  }

  build() {
    Stack() {
      Column() {
        // 顶部导航栏：标题"个性" + 返回 + 重置按钮（右侧插槽）
        TopNavMenu({
          title: '个性',
          showBack: true,
          showMenu: false,
          onBack: () => { this.router.back(); }
        }) {
          GlassButton({
            text: '重置',
            type: 'danger',
            size: 'small',
            disabled: this.loading || this.current === null || this.resetting,
            onClick: () => { this.confirmReset(); }
          })
        }

        if (this.loading) {
          // 加载态
          Column() {
            Text('加载中...')
              .fontSize(this.sm.getFontSize('body'))
              .fontColor(this.sm.getColor('text_secondary'))
          }
          .width('100%')
          .layoutWeight(1)
          .justifyContent(FlexAlign.Center)
          .alignItems(HorizontalAlign.Center)
        } else if (this.current === null) {
          // 空态
          Column() {
            Text('暂无个性配置')
              .fontSize(this.sm.getFontSize('subtitle'))
              .fontColor(this.sm.getColor('text_secondary'))
            GlassButton({
              text: '重新加载',
              type: 'primary',
              size: 'medium',
              onClick: () => { this.loadPersonality(); }
            })
              .margin({ top: this.sm.getSpacing('md') })
          }
          .width('100%')
          .layoutWeight(1)
          .justifyContent(FlexAlign.Center)
          .alignItems(HorizontalAlign.Center)
        } else {
          // 内容滚动区：5 维度卡片 + 保存按钮
          Scroll() {
            Column() {
              // 5 维度 GlassCard
              ForEach(ALL_DIMENSIONS, (dim: PersonalityDimension) => {
                this.buildDimensionCard(dim)
              }, (dim: PersonalityDimension) => dim)

              // 保存按钮（无变更时 disabled）
              GlassButton({
                text: this.saving ? '保存中...' : '保存',
                type: 'primary',
                size: 'large',
                block: true,
                disabled: this.saving
                  || !AgentPersonalityViewHelper.isDirty(this.current!, this.original!),
                onClick: () => { this.saveChanges(); }
              })
                .width('100%')
                .margin({
                  top: this.sm.getSpacing('md'),
                  bottom: this.sm.getSpacing('lg'),
                })
            }
            .width('100%')
            .padding({
              left: this.sm.getSpacing('md'),
              right: this.sm.getSpacing('md'),
              top: this.sm.getSpacing('sm'),
              bottom: this.sm.getSpacing('sm'),
            })
            .alignItems(HorizontalAlign.Start)
          }
          .layoutWeight(1)
          .width('100%')
          .scrollBar(BarState.Off)
          .align(Alignment.TopStart)
        }
      }
      .width('100%')
      .height('100%')
      .backgroundColor(this.sm.getColor('background'))
    }
    .width('100%')
    .height('100%')
  }

  // ===========================================================================
  // 区块构建器
  // ===========================================================================

  /** 单维度卡片：图标+标签+当前值百分比+slider+描述文案 */
  @Builder
  buildDimensionCard(dim: PersonalityDimension) {
    GlassCard() {
      Column() {
        // 行1：图标 + 维度名 + 当前百分比
        Row() {
          Text(`${AgentPersonalityViewHelper.getDimensionIcon(dim)} ${AgentPersonalityViewHelper.getDimensionLabel(dim)}`)
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontWeight(FontWeight.Bold)
            .fontColor(this.sm.getColor('text_primary'))
            .layoutWeight(1)
          Text(AgentPersonalityViewHelper.formatPercent(this.getDimensionValue(dim)))
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontWeight(FontWeight.Bold)
            .fontColor(this.sm.getColor(AgentPersonalityViewHelper.getDimensionColor(dim)))
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)

        // 行2：slider（0-1，步长 0.01）
        Slider({
          value: this.getDimensionValue(dim),
          min: 0,
          max: 1,
          step: 0.01,
        })
          .width('100%')
          .margin({ top: this.sm.getSpacing('sm') })
          .selectedColor(this.sm.getColor(AgentPersonalityViewHelper.getDimensionColor(dim)))
          .onChange((v: number) => {
            this.updateDimension(dim, v);
          })

        // 行3：维度描述文案（根据档位动态生成）
        Text(AgentPersonalityViewHelper.buildDescription(dim, this.getDimensionValue(dim)))
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('text_secondary'))
          .width('100%')
          .margin({ top: this.sm.getSpacing('xs') })
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
    .width('100%')
    .margin({ bottom: this.sm.getSpacing('sm') })
  }

  /**
   * 从 current 中安全读取指定维度值
   * current 为 null 时返回 0（理论上 buildDimensionCard 调用时 current 已校验非空，
   * 此处仅作防御性兜底）
   */
  private getDimensionValue(dim: PersonalityDimension): number {
    if (this.current === null) return 0;
    if (dim === 'openness') return this.current.openness;
    if (dim === 'conscientiousness') return this.current.conscientiousness;
    if (dim === 'extraversion') return this.current.extraversion;
    if (dim === 'agreeableness') return this.current.agreeableness;
    return this.current.neuroticism;
  }
}
