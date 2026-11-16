/**
 * FirewallPage - 系统防火墙规则页（P3）
 *
 * 职责：展示系统防火墙规则列表，按 action 筛选（allow/deny/ask），
 *       启用/禁用开关
 *
 * 注意：本页为【系统级】防火墙，与 AgentFirewallPage 的 agent 级防火墙区分。
 *       ViewHelper 类名为 SystemFirewallViewHelper，避免与 AgentFirewallPage 的
 *       FirewallViewHelper 类名冲突。
 *
 * 设计：
 *   - SystemFirewallViewHelper（导出）：纯视图模型，封装动作颜色/图标/标签映射
 *     （FirewallAction：allow/deny/ask），无 UI 依赖，可独立单元测试；
 *   - FirewallPage（@Component）：Stack[Column[TopNavMenu(标题"系统防火墙"+返回)]
 *     + [action 筛选 Tab（全部/allow/deny/ask）]
 *     + [加载态/空态/列表]]；
 *     列表项 GlassCard：动作徽章、规则资源（IP/值）、启用开关、创建时间；
 *     颜色统一走 StyleManager（返回 token 名），路由走 Router；
 *   - P1-33 已接线 PageMap；数据走 api.runtime.listFirewallRules /
 *     updateFirewallRule（后端 /v1/firewall/rules，全局规则无 agent 维度）。
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassCard
 *   - ../libs/api/ApiFacade：统一 API 门面（runtime 防火墙 CRUD）
 *   - ../routing/Router：统一路由跳转
 *   - ../libs/style/StyleManager：统一样式 token
 *   - ../libs/logger/Logger：统一日志
 *   - ../libs/message/MessageManager：统一消息提示
 *   - ../libs/types：FirewallRule、FirewallAction
 *
 * 用法：
 *   由 Router.push(RouteNames.FIREWALL) 跳转进入；
 *   aboutToAppear 经 api.runtime.listFirewallRules 拉真实规则；
 *   action 筛选 Tab 切换 → 本地按 action 过滤；
 *   启用/禁用开关 → api.runtime.updateFirewallRule(rule.id, { enabled })。
 *
 * TDD：SystemFirewallViewHelper 各方法按红绿灯垂直切片逐步实现，详见 FirewallPage.test.ets
 */

import { TopNavMenu, GlassCard } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { FirewallRule, FirewallAction } from '../libs/types';

/** 日志标签 */
const TAG = 'FirewallPage';

// ===========================================================================
// SystemFirewallViewHelper - 系统防火墙视图模型（纯函数，无 UI 依赖，可独立单元测试）
//
// 注意：类名使用 SystemFirewallViewHelper，避免与 AgentFirewallPage 中的 FirewallViewHelper
//       类名冲突。两者均封装规则视图逻辑，但作用域不同：
//       - SystemFirewallViewHelper：系统级（/v1/firewall 全局规则）
//       - FirewallViewHelper（AgentFirewallPage）：agent 级（agent 行为权限）
// ===========================================================================

export class SystemFirewallViewHelper {
  /**
   * 获取动作对应的颜色 token 名
   * 映射：allow→success、deny→error、ask→warning
   * @param action 动作类型
   * @return StyleManager 颜色 token 名
   */
  static getActionColor(action: FirewallAction): string {
    if (action === 'allow') return 'success';
    if (action === 'deny') return 'error';
    if (action === 'ask') return 'warning';
    throw new Error(`getActionColor 未实现: ${action}`);
  }

  /**
   * 获取动作对应的图标 emoji
   * 映射：allow→✅、deny→🚫、ask→❓
   * @param action 动作类型
   * @return emoji 字符串
   */
  static getActionIcon(action: FirewallAction): string {
    if (action === 'allow') return '✅';
    if (action === 'deny') return '🚫';
    if (action === 'ask') return '❓';
    throw new Error(`getActionIcon 未实现: ${action}`);
  }

  /**
   * 获取动作对应的中文标签
   * 映射：allow→允许、deny→拒绝、ask→询问
   * @param action 动作类型
   * @return 中文标签
   */
  static getActionLabel(action: FirewallAction): string {
    if (action === 'allow') return '允许';
    if (action === 'deny') return '拒绝';
    if (action === 'ask') return '询问';
    throw new Error(`getActionLabel 未实现: ${action}`);
  }
}

/** 动作筛选 Tab 配置 */
interface ActionFilterOption {
  value: string;
  label: string;
}

/** 动作筛选 Tab 列表 */
const ACTION_FILTERS: ActionFilterOption[] = [
  { value: 'all', label: '全部' },
  { value: 'allow', label: '允许' },
  { value: 'deny', label: '拒绝' },
  { value: 'ask', label: '询问' },
];

@Component
export struct FirewallPage {
  // 规则列表
  @State rules: FirewallRule[] = [];
  // 加载态
  @State loading: boolean = true;
  // 当前激活的动作筛选
  @State activeAction: string = 'all';

  // 统一库单例
  private api = ApiFacade.getInstance();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private msg = MessageManager.getInstance();

  aboutToAppear() {
    this.loadRules();
  }

  /**
   * 加载规则列表（/v1/firewall/rules，全局规则）
   */
  private async loadRules(): Promise<void> {
    this.loading = true;
    try {
      const res = await this.api.runtime.listFirewallRules('');
      if (res.code === 0 && res.data) {
        this.rules = res.data.items;
      } else {
        this.rules = [];
        this.msg.error(res.message || '加载防火墙规则失败');
      }
    } catch (e) {
      this.logger.error(TAG, '加载防火墙规则失败', e as Error);
      this.msg.error('加载防火墙规则失败');
    } finally {
      this.loading = false;
    }
  }

  /** 切换动作筛选 */
  private switchAction(value: string): void {
    this.activeAction = value;
  }

  /** 获取经动作筛选后的列表 */
  private getFilteredRules(): FirewallRule[] {
    if (this.activeAction === 'all') {
      return this.rules;
    }
    return this.rules.filter((r: FirewallRule) => r.action === this.activeAction);
  }

  /**
   * 切换规则启用状态（PUT /v1/firewall/rules/{id} 全量更新，仅翻 enabled）
   */
  private async toggleRule(rule: FirewallRule): Promise<void> {
    try {
      const res = await this.api.runtime.updateFirewallRule(rule.id, { enabled: !rule.enabled });
      if (res.code === 0 && res.data) {
        this.rules = this.rules.map((r: FirewallRule) => {
          if (r.id === rule.id) {
            return res.data as FirewallRule;
          }
          return r;
        });
        this.msg.success(rule.enabled ? '已禁用' : '已启用');
      } else {
        this.msg.error(res.message || '切换规则失败');
      }
    } catch (e) {
      this.logger.error(TAG, '切换规则失败', e as Error);
      this.msg.error('切换规则失败');
    }
  }

  build() {
    Stack() {
      Column() {
        // 顶部导航栏：标题"系统防火墙" + 返回
        TopNavMenu({
          title: '系统防火墙',
          showBack: true,
          showMenu: false,
          onBack: () => { this.router.back(); }
        })

        // 动作筛选 Tab
        Scroll() {
          Row({ space: 8 }) {
            ForEach(ACTION_FILTERS, (opt: ActionFilterOption) => {
              Text(opt.label)
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.activeAction === opt.value
                  ? this.sm.getColor('text_on_primary')
                  : this.sm.getColor('text_secondary'))
                .backgroundColor(this.activeAction === opt.value
                  ? this.sm.getColor('primary')
                  : this.sm.getColor('surface'))
                .padding({ left: 12, right: 12, top: 6, bottom: 6 })
                .borderRadius(16)
                .onClick(() => { this.switchAction(opt.value); })
            }, (opt: ActionFilterOption) => opt.value)
          }
          .padding({ left: this.sm.getSpacing('md'), right: this.sm.getSpacing('md') })
        }
        .scrollable(ScrollDirection.Horizontal)
        .scrollBar(BarState.Off)
        .width('100%')
        .padding({ top: 4, bottom: 4 })

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
        } else if (this.getFilteredRules().length === 0) {
          Column() {
            Text('暂无防火墙规则')
              .fontSize(this.sm.getFontSize('subtitle'))
              .fontColor(this.sm.getColor('text_secondary'))
          }
          .width('100%')
          .layoutWeight(1)
          .justifyContent(FlexAlign.Center)
          .alignItems(HorizontalAlign.Center)
        } else {
          List({ space: 12 }) {
            ForEach(this.getFilteredRules(), (rule: FirewallRule) => {
              ListItem() {
                this.buildRuleCard(rule)
              }
            }, (rule: FirewallRule) => rule.id)
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
  // 规则卡片构建器
  // ===========================================================================

  /** 单条规则卡片：动作徽章 + 资源值 + 启用开关 + 创建时间 */
  @Builder
  buildRuleCard(rule: FirewallRule) {
    GlassCard() {
      Column() {
        // 上部：动作徽章 + 启用开关
        Row() {
          Row() {
            Text(SystemFirewallViewHelper.getActionIcon(rule.action))
              .fontSize(14)
            Text(SystemFirewallViewHelper.getActionLabel(rule.action))
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_on_primary'))
              .margin({ left: 4 })
          }
          .padding({ left: 8, right: 8, top: 2, bottom: 2 })
          .borderRadius(this.sm.getRadius('sm'))
          .backgroundColor(this.sm.getColor(SystemFirewallViewHelper.getActionColor(rule.action)))

          Text(rule.enabled ? '✅ 已启用' : '⏸️ 已禁用')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor(rule.enabled ? 'success' : 'text_secondary'))
            .layoutWeight(1)
            .margin({ left: 8 })
            .textAlign(TextAlign.End)
            .onClick(() => { this.toggleRule(rule); })
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)

        // 规则资源值（IP/路径等）
        Text(rule.resource.length > 0 ? rule.resource : '（未指定资源）')
          .fontSize(this.sm.getFontSize('body'))
          .fontColor(this.sm.getColor('text_primary'))
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .margin({ top: 4 })
          .width('100%')

        // 作用域 + 创建时间
        Row() {
          Text(`作用域: ${rule.scope}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .layoutWeight(1)
          Text(`创建: ${rule.createdAt.length > 0 ? rule.createdAt : '—'}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_disabled'))
        }
        .width('100%')
        .margin({ top: 4 })
        .alignItems(VerticalAlign.Center)
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
  }
}
