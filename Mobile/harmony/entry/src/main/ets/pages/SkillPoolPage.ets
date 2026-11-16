/**
 * SkillPoolPage - 技能池页（R6 接真实 API）
 *
 * 职责：展示已安装的技能列表（/v1/skills registry 快照），按启用态筛选，启用/禁用
 * 设计：
 *   - SkillPoolViewHelper（导出）：纯视图模型，封装启用态颜色映射、状态图标、状态文案、
 *     使用次数格式化、成功率格式化、描述截断，无 UI 运行时依赖，可独立单元测试；
 *   - SkillPoolPage（@Component）：Column [TopNavMenu(标题"技能池"+返回)] +
 *     [enabled 筛选 Tab（全部/启用/禁用）] + [加载态/空态/列表]；
 *     列表项 GlassCard：name、category 徽章、version、enabled 徽章、usage_count、
 *     success_rate、description；
 *   - 颜色统一走 StyleManager，路由走 Router，已接线 PageMap（P1-33）；
 *     数据源 SkillsApi.list()（R6：替换 mock，契约对齐后端 SkillInfo——enabled 布尔，
 *     无 draft/published/deprecated 三态与 installs/rating 字段）。
 *
 * 契约说明（诚实缺省）：
 *   - 后端 skill.py 域无卸载端点（卸载属市场域 marketplace.uninstall / 技能池
 *     private 库 DELETE，且 registry 快照不携带来源信息无法定位）——本页不再
 *     渲染"卸载"按钮，不提供后端没有的能力。
 *   - 启用/禁用写 PUT /skills/{id}/enable|disable（registry.set_skill_enabled）。
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassCard、GlassButton
 *   - ../libs/api/ApiFacade：统一 API 门面（api.skills.*）
 *   - ../libs/api/modules/SkillsApi：SkillInfoDto 契约
 *   - ../routing/Router：统一路由跳转
 *   - ../libs/style/StyleManager：统一样式 token
 *   - ../libs/logger/Logger：统一日志
 *   - ../libs/message/MessageManager：统一消息提示
 *
 * 用法：
 *   由 Router.push(RouteNames.SKILL_POOL) 跳转进入；
 *   aboutToAppear 经 api.skills.list() 加载技能列表；
 *   enabled 筛选 Tab 切换 → 本地过滤；
 *   启用/禁用 → api.skills.enable/disable → 失败 toast，成功后刷新。
 *
 * TDD：SkillPoolViewHelper 各方法见 ohosTest SkillPoolPage.test.ets
 */

import { TopNavMenu, GlassCard, GlassButton } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { SkillInfoDto } from '../libs/api/modules/SkillsApi';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';

/** 日志标签 */
const TAG = 'SkillPoolPage';

/** 描述截断默认最大长度 */
const DEFAULT_DESC_MAX_LEN = 80;

/** 成功率百分比上限 */
const RATE_PERCENT_MAX = 100;

// ===========================================================================
// SkillPoolViewHelper - 技能池视图模型（纯函数，无 UI 依赖，可独立单元测试）
//
// 设计：所有方法为 static，输入 → 输出，无副作用；
//       颜色方法返回 StyleManager 的 token 名（如 'success'），由页面解析为实际颜色值；
//       通过本文件 export，供 ohosTest 直接导入测试
// ===========================================================================

export class SkillPoolViewHelper {
  /**
   * 获取技能启用态对应的颜色 token 名
   * 映射：enabled→success，disabled→text_disabled
   * @param enabled 技能启用态（后端 SkillInfo.enabled）
   * @return StyleManager 颜色 token 名
   */
  static getStatusColor(enabled: boolean): string {
    return enabled ? 'success' : 'text_disabled';
  }

  /**
   * 获取技能启用态对应的图标 emoji
   * 映射：enabled→✅，disabled→🚫
   * @param enabled 技能启用态
   * @return emoji 字符串
   */
  static getStatusIcon(enabled: boolean): string {
    return enabled ? '✅' : '🚫';
  }

  /**
   * 获取技能启用态对应的中文标签
   * 映射：enabled→已启用，disabled→已禁用
   * @param enabled 技能启用态
   * @return 中文文案
   */
  static getStatusLabel(enabled: boolean): string {
    return enabled ? '已启用' : '已禁用';
  }

  /**
   * 获取启用/禁用操作按钮文案（对当前状态取反的动作）
   * @param enabled 技能启用态
   * @return '禁用' 或 '启用'
   */
  static getToggleActionLabel(enabled: boolean): string {
    return enabled ? '禁用' : '启用';
  }

  /**
   * 格式化使用次数为人类可读字符串
   * 规则：0 → "未使用"；≥1M → "1.0M 次"；≥1K → "1.0K 次"；其他 → "{n} 次"
   * @param usageCount 使用次数（后端 usage_count）
   * @return 人类可读使用数字符串
   */
  static formatUsageCount(usageCount: number): string {
    if (usageCount === 0) return '未使用';
    const M = 1024 * 1024;
    const K = 1024;
    if (usageCount >= M) {
      return `${(usageCount / M).toFixed(1)}M 次`;
    }
    if (usageCount >= K) {
      return `${(usageCount / K).toFixed(1)}K 次`;
    }
    return `${usageCount} 次`;
  }

  /**
   * 格式化成功率（0-1 小数）为百分比字符串
   * 规则：0 → "无统计"；其他 → "成功率 {n}%"
   * @param successRate 成功率（后端 success_rate，0-1）
   * @return 成功率展示字符串
   */
  static formatSuccessRate(successRate: number): string {
    if (successRate === 0) return '无统计';
    const percent = Math.round(successRate * RATE_PERCENT_MAX);
    return `成功率 ${percent}%`;
  }

  /**
   * 截断描述文本，超长时截取 maxLen 字符并追加省略号
   * @param desc 原始描述
   * @param maxLen 最大字符数，默认 80
   * @return 截断后的描述；未超长则原样返回
   */
  static truncateDescription(desc: string, maxLen: number = DEFAULT_DESC_MAX_LEN): string {
    if (desc.length <= maxLen) return desc;
    return desc.substring(0, maxLen) + '...';
  }
}

/** enabled 筛选 Tab 配置 */
interface EnabledFilterOption {
  value: string;     // 'all' / 'enabled' / 'disabled'
  label: string;
}

/** enabled 筛选 Tab 列表（顺序即展示顺序） */
const ENABLED_FILTERS: EnabledFilterOption[] = [
  { value: 'all', label: '全部' },
  { value: 'enabled', label: '启用' },
  { value: 'disabled', label: '禁用' },
];

@Component
export struct SkillPoolPage {
  // 技能列表（api.skills.list() 真实数据）
  @State skills: SkillInfoDto[] = [];
  // 加载态
  @State loading: boolean = true;
  // 当前激活的 enabled 筛选值：'all' / 'enabled' / 'disabled'
  @State activeFilter: string = 'all';
  // 写操作进行中（防重复点击）
  @State togglingId: string = '';

  // 统一库单例
  private api = ApiFacade.getInstance();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private msg = MessageManager.getInstance();

  aboutToAppear() {
    this.loadSkills();
  }

  /**
   * 加载技能列表（GET /v1/skills，registry 快照）
   */
  private async loadSkills(): Promise<void> {
    this.loading = true;
    try {
      const res = await this.api.skills.list();
      if (res.code === 0 && res.data) {
        this.skills = res.data;
      } else {
        this.skills = [];
        this.msg.error(res.message && res.message.length > 0 ? res.message : '加载技能列表失败');
      }
    } catch (e) {
      this.logger.error(TAG, '加载技能失败', e as Error);
      this.msg.error('加载技能列表失败');
      this.skills = [];
    } finally {
      this.loading = false;
    }
  }

  /** 切换 enabled 筛选 Tab */
  private switchFilter(value: string): void {
    this.activeFilter = value;
  }

  /**
   * 获取经 enabled 筛选后的列表
   * 规则：activeFilter === 'all' 返回全量；否则按 enabled 字段过滤
   */
  private getFilteredSkills(): SkillInfoDto[] {
    if (this.activeFilter === 'all') {
      return this.skills;
    }
    const wantEnabled = this.activeFilter === 'enabled';
    return this.skills.filter((s: SkillInfoDto) => s.enabled === wantEnabled);
  }

  /**
   * 切换技能启用/禁用（对当前状态取反）
   * 后端无"失败回滚"问题：失败时 toast 拒因，成功后整体刷新拿 registry 真值
   */
  private async toggleSkill(skill: SkillInfoDto): Promise<void> {
    if (this.togglingId.length > 0) {
      return;
    }
    this.togglingId = skill.skill_id;
    try {
      const res = skill.enabled
        ? await this.api.skills.disable(skill.skill_id)
        : await this.api.skills.enable(skill.skill_id);
      if (res.code === 0) {
        this.msg.success(`${skill.name} ${SkillPoolViewHelper.getToggleActionLabel(skill.enabled)}成功`);
        await this.loadSkills();
      } else {
        this.msg.error(res.message && res.message.length > 0 ? res.message : '操作失败');
      }
    } catch (e) {
      this.logger.error(TAG, '切换技能状态失败', e as Error);
      this.msg.error('切换技能状态失败');
    } finally {
      this.togglingId = '';
    }
  }

  build() {
    Column() {
      // 顶部导航栏：标题"技能池" + 返回
      TopNavMenu({
        title: '技能池',
        showBack: true,
        showMenu: false,
        onBack: () => { this.router.back(); }
      })

      // enabled 筛选 Tab：横向滚动胶囊
      Scroll() {
        Row({ space: 8 }) {
          ForEach(ENABLED_FILTERS, (opt: EnabledFilterOption) => {
            Text(opt.label)
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.activeFilter === opt.value
                ? this.sm.getColor('text_on_primary')
                : this.sm.getColor('text_secondary'))
              .backgroundColor(this.activeFilter === opt.value
                ? this.sm.getColor('primary')
                : this.sm.getColor('surface'))
              .padding({ left: 12, right: 12, top: 6, bottom: 6 })
              .borderRadius(16)
              .onClick(() => { this.switchFilter(opt.value); })
          }, (opt: EnabledFilterOption) => opt.value)
        }
        .padding({ left: this.sm.getSpacing('md'), right: this.sm.getSpacing('md') })
      }
      .scrollable(ScrollDirection.Horizontal)
      .scrollBar(BarState.Off)
      .width('100%')
      .padding({ top: 4, bottom: 4 })

      // 主体内容：加载态 / 空态 / 列表 三选一
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
      } else if (this.getFilteredSkills().length === 0) {
        // 空态：居中"暂无技能"
        Column() {
          Text('暂无技能')
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontColor(this.sm.getColor('text_secondary'))
        }
        .width('100%')
        .layoutWeight(1)
        .justifyContent(FlexAlign.Center)
        .alignItems(HorizontalAlign.Center)
      } else {
        // 技能列表：纵向滚动，卡片间距 12
        List({ space: 12 }) {
          ForEach(this.getFilteredSkills(), (skill: SkillInfoDto) => {
            ListItem() {
              this.buildSkillCard(skill)
            }
          }, (skill: SkillInfoDto) => skill.skill_id)
        }
        .layoutWeight(1)
        .width('100%')
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
  }

  // ===========================================================================
  // 技能卡片构建器
  // ===========================================================================

  /** 单个技能卡片：启用徽章 + 名称 + 分类/版本 + 使用统计 + 描述 + 启用/禁用按钮 */
  @Builder
  buildSkillCard(skill: SkillInfoDto) {
    GlassCard() {
      Column() {
        // 顶部行：状态图标 + 状态徽章 + 名称
        Row() {
          Text(SkillPoolViewHelper.getStatusIcon(skill.enabled))
            .fontSize(20)
          Text(SkillPoolViewHelper.getStatusLabel(skill.enabled))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor(SkillPoolViewHelper.getStatusColor(skill.enabled)))
            .padding({ left: 6, right: 6, top: 2, bottom: 2 })
            .borderRadius(this.sm.getRadius('sm'))
            .backgroundColor(this.sm.getColor('surface'))
            .margin({ left: this.sm.getSpacing('xs') })
          Text(skill.name)
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontWeight(FontWeight.Bold)
            .fontColor(this.sm.getColor('text_primary'))
            .layoutWeight(1)
            .margin({ left: this.sm.getSpacing('sm') })
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)

        // 第二行：分类徽章 + 版本
        Row() {
          Text(skill.category)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_on_primary'))
            .padding({ left: 6, right: 6, top: 2, bottom: 2 })
            .borderRadius(this.sm.getRadius('sm'))
            .backgroundColor(this.sm.getColor('primary'))
          Text(`v${skill.version}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .margin({ left: this.sm.getSpacing('sm') })
        }
        .width('100%')
        .margin({ top: this.sm.getSpacing('xs') })
        .alignItems(VerticalAlign.Center)

        // 描述
        Text(SkillPoolViewHelper.truncateDescription(skill.description))
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('text_secondary'))
          .maxLines(2)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .margin({ top: this.sm.getSpacing('xs') })
          .width('100%')

        // 使用统计：次数 + 成功率
        Row() {
          Text(SkillPoolViewHelper.formatUsageCount(skill.usage_count))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .layoutWeight(1)
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
          Text(SkillPoolViewHelper.formatSuccessRate(skill.success_rate))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('info'))
        }
        .width('100%')
        .margin({ top: this.sm.getSpacing('xs') })
        .alignItems(VerticalAlign.Center)

        // 操作按钮：启用/禁用（右对齐）
        Row() {
          GlassButton({
            text: this.togglingId === skill.skill_id
              ? '处理中'
              : SkillPoolViewHelper.getToggleActionLabel(skill.enabled),
            type: 'default',
            btnSize: 'small',
            onTap: () => { this.toggleSkill(skill); }
          })
        }
        .width('100%')
        .justifyContent(FlexAlign.End)
        .margin({ top: this.sm.getSpacing('md') })
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
  }
}
