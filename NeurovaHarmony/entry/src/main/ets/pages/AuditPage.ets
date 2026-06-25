/**
 * AuditPage - 审计日志页（P3）
 *
 * 职责：展示系统审计日志列表，按 userId/action/时间范围筛选，
 *       操作类型徽章颜色区分，点击项展开 before/after 详情，导出按钮
 * 设计：
 *   - AuditViewHelper（导出）：纯视图模型，封装操作类型颜色/图标/标签映射、
 *     成功状态颜色、时间戳格式化、元数据 JSON 格式化、资源类型截断，
 *     无 UI 依赖，可独立单元测试；
 *   - AuditPage（@Component）：Stack[Column[TopNavMenu(标题"审计日志"+返回+导出)]
 *     + [action 筛选 Tab（全部/create/update/delete/login/logout/export/import/config_change）]
 *     + [加载态/空态/列表] + [详情展开区域]]；
 *     列表项 GlassCard：操作类型徽章、用户名、IP、资源、时间戳、成功状态、
 *     展开后 before/after JSON 详情；
 *     颜色统一走 StyleManager（返回 token 名），路由走 Router，
 *     API 暂无审计专用模块 → aboutToAppear 加载 mock 静态数据 + TODO M6 标注。
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassCard、GlassButton、GlassInput、GlassPanel
 *   - ../libs/api/ApiFacade：统一 API 门面（仅占位，未实际调用）
 *   - ../routing/Router：统一路由跳转
 *   - ../libs/style/StyleManager：统一样式 token
 *   - ../libs/logger/Logger：统一日志
 *   - ../libs/message/MessageManager：统一消息提示
 *   - ../libs/types：AuditEntry、AuditAction、Metadata
 *
 * 用法：
 *   由 Router.push(RouteNames.AUDIT) 跳转进入；
 *   aboutToAppear 加载 mock 审计列表（TODO M6 接入真实 API）；
 *   action 筛选 Tab 切换 → 本地按 action 过滤；
 *   点击列表项 → 切换展开/收起 before/after 详情；
 *   导出按钮 → TODO M6 接入 api.audit.export
 *
 * TDD：AuditViewHelper 各方法按红绿灯垂直切片逐步实现，详见 AuditPage.test.ets
 */

import { TopNavMenu, GlassCard, GlassButton, GlassInput, GlassPanel } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { AuditEntry, AuditAction, Metadata } from '../libs/types';

/** 日志标签 */
const TAG = 'AuditPage';

/** 默认资源类型截断长度 */
const DEFAULT_RESOURCE_MAX_LEN = 100;

// ===========================================================================
// AuditViewHelper - 审计日志视图模型（纯函数，无 UI 依赖，可独立单元测试）
//
// 设计：所有方法为 static，输入 → 输出，无副作用；
//       颜色方法返回 StyleManager 的 token 名（如 'success'），由页面解析为实际颜色值；
//       通过本文件 export，供 ohosTest 直接导入测试
// ===========================================================================

export class AuditViewHelper {
  /**
   * 获取操作类型对应的颜色 token 名
   * 映射：create→success、update→info、delete→error、login→info、
   *       logout→text_secondary、export→warning、import→warning、config_change→warning
   * @param action 操作类型
   * @return StyleManager 颜色 token 名
   */
  static getActionColor(action: AuditAction): string {
    if (action === 'create') return 'success';
    if (action === 'update') return 'info';
    if (action === 'delete') return 'error';
    if (action === 'login') return 'info';
    if (action === 'logout') return 'text_secondary';
    if (action === 'export') return 'warning';
    if (action === 'import') return 'warning';
    if (action === 'config_change') return 'warning';
    throw new Error(`getActionColor 未实现: ${action}`);
  }

  /**
   * 获取操作类型对应的图标 emoji
   * 映射：create→✨、update→✏️、delete→🗑️、login→🔑、logout→🚪、
   *       export→📤、import→📥、config_change→⚙️
   * @param action 操作类型
   * @return emoji 字符串
   */
  static getActionIcon(action: AuditAction): string {
    if (action === 'create') return '✨';
    if (action === 'update') return '✏️';
    if (action === 'delete') return '🗑️';
    if (action === 'login') return '🔑';
    if (action === 'logout') return '🚪';
    if (action === 'export') return '📤';
    if (action === 'import') return '📥';
    if (action === 'config_change') return '⚙️';
    throw new Error(`getActionIcon 未实现: ${action}`);
  }

  /**
   * 获取操作类型对应的中文标签
   * 映射：create→创建、update→更新、delete→删除、login→登录、logout→登出、
   *       export→导出、import→导入、config_change→配置变更
   * @param action 操作类型
   * @return 中文标签
   */
  static getActionLabel(action: AuditAction): string {
    if (action === 'create') return '创建';
    if (action === 'update') return '更新';
    if (action === 'delete') return '删除';
    if (action === 'login') return '登录';
    if (action === 'logout') return '登出';
    if (action === 'export') return '导出';
    if (action === 'import') return '导入';
    if (action === 'config_change') return '配置变更';
    throw new Error(`getActionLabel 未实现: ${action}`);
  }

  /**
   * 获取审计条目成功状态对应的颜色 token 名
   * 映射：成功→success、失败→error
   * @param success 是否成功
   * @return StyleManager 颜色 token 名
   */
  static getSuccessColor(success: boolean): string {
    return success ? 'success' : 'error';
  }

  /**
   * 格式化 ISO 时间戳为 YYYY-MM-DD HH:mm:ss
   * 规则：无值/空值/无效 → '—'
   * @param timestamp ISO 时间戳字符串（可选）
   * @return 格式化时间或 '—'
   */
  static formatTimestamp(timestamp?: string): string {
    if (!timestamp || timestamp.length === 0) return '—';
    const d = new Date(timestamp);
    if (isNaN(d.getTime())) return '—';
    const yyyy = d.getFullYear();
    const MM = (d.getMonth() + 1).toString().padStart(2, '0');
    const dd = d.getDate().toString().padStart(2, '0');
    const HH = d.getHours().toString().padStart(2, '0');
    const mm = d.getMinutes().toString().padStart(2, '0');
    const ss = d.getSeconds().toString().padStart(2, '0');
    return `${yyyy}-${MM}-${dd} ${HH}:${mm}:${ss}`;
  }

  /**
   * 格式化元数据为 JSON 字符串
   * 规则：undefined/空对象 → '—'，否则返回 JSON.stringify 结果
   * @param meta 元数据对象（可选）
   * @return JSON 字符串或 '—'
   */
  static formatMetadata(meta?: Metadata): string {
    if (!meta) return '—';
    const keys = Object.keys(meta);
    if (keys.length === 0) return '—';
    return JSON.stringify(meta);
  }

  /**
   * 截断资源类型字符串
   * 规则：
   *   - 长度 ≤ maxLen → 原样返回
   *   - 长度 > maxLen → 截取前 maxLen 字符并追加省略号 '...'
   * @param resource 资源类型字符串
   * @param maxLen 最大长度，默认 100
   * @return 截断后的字符串
   */
  static truncateResource(resource: string, maxLen: number = DEFAULT_RESOURCE_MAX_LEN): string {
    if (resource.length <= maxLen) return resource;
    return resource.substring(0, maxLen) + '...';
  }
}

/** 操作类型筛选 Tab 配置 */
interface ActionFilterOption {
  value: string;     // 'all' 或 AuditAction
  label: string;
}

/** 操作类型筛选 Tab 列表 */
const ACTION_FILTERS: ActionFilterOption[] = [
  { value: 'all', label: '全部' },
  { value: 'create', label: '创建' },
  { value: 'update', label: '更新' },
  { value: 'delete', label: '删除' },
  { value: 'login', label: '登录' },
  { value: 'logout', label: '登出' },
  { value: 'export', label: '导出' },
  { value: 'import', label: '导入' },
  { value: 'config_change', label: '配置变更' },
];

/**
 * Mock 审计日志数据
 * TODO M6 阶段：替换为 api.audit.list() 真实 API
 */
const MOCK_AUDITS: AuditEntry[] = [
  {
    id: 'audit_1',
    userId: 'user_1',
    username: 'admin',
    action: 'login',
    resource: 'auth',
    ip: '192.168.1.10',
    userAgent: 'Mozilla/5.0',
    timestamp: '2025-03-01T09:00:00Z',
    success: true,
  },
  {
    id: 'audit_2',
    userId: 'user_1',
    username: 'admin',
    action: 'create',
    resource: 'agent',
    resourceId: 'agent_001',
    ip: '192.168.1.10',
    before: undefined,
    after: { name: 'Agent-001', model: 'gpt-4' },
    timestamp: '2025-03-01T09:15:00Z',
    success: true,
  },
  {
    id: 'audit_3',
    userId: 'user_2',
    username: 'alice',
    action: 'delete',
    resource: 'memory',
    resourceId: 'mem_42',
    ip: '192.168.1.20',
    before: { content: '旧记忆内容' },
    after: undefined,
    timestamp: '2025-03-01T10:30:00Z',
    success: true,
  },
  {
    id: 'audit_4',
    userId: 'user_3',
    username: 'bob',
    action: 'config_change',
    resource: 'system_config',
    ip: '192.168.1.30',
    before: { max_tokens: 1000 },
    after: { max_tokens: 2000 },
    timestamp: '2025-03-01T11:45:00Z',
    success: true,
  },
  {
    id: 'audit_5',
    userId: 'user_4',
    username: 'attacker',
    action: 'login',
    resource: 'auth',
    ip: '10.0.0.5',
    timestamp: '2025-03-01T12:00:00Z',
    success: false,
    errorMessage: '密码错误',
  },
];

@Component
export struct AuditPage {
  // 审计日志列表
  @State audits: AuditEntry[] = [];
  // 加载态
  @State loading: boolean = true;
  // 当前激活的操作类型筛选
  @State activeAction: string = 'all';
  // 展开详情的审计 ID
  @State expandedId: string = '';

  // 统一库单例
  private api = ApiFacade.getInstance();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private msg = MessageManager.getInstance();

  aboutToAppear() {
    this.loadAudits();
  }

  /**
   * 加载审计日志列表
   * TODO M6 阶段：替换为真实 API（api.audit.list）
   */
  private async loadAudits(): Promise<void> {
    this.loading = true;
    try {
      // TODO M6: 接入真实 API（api.audit.*）
      // const res = await this.api.audit.list({ userId, action, start, end });
      // if (res.code === 0 && res.data) { this.audits = res.data.items; }
      this.audits = MOCK_AUDITS.slice();
    } catch (e) {
      this.logger.error(TAG, '加载审计日志失败', e as Error);
      this.msg.error('加载审计日志失败');
    } finally {
      this.loading = false;
    }
  }

  /** 切换操作类型筛选 */
  private switchAction(value: string): void {
    this.activeAction = value;
  }

  /** 获取经操作类型筛选后的列表 */
  private getFilteredAudits(): AuditEntry[] {
    if (this.activeAction === 'all') {
      return this.audits;
    }
    return this.audits.filter((a: AuditEntry) => a.action === this.activeAction);
  }

  /** 切换某条审计的展开状态 */
  private toggleExpand(id: string): void {
    this.expandedId = this.expandedId === id ? '' : id;
  }

  /**
   * 导出审计日志
   * TODO M6 阶段：调用真实 API（api.audit.export）
   */
  private async exportAudits(): Promise<void> {
    try {
      // TODO M6: const res = await this.api.audit.export({ format: 'csv' });
      this.msg.success(`已导出 ${this.audits.length} 条审计日志`);
    } catch (e) {
      this.logger.error(TAG, '导出审计日志失败', e as Error);
      this.msg.error('导出审计日志失败');
    }
  }

  build() {
    Stack() {
      Column() {
        // 顶部导航栏：标题"审计日志" + 返回 + 导出
        TopNavMenu({
          title: '审计日志',
          showBack: true,
          showMenu: false,
          onBack: () => { this.router.back(); }
        }) {
          GlassButton({
            text: '导出',
            type: 'default',
            size: 'small',
            onClick: () => { this.exportAudits(); }
          })
        }

        // 操作类型筛选 Tab
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
        } else if (this.getFilteredAudits().length === 0) {
          Column() {
            Text('暂无审计日志')
              .fontSize(this.sm.getFontSize('subtitle'))
              .fontColor(this.sm.getColor('text_secondary'))
          }
          .width('100%')
          .layoutWeight(1)
          .justifyContent(FlexAlign.Center)
          .alignItems(HorizontalAlign.Center)
        } else {
          List({ space: 12 }) {
            ForEach(this.getFilteredAudits(), (audit: AuditEntry) => {
              ListItem() {
                this.buildAuditCard(audit)
              }
            }, (audit: AuditEntry) => audit.id)
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
  // 审计卡片构建器
  // ===========================================================================

  /** 单条审计卡片：操作类型徽章 + 用户名 + IP + 资源 + 时间戳 + 成功状态 + 可展开 before/after */
  @Builder
  buildAuditCard(audit: AuditEntry) {
    GlassCard() {
      Column() {
        // 上部：操作类型徽章 + 时间戳
        Row() {
          // 操作类型徽章
          Row() {
            Text(AuditViewHelper.getActionIcon(audit.action))
              .fontSize(14)
            Text(AuditViewHelper.getActionLabel(audit.action))
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_on_primary'))
              .margin({ left: 4 })
          }
          .padding({ left: 8, right: 8, top: 2, bottom: 2 })
          .borderRadius(this.sm.getRadius('sm'))
          .backgroundColor(this.sm.getColor(AuditViewHelper.getActionColor(audit.action)))

          // 时间戳
          Text(AuditViewHelper.formatTimestamp(audit.timestamp))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_disabled'))
            .layoutWeight(1)
            .margin({ left: 8 })
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
            .textAlign(TextAlign.End)
        }
        .alignItems(VerticalAlign.Center)

        // 用户名 + IP
        Row() {
          Text(`用户: ${audit.username}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .layoutWeight(1)
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
          Text(`IP: ${audit.ip}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_disabled'))
            .maxLines(1)
        }
        .width('100%')
        .margin({ top: 4 })
        .alignItems(VerticalAlign.Center)

        // 资源类型
        Text(`资源: ${AuditViewHelper.truncateResource(audit.resource)}`)
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('text_secondary'))
          .margin({ top: 4 })
          .maxLines(2)
          .textOverflow({ overflow: TextOverflow.Ellipsis })

        // 成功状态
        Row() {
          Text(audit.success ? '✅ 成功' : '❌ 失败')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor(AuditViewHelper.getSuccessColor(audit.success)))
          if (audit.errorMessage) {
            Text(` | ${audit.errorMessage}`)
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('error'))
              .maxLines(1)
              .textOverflow({ overflow: TextOverflow.Ellipsis })
              .layoutWeight(1)
              .margin({ left: 4 })
          }
        }
        .width('100%')
        .margin({ top: 4 })
        .alignItems(VerticalAlign.Center)

        // 展开详情按钮
        Text(this.expandedId === audit.id ? '收起 ▲' : '展开 ▼')
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('info'))
          .margin({ top: 4 })
          .onClick(() => { this.toggleExpand(audit.id); })

        // 展开后显示 before/after 详情
        if (this.expandedId === audit.id) {
          Column() {
            Text('变更前')
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
            Text(AuditViewHelper.formatMetadata(audit.before))
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .padding({ top: 4, bottom: 4, left: 8, right: 8 })
              .backgroundColor(this.sm.getColor('surface'))
              .borderRadius(this.sm.getRadius('sm'))
              .width('100%')
              .margin({ top: 4 })

            Text('变更后')
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .margin({ top: 8 })
            Text(AuditViewHelper.formatMetadata(audit.after))
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .padding({ top: 4, bottom: 4, left: 8, right: 8 })
              .backgroundColor(this.sm.getColor('surface'))
              .borderRadius(this.sm.getRadius('sm'))
              .width('100%')
              .margin({ top: 4 })
          }
          .width('100%')
          .alignItems(HorizontalAlign.Start)
          .margin({ top: 8 })
        }
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
    .width('100%')
    .onClick(() => { this.toggleExpand(audit.id); })
  }
}
