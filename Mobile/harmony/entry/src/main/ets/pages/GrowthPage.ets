/**
 * GrowthPage - 成长画像页（growth.py /growth 真实契约版）
 *
 * 数据：GET /v1/growth?agent_id=
 *       （get_agent_growth 投影：motivation_level{level,drives,...}/
 *        personality{traits,values,communication_style,decision_style}/
 *        constitution[ConstitutionRule]/reflection_logs[ReflectionLog]）
 * 契约说明：后端无成长记录写入端点，旧"编辑里程碑"（updateGrowth）为幻影能力，
 *       本版移除；五维度假记录（dimension/level/experience）随旧 /cognition/growths
 *       端点一并退役，展示真实快照：动机驱动、人格画像、行为宪法、最近反思。
 */

import { TopNavMenu, GlassCard, GlassButton } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { AgentsStore } from '../libs/state/stores/AgentsStore';
import { Router, RouteNames } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { GrowthDataDto, ConstitutionRuleDto, ReflectionDto } from '../libs/api/modules/CognitionApi';

/** 日志标签 */
const TAG = 'GrowthPage';

/** 最近反思展示条数 */
const RECENT_REFLECTION_LIMIT = 5;

// ===========================================================================
// GrowthViewHelper - 成长视图模型（纯函数，无 UI 依赖，可独立单元测试）
//
// 设计：所有方法为 static，输入 → 输出，无副作用；
//       通过本文件 export，供 ohosTest 直接导入测试
// ===========================================================================

export class GrowthViewHelper {
  /**
   * 0-1 分数 → 百分比字符串（0.72 → "72%"；越界截断到 [0,1]）
   */
  static formatPercent(value: number): string {
    const clamped = Math.min(Math.max(value, 0), 1);
    return `${Math.round(clamped * 100)}%`;
  }

  /**
   * 驱动力名称 → 中文标签（未知键原样返回，不臆造）
   */
  static driveLabel(name: string): string {
    if (name === 'curiosity') return '好奇';
    if (name === 'autonomy') return '自主';
    if (name === 'competence') return '胜任';
    if (name === 'relatedness') return '联结';
    if (name === 'mastery') return '精熟';
    if (name === 'purpose') return '目标';
    return name;
  }

  /**
   * 风格词汇 → 中文标签（communication_style / decision_style 共用；未知原样）
   */
  static styleLabel(style: string): string {
    if (style === 'balanced') return '均衡';
    if (style === 'analytical') return '分析型';
    if (style === 'direct') return '直接';
    if (style === 'empathetic') return '共情';
    if (style === 'creative') return '创造';
    if (style === 'cautious') return '谨慎';
    if (style === 'decisive') return '果决';
    if (style === 'collaborative') return '协作';
    if (style === 'pragmatic') return '务实';
    return style;
  }

  /**
   * 宪法条目类型 → 中文标签（未知原样）
   */
  static ruleTypeLabel(type: string): string {
    if (type === 'behavior') return '行为';
    if (type === 'value') return '价值';
    if (type === 'boundary') return '边界';
    if (type === 'goal') return '目标';
    if (type === 'identity') return '身份';
    return type;
  }

  /**
   * 反思类型 → 中文标签（与 ReflectionPage 同词汇；此处独立小映射避免页面互相依赖）
   */
  static reflectionTypeLabel(type: string): string {
    if (type === 'performance') return '性能反思';
    if (type === 'error') return '错误反思';
    if (type === 'improvement') return '改进反思';
    if (type === 'pattern') return '模式反思';
    if (type === 'insight') return '洞察反思';
    if (type === 'strategy') return '策略反思';
    if (type === 'general') return '通用反思';
    return type;
  }

  /**
   * 截断内容，超长时截取 maxLen 字符并追加省略号
   */
  static truncateContent(content: string, maxLen?: number): string {
    const limit = maxLen !== undefined ? maxLen : 80;
    if (content.length <= limit) return content;
    return content.substring(0, limit) + '...';
  }

  /**
   * 秒级时间戳 → "YYYY-MM-DD HH:mm"；非正数回退 "未知"
   */
  static formatTimestamp(ts: number): string {
    if (!ts || ts <= 0) return '未知';
    const d = new Date(ts * 1000);
    if (isNaN(d.getTime())) return '未知';
    const yyyy = d.getFullYear();
    const MM = (d.getMonth() + 1).toString().padStart(2, '0');
    const dd = d.getDate().toString().padStart(2, '0');
    const hh = d.getHours().toString().padStart(2, '0');
    const mm = d.getMinutes().toString().padStart(2, '0');
    return `${yyyy}-${MM}-${dd} ${hh}:${mm}`;
  }
}

// ===========================================================================
// GrowthPage - 成长画像页组件
//
// 设计：Stack[Column[TopNavMenu + Scroll[动机卡 + 人格卡 + 宪法卡 + 最近反思]]]；
//       数据流：aboutToAppear → api.cognition.getGrowthData → 分区渲染
// ===========================================================================

@Component
export struct GrowthPage {
  // 成长数据（由 API 加载）
  @State growth: GrowthDataDto | null = null;
  // 加载态
  @State loading: boolean = true;

  // 统一库单例
  private api = ApiFacade.getInstance();
  private agentsStore = new AgentsStore();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private msg = MessageManager.getInstance();

  aboutToAppear() {
    this.loadGrowth();
  }

  /**
   * 加载当前 Agent 的成长数据
   * 流程：取 currentAgentId → 调用 api.cognition.getGrowthData → 写入 growth
   * 异常：记录日志并提示用户；finally 关闭 loading
   */
  private async loadGrowth(): Promise<void> {
    this.loading = true;
    try {
      const agentId = this.agentsStore.currentAgentId || '';
      const res = await this.api.cognition.getGrowthData(agentId);
      if (res.code === 0 && res.data) {
        this.growth = res.data;
      }
    } catch (e) {
      this.logger.error(TAG, '加载成长数据失败', e as Error);
      this.msg.error('加载成长数据失败');
    } finally {
      this.loading = false;
    }
  }

  /** 刷新按钮回调 */
  private handleRefresh(): void {
    this.loadGrowth();
  }

  /** 动机总水平（0-1；无数据回退 0） */
  private motivationLevel(): number {
    if (this.growth === null || this.growth.motivation_level === null) return 0;
    const snap = this.growth.motivation_level as Record<string, Object>;
    const level = snap['level'];
    return typeof level === 'number' ? level : 0;
  }

  /** drives 键集（动机驱动名列表） */
  private driveNames(): string[] {
    if (this.growth === null || this.growth.motivation_level === null) return [];
    const snap = this.growth.motivation_level as Record<string, Object>;
    const drives = snap['drives'] as Record<string, Object>;
    if (!drives) return [];
    return Object.keys(drives);
  }

  /** 指定驱动的 intensity（0-1；缺失回退 0） */
  private driveIntensity(name: string): number {
    if (this.growth === null || this.growth.motivation_level === null) return 0;
    const snap = this.growth.motivation_level as Record<string, Object>;
    const drives = snap['drives'] as Record<string, Object>;
    if (!drives) return 0;
    const state = drives[name] as Record<string, number>;
    if (!state) return 0;
    const intensity = state['intensity'];
    return typeof intensity === 'number' ? intensity : 0;
  }

  /** 特质键集 */
  private traitNames(): string[] {
    if (this.growth === null || this.growth.personality === null) return [];
    const traits = this.growth.personality.traits;
    if (!traits) return [];
    return Object.keys(traits);
  }

  /** 指定特质值（转字符串展示） */
  private traitValue(name: string): string {
    if (this.growth === null || this.growth.personality === null) return '';
    const traits = this.growth.personality.traits;
    if (!traits) return '';
    const v = traits[name];
    if (typeof v === 'number') return GrowthViewHelper.formatPercent(v);
    return `${v}`;
  }

  build() {
    Stack() {
      // ========== 主页面 ==========
      Column() {
        // 顶部导航栏：标题"成长记录" + 返回 + 刷新按钮（右侧插槽）
        TopNavMenu({
          title: '成长记录',
          showBack: true,
          showMenu: false,
          onBack: () => { this.router.back(); }
        }) {
          GlassButton({
            text: '刷新',
            type: 'primary',
            btnSize: 'small',
            onTap: () => { this.handleRefresh(); }
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
        } else if (this.growth === null) {
          // 空态
          Column() {
            Text('暂无成长数据')
              .fontSize(this.sm.getFontSize('subtitle'))
              .fontColor(this.sm.getColor('text_secondary'))
            GlassButton({
              text: '重新加载',
              type: 'primary',
              btnSize: 'medium',
              onTap: () => { this.handleRefresh(); }
            })
              .margin({ top: this.sm.getSpacing('md') })
          }
          .width('100%')
          .layoutWeight(1)
          .justifyContent(FlexAlign.Center)
          .alignItems(HorizontalAlign.Center)
        } else {
          Scroll() {
            Column() {
              // 1. 动机水平卡
              this.buildMotivationCard()

              // 2. 人格画像卡
              this.buildPersonalityCard()

              // 3. 行为宪法卡
              this.buildConstitutionCard()

              // 4. 最近反思卡
              this.buildRecentReflectionCard()
            }
            .width('100%')
            .alignItems(HorizontalAlign.Start)
          }
          .layoutWeight(1)
          .width('100%')
          .scrollBar(BarState.Off)
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

  /** 动机水平卡：总水平进度条 + 各驱动力强度 */
  @Builder
  buildMotivationCard() {
    Column() {
    GlassCard({ title: '动机水平' }) {
      Column() {
        // 总水平
        Row() {
          Text('综合水平')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
          Text(GrowthViewHelper.formatPercent(this.motivationLevel()))
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontWeight(FontWeight.Bold)
            .fontColor(this.sm.getColor('primary'))
            .margin({ left: this.sm.getSpacing('sm') })
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)

        Row() {
          Row()
            .width(`${Math.round(Math.min(Math.max(this.motivationLevel(), 0), 1) * 100)}%`)
            .height(6)
            .borderRadius(3)
            .backgroundColor(this.sm.getColor('primary'))
        }
        .width('100%')
        .height(6)
        .borderRadius(3)
        .backgroundColor(this.sm.getColor('divider'))
        .alignItems(VerticalAlign.Top)
        .margin({ top: 6 })

        // 各驱动力
        ForEach(this.driveNames(), (name: string) => {
          Row() {
            Text(GrowthViewHelper.driveLabel(name))
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_primary'))
              .width(70)

            Row() {
              Row()
                .width(`${Math.round(Math.min(Math.max(this.driveIntensity(name), 0), 1) * 100)}%`)
                .height(5)
                .borderRadius(2.5)
                .backgroundColor(this.sm.getColor('info'))
            }
            .layoutWeight(1)
            .height(5)
            .borderRadius(2.5)
            .backgroundColor(this.sm.getColor('divider'))
            .alignItems(VerticalAlign.Top)
            .margin({ left: 8, right: 8 })

            Text(GrowthViewHelper.formatPercent(this.driveIntensity(name)))
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .width(44)
              .textAlign(TextAlign.End)
          }
          .width('100%')
          .padding({ top: 5, bottom: 5 })
          .alignItems(VerticalAlign.Center)
        }, (name: string) => name)
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
    }
    .width('100%')
    .margin({ bottom: this.sm.getSpacing('md') })
  }

  /** 人格画像卡：沟通/决策风格 + 特质键值 + 价值观徽章 */
  @Builder
  buildPersonalityCard() {
    Column() {
    GlassCard({ title: '人格画像' }) {
      Column() {
        if (this.growth !== null && this.growth.personality !== null) {
          // 风格两联
          Row() {
            Column() {
              Text('沟通风格')
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.sm.getColor('text_secondary'))
              Text(GrowthViewHelper.styleLabel(this.growth.personality.communication_style))
                .fontSize(this.sm.getFontSize('subtitle'))
                .fontWeight(FontWeight.Bold)
                .fontColor(this.sm.getColor('text_primary'))
                .margin({ top: 2 })
            }
            .layoutWeight(1)
            .alignItems(HorizontalAlign.Start)

            Column() {
              Text('决策风格')
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.sm.getColor('text_secondary'))
              Text(GrowthViewHelper.styleLabel(this.growth.personality.decision_style))
                .fontSize(this.sm.getFontSize('subtitle'))
                .fontWeight(FontWeight.Bold)
                .fontColor(this.sm.getColor('text_primary'))
                .margin({ top: 2 })
            }
            .layoutWeight(1)
            .alignItems(HorizontalAlign.Start)
          }
          .width('100%')

          // 特质键值
          ForEach(this.traitNames(), (name: string) => {
            Row() {
              Text(name)
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.sm.getColor('text_primary'))
                .layoutWeight(1)
              Text(this.traitValue(name))
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.sm.getColor('info'))
            }
            .width('100%')
            .padding({ top: 4, bottom: 4 })
            .alignItems(VerticalAlign.Center)
          }, (name: string) => name)

          // 价值观徽章
          if (this.growth.personality.values.length > 0) {
            Text('价值观')
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .margin({ top: this.sm.getSpacing('sm') })
            Flex({ wrap: FlexWrap.Wrap }) {
              ForEach(this.growth.personality.values, (value: string) => {
                Text(value)
                  .fontSize(this.sm.getFontSize('caption'))
                  .fontColor(this.sm.getColor('primary'))
                  .backgroundColor(this.sm.getColor('surface_strong'))
                  .border({ width: 1, color: this.sm.getColor('primary') })
                  .borderRadius(12)
                  .padding({ left: 10, right: 10, top: 3, bottom: 3 })
                  .margin({ right: 6, bottom: 6 })
              }, (value: string) => value)
            }
            .width('100%')
            .margin({ top: 4 })
          }
        } else {
          Text('人格画像未配置')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_disabled'))
        }
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
    }
    .width('100%')
    .margin({ bottom: this.sm.getSpacing('md') })
  }

  /** 行为宪法卡：条目列表（类型徽章 + 内容 + 启用状态） */
  @Builder
  buildConstitutionCard() {
    Column() {
    GlassCard({ title: '行为宪法' }) {
      Column() {
        if (this.growth !== null && this.growth.constitution.length > 0) {
          ForEach(this.growth.constitution, (rule: ConstitutionRuleDto) => {
            Row() {
              Text(GrowthViewHelper.ruleTypeLabel(rule.rule_type))
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.sm.getColor('text_on_primary'))
                .backgroundColor(this.sm.getColor('info'))
                .borderRadius(8)
                .padding({ left: 8, right: 8, top: 2, bottom: 2 })

              Text(GrowthViewHelper.truncateContent(rule.content, 60))
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.sm.getColor('text_primary'))
                .layoutWeight(1)
                .margin({ left: 8 })
                .maxLines(2)
                .textOverflow({ overflow: TextOverflow.Ellipsis })

              Text(rule.enabled ? '生效中' : '已停用')
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(rule.enabled
                  ? this.sm.getColor('success')
                  : this.sm.getColor('text_disabled'))
            }
            .width('100%')
            .padding({ top: 5, bottom: 5 })
            .alignItems(VerticalAlign.Center)
          }, (rule: ConstitutionRuleDto) => rule.rule_id)
        } else {
          Text('暂无宪法条目')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_disabled'))
        }
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
    }
    .width('100%')
    .margin({ bottom: this.sm.getSpacing('md') })
  }

  /** 最近反思卡：reflection_logs 前 N 条（类型 + 摘要 + 时间） */
  @Builder
  buildRecentReflectionCard() {
    Column() {
    GlassCard({ title: '最近反思' }) {
      Column() {
        if (this.growth !== null && this.growth.reflection_logs.length > 0) {
          ForEach(this.growth.reflection_logs.slice(0, RECENT_REFLECTION_LIMIT), (log: ReflectionDto) => {
            Column() {
              Row() {
                Text(GrowthViewHelper.reflectionTypeLabel(log.reflection_type))
                  .fontSize(this.sm.getFontSize('caption'))
                  .fontColor(this.sm.getColor('primary'))
                  .layoutWeight(1)
                Text(GrowthViewHelper.formatTimestamp(log.timestamp))
                  .fontSize(this.sm.getFontSize('caption'))
                  .fontColor(this.sm.getColor('text_disabled'))
              }
              .width('100%')
              .alignItems(VerticalAlign.Center)

              Text(GrowthViewHelper.truncateContent(log.content, 70))
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.sm.getColor('text_secondary'))
                .margin({ top: 2 })
                .width('100%')
                .maxLines(2)
                .textOverflow({ overflow: TextOverflow.Ellipsis })
            }
            .width('100%')
            .padding({ top: 5, bottom: 5 })
            .alignItems(HorizontalAlign.Start)
          }, (log: ReflectionDto) => log.log_id)
        } else {
          Text('暂无反思记录')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_disabled'))
        }
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
    }
    .width('100%')
  }
}
