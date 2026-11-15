/**
 * FirewallPage - 系统防火墙规则页（P3）
 *
 * 职责：展示系统防火墙规则列表，按 action 筛选（allow/deny/log/rate_limit），
 *       优先级排序，启用/禁用开关，命中次数显示
 *
 * 注意：本页为【系统级】防火墙，与 AgentFirewallPage 的 agent 级防火墙区分。
 *       ViewHelper 类名为 SystemFirewallViewHelper，避免与 AgentFirewallPage 的
 *       FirewallViewHelper 类名冲突。
 *
 * 设计：
 *   - SystemFirewallViewHelper（导出）：纯视图模型，封装动作颜色/图标/标签映射、
 *     协议标签、命中次数格式化（0→未命中/1-999→原值/≥1000→999+次）、
 *     优先级格式化（'优先级 N'），无 UI 依赖，可独立单元测试；
 *   - FirewallPage（@Component）：Stack[Column[TopNavMenu(标题"系统防火墙"+返回)]
 *     + [action 筛选 Tab（全部/allow/deny/log/rate_limit）]
 *     + [加载态/空态/列表]]；
 *     列表项 GlassCard：动作徽章、规则名、协议/源IP/端口、优先级、命中次数、启用开关；
 *     颜色统一走 StyleManager（返回 token 名），路由走 Router，
 *     API 暂无系统防火墙专用模块 → aboutToAppear 加载 mock 静态数据 + TODO M6 标注。
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassCard、GlassButton、GlassInput、GlassPanel
 *   - ../libs/api/ApiFacade：统一 API 门面（仅占位，未实际调用）
 *   - ../routing/Router：统一路由跳转
 *   - ../libs/style/StyleManager：统一样式 token
 *   - ../libs/logger/Logger：统一日志
 *   - ../libs/message/MessageManager：统一消息提示
 *   - ../libs/types：SystemFirewallRule、SystemFirewallAction
 *
 * 用法：
 *   由 Router.push(RouteNames.FIREWALL) 跳转进入；
 *   aboutToAppear 加载 mock 规则列表（TODO M6 接入真实 API）；
 *   action 筛选 Tab 切换 → 本地按 action 过滤；
 *   启用/禁用开关 → TODO M6 接入 api.systemFirewall.toggle
 *
 * TDD：SystemFirewallViewHelper 各方法按红绿灯垂直切片逐步实现，详见 FirewallPage.test.ets
 */

import { TopNavMenu, GlassCard, GlassButton, GlassInput, GlassPanel } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { SystemFirewallRule, SystemFirewallAction } from '../libs/types';

/** 日志标签 */
const TAG = 'FirewallPage';

/** 命中次数阈值：≥1000 显示 '999+次' */
const HIT_COUNT_THRESHOLD = 1000;

// ===========================================================================
// SystemFirewallViewHelper - 系统防火墙视图模型（纯函数，无 UI 依赖，可独立单元测试）
//
// 注意：类名使用 SystemFirewallViewHelper，避免与 AgentFirewallPage 中的 FirewallViewHelper
//       类名冲突。两者均封装规则视图逻辑，但作用域不同：
//       - SystemFirewallViewHelper：系统级（IP/端口/协议）
//       - FirewallViewHelper（AgentFirewallPage）：agent 级（agent 行为权限）
// ===========================================================================

export class SystemFirewallViewHelper {
  /**
   * 获取动作对应的颜色 token 名
   * 映射：allow→success、deny→error、log→info、rate_limit→warning
   * @param action 动作类型
   * @return StyleManager 颜色 token 名
   */
  static getActionColor(action: SystemFirewallAction): string {
    if (action === 'allow') return 'success';
    if (action === 'deny') return 'error';
    if (action === 'log') return 'info';
    if (action === 'rate_limit') return 'warning';
    throw new Error(`getActionColor 未实现: ${action}`);
  }

  /**
   * 获取动作对应的图标 emoji
   * 映射：allow→✅、deny→🚫、log→📋、rate_limit→🐢
   * @param action 动作类型
   * @return emoji 字符串
   */
  static getActionIcon(action: SystemFirewallAction): string {
    if (action === 'allow') return '✅';
    if (action === 'deny') return '🚫';
    if (action === 'log') return '📋';
    if (action === 'rate_limit') return '🐢';
    throw new Error(`getActionIcon 未实现: ${action}`);
  }

  /**
   * 获取动作对应的中文标签
   * 映射：allow→允许、deny→拒绝、log→记录、rate_limit→限流
   * @param action 动作类型
   * @return 中文标签
   */
  static getActionLabel(action: SystemFirewallAction): string {
    if (action === 'allow') return '允许';
    if (action === 'deny') return '拒绝';
    if (action === 'log') return '记录';
    if (action === 'rate_limit') return '限流';
    throw new Error(`getActionLabel 未实现: ${action}`);
  }

  /**
   * 获取协议对应的中文标签
   * 映射：tcp→TCP、udp→UDP、icmp→ICMP、any→任意、undefined/其他→'—'
   * @param protocol 协议字符串（可选）
   * @return 协议标签
   */
  static getProtocolLabel(protocol?: string): string {
    if (protocol === 'tcp') return 'TCP';
    if (protocol === 'udp') return 'UDP';
    if (protocol === 'icmp') return 'ICMP';
    if (protocol === 'any') return '任意';
    if (protocol === undefined || protocol === null) return '—';
    return '—';
  }

  /**
   * 格式化命中次数
   * 规则：
   *   - 0 → '未命中'
   *   - 1-999 → 'N次'
   *   - ≥1000 → '999+次'
   * @param count 命中次数
   * @return 格式化命中次数字符串
   */
  static formatHitCount(count: number): string {
    if (count <= 0) return '未命中';
    if (count < HIT_COUNT_THRESHOLD) {
      return `${count}次`;
    }
    return '999+次';
  }

  /**
   * 格式化优先级
   * 规则：'优先级 N'
   * @param priority 优先级（1-100）
   * @return '优先级 N' 格式字符串
   */
  static formatPriority(priority: number): string {
    return `优先级 ${priority}`;
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
  { value: 'log', label: '记录' },
  { value: 'rate_limit', label: '限流' },
];

/**
 * Mock 系统防火墙规则数据
 * TODO M6 阶段：替换为 api.systemFirewall.list() 真实 API
 */
const MOCK_RULES: SystemFirewallRule[] = [
  {
    id: 'fw_1',
    name: '允许内网 SSH',
    sourceIp: '192.168.0.0/16',
    destinationPort: 22,
    protocol: 'tcp',
    action: 'allow',
    priority: 10,
    enabled: true,
    hitCount: 156,
    lastHitAt: '2025-03-01T08:30:00Z',
    createdAt: '2025-02-01T00:00:00Z',
    updatedAt: '2025-02-01T00:00:00Z',
  },
  {
    id: 'fw_2',
    name: '拒绝外部 3306',
    sourceIp: '0.0.0.0/0',
    destinationPort: 3306,
    protocol: 'tcp',
    action: 'deny',
    priority: 5,
    enabled: true,
    hitCount: 1200,
    lastHitAt: '2025-03-01T09:00:00Z',
    createdAt: '2025-02-01T00:00:00Z',
    updatedAt: '2025-02-01T00:00:00Z',
  },
  {
    id: 'fw_3',
    name: '记录所有 ICMP',
    protocol: 'icmp',
    action: 'log',
    priority: 50,
    enabled: true,
    hitCount: 0,
    createdAt: '2025-02-01T00:00:00Z',
    updatedAt: '2025-02-01T00:00:00Z',
  },
  {
    id: 'fw_4',
    name: '限流 80 端口',
    destinationPort: 80,
    protocol: 'tcp',
    action: 'rate_limit',
    priority: 30,
    enabled: false,
    hitCount: 42,
    createdAt: '2025-02-01T00:00:00Z',
    updatedAt: '2025-02-01T00:00:00Z',
  },
  {
    id: 'fw_5',
    name: '允许任意 DNS',
    destinationPort: 53,
    protocol: 'any',
    action: 'allow',
    priority: 20,
    enabled: true,
    hitCount: 999,
    lastHitAt: '2025-03-01T07:00:00Z',
    createdAt: '2025-02-01T00:00:00Z',
    updatedAt: '2025-02-01T00:00:00Z',
  },
];

@Component
export struct FirewallPage {
  // 规则列表
  @State rules: SystemFirewallRule[] = [];
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
   * 加载规则列表
   * TODO M6 阶段：替换为真实 API（api.systemFirewall.list）
   */
  private async loadRules(): Promise<void> {
    this.loading = true;
    try {
      // TODO M6: 接入真实 API（api.systemFirewall.*）
      // const res = await this.api.systemFirewall.list();
      // if (res.code === 0 && res.data) { this.rules = res.data.items; }
      this.rules = MOCK_RULES.slice();
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

  /** 获取经动作筛选 + 优先级排序后的列表 */
  private getFilteredRules(): SystemFirewallRule[] {
    let result = this.rules;
    if (this.activeAction !== 'all') {
      result = result.filter((r: SystemFirewallRule) => r.action === this.activeAction);
    }
    // 按 priority 升序（数字小的优先级高）
    return result.slice().sort((a: SystemFirewallRule, b: SystemFirewallRule) => a.priority - b.priority);
  }

  /**
   * 切换规则启用状态
   * TODO M6 阶段：调用真实 API（api.systemFirewall.toggle）
   */
  private async toggleRule(rule: SystemFirewallRule): Promise<void> {
    try {
      // TODO M6: const res = await this.api.systemFirewall.toggle(rule.id, !rule.enabled);
      this.rules = this.rules.map((r: SystemFirewallRule) => {
        if (r.id === rule.id) {
          return { ...r, enabled: !r.enabled };
        }
        return r;
      });
      this.msg.success(rule.enabled ? '已禁用' : '已启用');
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
            ForEach(this.getFilteredRules(), (rule: SystemFirewallRule) => {
              ListItem() {
                this.buildRuleCard(rule)
              }
            }, (rule: SystemFirewallRule) => rule.id)
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

  /** 单条规则卡片：动作徽章 + 名称 + 协议/源IP/端口 + 优先级 + 命中次数 + 启用开关 */
  @Builder
  buildRuleCard(rule: SystemFirewallRule) {
    GlassCard() {
      Column() {
        // 上部：动作徽章 + 优先级
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

          Text(SystemFirewallViewHelper.formatPriority(rule.priority))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_disabled'))
            .layoutWeight(1)
            .margin({ left: 8 })
            .maxLines(1)
            .textAlign(TextAlign.End)
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)

        // 规则名
        Text(rule.name)
          .fontSize(this.sm.getFontSize('body'))
          .fontColor(this.sm.getColor('text_primary'))
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .margin({ top: 4 })
          .width('100%')

        // 协议 + 源IP + 端口
        Row() {
          Text(`协议: ${SystemFirewallViewHelper.getProtocolLabel(rule.protocol)}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .layoutWeight(1)
          Text(`端口: ${rule.destinationPort !== undefined ? rule.destinationPort.toString() : '—'}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .layoutWeight(1)
        }
        .width('100%')
        .margin({ top: 4 })
        .alignItems(VerticalAlign.Center)

        if (rule.sourceIp) {
          Text(`源IP: ${rule.sourceIp}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .margin({ top: 2 })
        }

        // 命中次数 + 启用开关
        Row() {
          Text(`命中: ${SystemFirewallViewHelper.formatHitCount(rule.hitCount)}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .layoutWeight(1)
          // 启用开关（简化版：用按钮触发切换）
          Text(rule.enabled ? '✅ 已启用' : '⏸️ 已禁用')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor(rule.enabled ? 'success' : 'text_secondary'))
            .onClick(() => { this.toggleRule(rule); })
        }
        .width('100%')
        .margin({ top: 4 })
        .alignItems(VerticalAlign.Center)
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
    .width('100%')
  }
}
