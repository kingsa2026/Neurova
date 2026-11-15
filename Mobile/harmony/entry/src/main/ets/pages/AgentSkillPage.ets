/**
 * AgentSkillPage - 智能体技能页
 *
 * 职责：列出绑定到当前 Agent 的技能实例（按 status 筛选），展示等级进度条、
 *       经验值、冷却倒计时，提供卸下按钮
 * 设计：
 *   - AgentSkillViewHelper（导出）：纯视图模型，封装状态颜色映射、状态图标、状态标签、
 *     等级格式化（Lv.N / Lv.MAX）、经验值格式化（N/100）、经验值颜色、冷却倒计时格式化，
 *     无 UI 依赖，可独立单元测试；
 *   - AgentSkillPage（@Component）：Stack [主内容列] + [详情弹窗]
 *     主内容列：TopNavMenu(标题"智能体技能"+返回) + [状态筛选 Tab] + [加载态/空态/列表]；
 *     列表项 GlassCard：name、description、status 徽章、level 进度条、experience、
 *     cooldown 倒计时、usageCount、卸下按钮；
 *   - 颜色统一走 StyleManager（返回 token 名），路由走 Router，
 *     API 暂无智能体技能专用模块 → aboutToAppear 加载 mock 静态数据 + TODO M6 接入真实 API。
 *
 * 注意：区别于 SkillPoolPage（技能池），AgentSkillPage 是绑定到具体 Agent 的技能实例管理。
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassCard、GlassButton
 *   - ../libs/api/ApiFacade：统一 API 门面（仅作为占位，未实际调用）
 *   - ../libs/state/stores/AgentsStore：Agent 状态（currentAgentId 过滤）
 *   - ../routing/Router：统一路由跳转
 *   - ../libs/style/StyleManager：统一样式 token
 *   - ../libs/logger/Logger：统一日志
 *   - ../libs/message/MessageManager：统一消息提示
 *   - ../libs/types：AgentSkill、AgentSkillStatus
 *
 * 用法：
 *   由 Router.push(RouteNames.AGENT_SKILL) 跳转进入；
 *   aboutToAppear 加载当前 Agent 的技能列表（TODO M6 接入真实 API api.agentSkills.*）；
 *   状态筛选 Tab 切换 → 本地 filterStatus 过滤；
 *   卸下按钮 → TODO M6 接入 api.agentSkills.unequip。
 *
 * TDD：AgentSkillViewHelper 各方法按红绿灯垂直切片逐步实现，详见 AgentSkillPage.test.ets
 */

import { TopNavMenu, GlassCard, GlassButton } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { AgentsStore } from '../libs/state/stores/AgentsStore';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { AgentSkill, AgentSkillStatus } from '../libs/types';

/** 日志标签 */
const TAG = 'AgentSkillPage';

/** 等级上限（超过则显示 Lv.MAX） */
const MAX_LEVEL = 10;

/** 经验值上限 */
const MAX_EXPERIENCE = 100;

/** 全部状态（用于筛选 Tab 顺序） */
const ALL_STATUSES: AgentSkillStatus[] = ['equipped', 'active', 'cooldown', 'disabled'];

// ===========================================================================
// AgentSkillViewHelper - 智能体技能视图模型（纯函数，无 UI 依赖，可独立单元测试）
//
// 设计：所有方法为 static，输入 → 输出，无副作用；
//       颜色方法返回 StyleManager 的 token 名（如 'info'），由页面解析为实际颜色值；
//       通过本文件 export，供 ohosTest 直接导入测试
// ===========================================================================

export class AgentSkillViewHelper {
  /**
   * 获取技能状态对应的颜色 token 名
   * 映射：equipped→info, active→success, cooldown→warning, disabled→text_secondary
   * @param status 技能状态
   * @return StyleManager 颜色 token 名
   */
  static getStatusColor(status: AgentSkillStatus): string {
    if (status === 'equipped') return 'info';
    if (status === 'active') return 'success';
    if (status === 'cooldown') return 'warning';
    return 'text_secondary';
  }

  /**
   * 获取技能状态对应的图标 emoji
   * 映射：equipped→📌, active→⚡, cooldown→⏳, disabled→🚫
   * @param status 技能状态
   * @return emoji 字符串
   */
  static getStatusIcon(status: AgentSkillStatus): string {
    if (status === 'equipped') return '📌';
    if (status === 'active') return '⚡';
    if (status === 'cooldown') return '⏳';
    return '🚫';
  }

  /**
   * 获取技能状态对应的中文标签
   * 映射：equipped→已装备, active→激活中, cooldown→冷却中, disabled→已禁用
   * @param status 技能状态
   * @return 中文标签
   */
  static getStatusLabel(status: AgentSkillStatus): string {
    if (status === 'equipped') return '已装备';
    if (status === 'active') return '激活中';
    if (status === 'cooldown') return '冷却中';
    return '已禁用';
  }

  /**
   * 格式化等级为 "Lv.N"
   * 规则：level > 10 → "Lv.MAX"；否则 → "Lv.N"
   * @param level 等级数值（1-10）
   * @return 等级文案
   */
  static formatLevel(level: number): string {
    if (level > MAX_LEVEL) return 'Lv.MAX';
    return `Lv.${level}`;
  }

  /**
   * 格式化经验值
   * 规则：返回 "N/100"
   * @param experience 经验值（0-100）
   * @return 经验值文案
   */
  static formatExperience(experience: number): string {
    return `${experience}/${MAX_EXPERIENCE}`;
  }

  /**
   * 获取经验值对应的颜色 token 名
   * 规则：< 30 → text_secondary；30-70 → info；> 70 → success
   * @param experience 经验值（0-100）
   * @return StyleManager 颜色 token 名
   */
  static getExperienceColor(experience: number): string {
    if (experience < 30) return 'text_secondary';
    if (experience > 70) return 'success';
    return 'info';
  }

  /**
   * 格式化冷却倒计时
   * 规则：undefined → "—"；已过期 → "就绪"；
   *       < 60 秒 → "X 秒后"；< 1 小时 → "X 分钟后"；否则 → "X 小时后"
   * @param endsAt 冷却结束时间 ISO 字符串或 undefined
   * @return 冷却倒计时文案
   */
  static formatCooldown(endsAt?: string): string {
    if (!endsAt) return '—';
    const d = new Date(endsAt);
    if (isNaN(d.getTime())) return '—';
    const diffMs = d.getTime() - Date.now();
    if (diffMs <= 0) return '就绪';
    const diffSec = Math.floor(diffMs / 1000);
    if (diffSec < 60) return `${diffSec} 秒后`;
    const diffMin = Math.floor(diffMs / 60000);
    if (diffMin < 60) return `${diffMin} 分钟后`;
    const diffHour = Math.floor(diffMs / 3600000);
    return `${diffHour} 小时后`;
  }
}

/**
 * Mock 智能体技能数据
 * TODO M6 阶段：替换为 api.agentSkills.list(agentId) 真实 API
 */
const MOCK_SKILLS: AgentSkill[] = [
  {
    id: 'skill_1',
    agentId: 'agent_1',
    name: '代码生成',
    description: '根据需求生成高质量代码',
    level: 8,
    experience: 85,
    status: 'active',
    cooldownEndsAt: undefined,
    lastUsedAt: new Date(Date.now() - 60 * 60 * 1000).toISOString(),
    usageCount: 320,
    equippedAt: '2025-01-01T00:00:00Z',
  },
  {
    id: 'skill_2',
    agentId: 'agent_1',
    name: '文档搜索',
    description: '在知识库中检索相关文档',
    level: 5,
    experience: 50,
    status: 'equipped',
    cooldownEndsAt: undefined,
    lastUsedAt: new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString(),
    usageCount: 158,
    equippedAt: '2025-02-01T00:00:00Z',
  },
  {
    id: 'skill_3',
    agentId: 'agent_1',
    name: '图像识别',
    description: '识别图像内容并生成描述',
    level: 3,
    experience: 20,
    status: 'cooldown',
    cooldownEndsAt: new Date(Date.now() + 5 * 60 * 1000).toISOString(),
    lastUsedAt: new Date(Date.now() - 30 * 1000).toISOString(),
    usageCount: 42,
    equippedAt: '2025-03-01T00:00:00Z',
  },
  {
    id: 'skill_4',
    agentId: 'agent_1',
    name: '语音转写',
    description: '将语音转为文字',
    level: 15,
    experience: 100,
    status: 'disabled',
    cooldownEndsAt: undefined,
    lastUsedAt: new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString(),
    usageCount: 8,
    equippedAt: '2025-04-01T00:00:00Z',
  },
];

@Component
export struct AgentSkillPage {
  // 技能列表
  @State skills: AgentSkill[] = [];
  // 加载态
  @State loading: boolean = true;
  // 当前筛选状态（空串表示全部）
  @State filterStatus: string = '';
  // 当前 Agent ID
  @State agentId: string = '';

  // 统一库单例
  private api = ApiFacade.getInstance();
  private agentsStore = new AgentsStore();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private msg = MessageManager.getInstance();

  aboutToAppear() {
    this.loadSkills();
  }

  /**
   * 加载当前 Agent 的技能列表
   * TODO M6 阶段：替换为真实 API（api.agentSkills.list）
   */
  private async loadSkills(): Promise<void> {
    this.loading = true;
    try {
      this.agentId = this.agentsStore.currentAgentId || '';
      // TODO M6 阶段补充真实 API
      // const res = await this.api.agentSkills.list(this.agentId);
      // if (res.code === 0 && res.data) { this.skills = res.data; }
      this.skills = MOCK_SKILLS.slice();
    } catch (e) {
      this.logger.error(TAG, '加载技能失败', e as Error);
      this.msg.error('加载技能列表失败');
    } finally {
      this.loading = false;
    }
  }

  /**
   * 切换状态筛选
   * 规则：再次点击同一状态取消筛选；点击不同状态切换筛选
   */
  private handleStatusFilter(status: AgentSkillStatus): void {
    this.filterStatus = this.filterStatus === status ? '' : status;
  }

  /**
   * 获取经筛选后的列表
   * 规则：filterStatus 为空 → 全部；否则筛选 status 等于筛选值的技能
   */
  private getFilteredSkills(): AgentSkill[] {
    if (!this.filterStatus) return this.skills;
    return this.skills.filter((s: AgentSkill) => s.status === this.filterStatus);
  }

  /**
   * 计算等级进度（0-1，用于进度条）
   * 规则：level / MAX_LEVEL，封顶 1
   */
  private getLevelProgress(level: number): number {
    if (level <= 0) return 0;
    return Math.min(level / MAX_LEVEL, 1);
  }

  /**
   * 卸下技能
   * TODO M6 阶段：调用真实 API（api.agentSkills.unequip）
   * 当前为本地移除 + TODO 提示
   */
  private async unequipSkill(skill: AgentSkill): Promise<void> {
    try {
      // TODO M6 阶段：const res = await this.api.agentSkills.unequip(skill.id);
      this.skills = this.skills.filter((s: AgentSkill) => s.id !== skill.id);
      this.msg.success(`已卸下技能：${skill.name}`);
    } catch (e) {
      this.logger.error(TAG, '卸下技能失败', e as Error);
      this.msg.error('卸下技能失败');
    }
  }

  build() {
    Stack() {
      Column() {
        // 顶部导航栏：标题"智能体技能" + 返回
        TopNavMenu({
          title: '智能体技能',
          showBack: true,
          showMenu: false,
          onBack: () => { this.router.back(); }
        })

        // 状态筛选 Tab（横向滚动胶囊：全部 + 4 状态）
        this.buildStatusFilter()

        // 主体内容：加载态 / 空态 / 列表 三选一
        if (this.loading) {
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
          List({ space: 12 }) {
            ForEach(this.getFilteredSkills(), (skill: AgentSkill) => {
              ListItem() {
                this.buildSkillCard(skill)
              }
            }, (skill: AgentSkill) => skill.id)
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
    .width('100%')
    .height('100%')
  }

  // ===========================================================================
  // 状态筛选 Tab 构建器
  // ===========================================================================

  /** 状态筛选 Tab：横向滚动胶囊（全部 + 4 状态） */
  @Builder
  buildStatusFilter() {
    Scroll() {
      Row({ space: 8 }) {
        // 全部
        Text('全部')
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.filterStatus === ''
            ? this.sm.getColor('text_on_primary')
            : this.sm.getColor('text_primary'))
          .padding({ left: 12, right: 12, top: 6, bottom: 6 })
          .borderRadius(16)
          .backgroundColor(this.filterStatus === ''
            ? this.sm.getColor('primary')
            : Color.Transparent)
          .onClick(() => { this.filterStatus = ''; })

        // 4 状态
        ForEach(ALL_STATUSES, (status: AgentSkillStatus) => {
          Text(AgentSkillViewHelper.getStatusLabel(status))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.filterStatus === status
              ? this.sm.getColor('text_on_primary')
              : this.sm.getColor('text_primary'))
            .padding({ left: 12, right: 12, top: 6, bottom: 6 })
            .borderRadius(16)
            .backgroundColor(this.filterStatus === status
              ? this.sm.getColor(AgentSkillViewHelper.getStatusColor(status))
              : Color.Transparent)
            .onClick(() => { this.handleStatusFilter(status); })
        }, (status: AgentSkillStatus) => status)
      }
      .padding({
        left: this.sm.getSpacing('md'),
        right: this.sm.getSpacing('md'),
        top: this.sm.getSpacing('sm'),
        bottom: this.sm.getSpacing('sm'),
      })
    }
    .scrollable(ScrollDirection.Horizontal)
    .scrollBar(BarState.Off)
    .width('100%')
  }

  // ===========================================================================
  // 技能卡片构建器
  // ===========================================================================

  /** 单个技能卡片：name + status + level 进度条 + experience + cooldown + usageCount + 卸下按钮 */
  @Builder
  buildSkillCard(skill: AgentSkill) {
    GlassCard() {
      Column() {
        // 顶部行：状态图标 + name + 状态徽章
        Row() {
          Text(AgentSkillViewHelper.getStatusIcon(skill.status))
            .fontSize(14)
            .margin({ right: 6 })

          Column() {
            Text(skill.name)
              .fontSize(this.sm.getFontSize('subtitle'))
              .fontWeight(FontWeight.Bold)
              .fontColor(this.sm.getColor('text_primary'))
              .maxLines(1)
              .textOverflow({ overflow: TextOverflow.Ellipsis })
            if (skill.description) {
              Text(skill.description)
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.sm.getColor('text_secondary'))
                .maxLines(1)
                .textOverflow({ overflow: TextOverflow.Ellipsis })
            }
          }
          .alignItems(HorizontalAlign.Start)
          .layoutWeight(1)
          .margin({ right: this.sm.getSpacing('sm') })

          // 状态徽章
          Text(AgentSkillViewHelper.getStatusLabel(skill.status))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_on_primary'))
            .padding({ left: 8, right: 8, top: 2, bottom: 2 })
            .borderRadius(10)
            .backgroundColor(this.sm.getColor(AgentSkillViewHelper.getStatusColor(skill.status)))
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)

        // 等级行：Lv.N + 进度条
        Row() {
          Text(AgentSkillViewHelper.formatLevel(skill.level))
            .fontSize(this.sm.getFontSize('caption'))
            .fontWeight(FontWeight.Bold)
            .fontColor(this.sm.getColor(AgentSkillViewHelper.getStatusColor(skill.status)))
            .width(60)

          // 等级进度条
          Row() {
            Row()
              .width(`${this.getLevelProgress(skill.level) * 100}%`)
              .height(6)
              .borderRadius(3)
              .backgroundColor(this.sm.getColor(AgentSkillViewHelper.getStatusColor(skill.status)))
          }
          .width('50%')
          .height(6)
          .borderRadius(3)
          .backgroundColor(this.sm.getColor('divider'))
          .alignItems(VerticalAlign.Start)

          Text(`${skill.level}/${MAX_LEVEL}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_disabled'))
            .layoutWeight(1)
            .textAlign(TextAlign.End)
        }
        .width('100%')
        .margin({ top: this.sm.getSpacing('sm') })
        .alignItems(VerticalAlign.Center)

        // 经验值行：N/100 + 进度条
        Row() {
          Text(AgentSkillViewHelper.formatExperience(skill.experience))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor(AgentSkillViewHelper.getExperienceColor(skill.experience)))
            .width(60)

          // 经验进度条
          Row() {
            Row()
              .width(`${skill.experience}%`)
              .height(6)
              .borderRadius(3)
              .backgroundColor(this.sm.getColor(AgentSkillViewHelper.getExperienceColor(skill.experience)))
          }
          .width('50%')
          .height(6)
          .borderRadius(3)
          .backgroundColor(this.sm.getColor('divider'))
          .alignItems(VerticalAlign.Start)

          Text('EXP')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_disabled'))
            .layoutWeight(1)
            .textAlign(TextAlign.End)
        }
        .width('100%')
        .margin({ top: this.sm.getSpacing('xs') })
        .alignItems(VerticalAlign.Center)

        // 底部行：冷却 + 使用次数 + 卸下按钮
        Row() {
          // 冷却倒计时
          Text(`⏱ ${AgentSkillViewHelper.formatCooldown(skill.cooldownEndsAt)}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))

          // 使用次数
          Text(`使用 ${skill.usageCount} 次`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_disabled'))
            .margin({ left: this.sm.getSpacing('sm') })
            .layoutWeight(1)

          // 卸下按钮
          GlassButton({
            text: '卸下',
            type: 'default',
            size: 'small',
            onClick: () => { this.unequipSkill(skill); }
          })
        }
        .width('100%')
        .margin({ top: this.sm.getSpacing('sm') })
        .alignItems(VerticalAlign.Center)
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
    .width('100%')
  }
}
