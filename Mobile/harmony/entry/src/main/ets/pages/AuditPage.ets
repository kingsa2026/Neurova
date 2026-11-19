/**
 * AuditPage - 审计日志页（R6 接真实 API）
 *
 * 职责：展示系统审计日志列表（/v1/audit，require_admin），按事件类筛选，
 *       点击项展开 details 详情，导出按钮
 * 设计：
 *   - AuditViewHelper（导出）：纯视图模型，封装事件类颜色/图标映射（开放集合，
 *     未知值兜默认不抛错——后端 action 是自由文本）、事件类筛选匹配、
 *     时间戳格式化、details JSON 格式化、资源截断；无 UI 依赖，可独立单元测试；
 *   - AuditPage（@Component）：Column[TopNavMenu(标题"审计日志"+返回+导出)]
 *     + [事件类筛选 Tab（全部/认证/登出/配置/用户/角色/安全/系统）]
 *     + [加载态/空态/列表] + [详情展开区域]；
 *     列表项 GlassCard：事件类徽章、用户、资源、时间戳、展开后 details JSON；
 *   - 颜色统一走 StyleManager，路由走 Router，已接线 PageMap（P1-33）；
 *     数据源 AuditApi.list()（R6：替换 mock）。
 *
 * 契约说明（诚实缺省）：
 *   - 列表条目（audit.py _entry_to_record）：id/timestamp(ISO Z)/user/action/
 *     resource/details——后端列表面无 username/ip/success/before/after 字段，
 *     本页不再渲染这些 mock 时代的列；ip 等扩展字段走 /audit/search 的
 *     AuditLog 契约（AuditApi.search，本页列表主源仍为分页 list）。
 *   - 条目 id 形如 "{event_type}_{ms}"，事件类 Tab 按 id 前缀匹配（比
 *     自由文本 action 子串稳定）。
 *   - 导出（GET /audit/export）返回裸数组，移动端无文件落盘面——取回后
 *     如实提示条数，不谎称"已保存文件"。
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassCard、GlassButton
 *   - ../libs/api/ApiFacade：统一 API 门面（api.audit.*）
 *   - ../libs/api/modules/AuditApi：AuditRecordDto 契约
 *   - ../routing/Router、../libs/style/StyleManager、../libs/logger/Logger、
 *     ../libs/message/MessageManager
 *
 * 用法：
 *   由 Router.push(RouteNames.AUDIT) 跳转进入；
 *   aboutToAppear 经 api.audit.list() 加载第一页；
 *   事件类筛选 Tab 切换 → 本地按 id 前缀过滤；
 *   点击列表项 → 切换展开/收起 details 详情；
 *   导出按钮 → api.audit.exportAudit() → 提示取回条数。
 */

import { TopNavMenu, GlassCard, GlassButton } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { AuditRecordDto } from '../libs/api/modules/AuditApi';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';

/** 日志标签 */
const TAG = 'AuditPage';

/** 默认资源截断长度 */
const DEFAULT_RESOURCE_MAX_LEN = 100;

// ===========================================================================
// AuditViewHelper - 审计日志视图模型（纯函数，无 UI 依赖，可独立单元测试）
//
// 后端 action 是自由文本、event_type 是封闭枚举但随条目 id 前缀下发——
// 一切映射按开放集合处理：已知值给语义色，未知值兜 'info'，不抛错。
// ===========================================================================

export class AuditViewHelper {
  /**
   * 获取事件类对应的颜色 token 名（按 id 的 event_type 前缀；未知兜 'info'）
   * 映射：auth_login→success、auth_logout→text_secondary、auth_failed→error、
   *       config_change→warning、user_change/role_change→primary、
   *       security_event→error、system_event→info、data_access→secondary、
   *       tool_execution→info、api_key_change→warning
   * @param entryId 条目 id（"{event_type}_{ms}"；空/无前缀 → 'info'）
   * @return StyleManager 颜色 token 名
   */
  static getEventColor(entryId: string): string {
    if (entryId.startsWith('auth_failed') || entryId.startsWith('security_event')) return 'error';
    if (entryId.startsWith('auth_login')) return 'success';
    if (entryId.startsWith('auth_logout')) return 'text_secondary';
    if (entryId.startsWith('config_change') || entryId.startsWith('api_key_change')) return 'warning';
    if (entryId.startsWith('user_change') || entryId.startsWith('role_change')) return 'primary';
    if (entryId.startsWith('data_access')) return 'secondary';
    return 'info';
  }

  /**
   * 获取事件类对应的图标 emoji（未知兜 '📌'）
   * @param entryId 条目 id（"{event_type}_{ms}"）
   * @return emoji 字符串
   */
  static getEventIcon(entryId: string): string {
    if (entryId.startsWith('auth_failed')) return '⛔';
    if (entryId.startsWith('security_event')) return '🛡️';
    if (entryId.startsWith('auth_login')) return '🔑';
    if (entryId.startsWith('auth_logout')) return '🚪';
    if (entryId.startsWith('config_change')) return '⚙️';
    if (entryId.startsWith('api_key_change')) return '🗝️';
    if (entryId.startsWith('user_change')) return '👤';
    if (entryId.startsWith('role_change')) return '🎭';
    if (entryId.startsWith('data_access')) return '📂';
    if (entryId.startsWith('tool_execution')) return '🔧';
    if (entryId.startsWith('system_event')) return '🖥️';
    return '📌';
  }

  /**
   * 获取事件类对应的中文标签（未知兜 '系统事件'）
   * @param entryId 条目 id（"{event_type}_{ms}"）
   * @return 中文文案
   */
  static getEventLabel(entryId: string): string {
    if (entryId.startsWith('auth_failed')) return '认证失败';
    if (entryId.startsWith('security_event')) return '安全事件';
    if (entryId.startsWith('auth_login')) return '登录';
    if (entryId.startsWith('auth_logout')) return '登出';
    if (entryId.startsWith('config_change')) return '配置变更';
    if (entryId.startsWith('api_key_change')) return '密钥变更';
    if (entryId.startsWith('user_change')) return '用户变更';
    if (entryId.startsWith('role_change')) return '角色变更';
    if (entryId.startsWith('data_access')) return '数据访问';
    if (entryId.startsWith('tool_execution')) return '工具执行';
    if (entryId.startsWith('system_event')) return '系统事件';
    return '系统事件';
  }

  /**
   * 判断条目是否命中事件类筛选
   * 规则：filter === 'all' 恒命中；否则按条目 id 的 event_type 前缀匹配
   * @param entryId 条目 id（"{event_type}_{ms}"）
   * @param filterValue 筛选值（'all' 或 event_type 前缀，如 'auth_login'）
   * @return 是否命中
   */
  static matchesEventFilter(entryId: string, filterValue: string): boolean {
    if (filterValue === 'all') return true;
    return entryId.startsWith(filterValue);
  }

  /**
   * 格式化 ISO 时间戳为 YYYY-MM-DD HH:mm:ss
   * 规则：无值/空值/无效 → '—'
   * @param timestamp ISO 时间戳字符串
   * @return 格式化时间或 '—'
   */
  static formatTimestamp(timestamp: string): string {
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
   * 格式化 details 为 JSON 字符串
   * 规则：undefined/null/空对象 → '—'，否则返回 JSON.stringify 结果
   * @param details 详情对象（可选）
   * @return JSON 字符串或 '—'
   */
  static formatDetails(details?: Record<string, Object> | null): string {
    if (!details) return '—';
    const keys = Object.keys(details);
    if (keys.length === 0) return '—';
    return JSON.stringify(details);
  }

  /**
   * 截断资源字符串
   * 规则：长度 ≤ maxLen → 原样返回；> maxLen → 截取前 maxLen 字符 + '...'
   * @param resource 资源字符串
   * @param maxLen 最大长度，默认 100
   * @return 截断后的字符串
   */
  static truncateResource(resource: string, maxLen: number = DEFAULT_RESOURCE_MAX_LEN): string {
    if (resource.length <= maxLen) return resource;
    return resource.substring(0, maxLen) + '...';
  }
}

/** 事件类筛选 Tab 配置（value = event_type 前缀） */
interface EventFilterOption {
  value: string;
  label: string;
}

/** 事件类筛选 Tab 列表 */
const EVENT_FILTERS: EventFilterOption[] = [
  { value: 'all', label: '全部' },
  { value: 'auth_login', label: '登录' },
  { value: 'auth_logout', label: '登出' },
  { value: 'auth_failed', label: '认证失败' },
  { value: 'config_change', label: '配置' },
  { value: 'user_change', label: '用户' },
  { value: 'role_change', label: '角色' },
  { value: 'security_event', label: '安全' },
  { value: 'system_event', label: '系统' },
];

@Component
export struct AuditPage {
  // 审计日志列表（api.audit.list() 真实数据）
  @State audits: AuditRecordDto[] = [];
  // 加载态
  @State loading: boolean = true;
  // 当前激活的事件类筛选
  @State activeFilter: string = 'all';
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
   * 加载审计日志列表（GET /v1/audit 第一页，require_admin）
   */
  private async loadAudits(): Promise<void> {
    this.loading = true;
    try {
      const res = await this.api.audit.list({ page: 1, pageSize: 20 });
      if (res.code === 0 && res.data) {
        this.audits = res.data.items;
      } else {
        this.audits = [];
        this.msg.error(res.message && res.message.length > 0 ? res.message : '加载审计日志失败');
      }
    } catch (e) {
      this.logger.error(TAG, '加载审计日志失败', e as Error);
      this.msg.error('加载审计日志失败（需要管理员权限）');
      this.audits = [];
    } finally {
      this.loading = false;
    }
  }

  /** 切换事件类筛选 */
  private switchFilter(value: string): void {
    this.activeFilter = value;
  }

  /** 获取经事件类筛选后的列表 */
  private getFilteredAudits(): AuditRecordDto[] {
    return this.audits.filter((a: AuditRecordDto) => AuditViewHelper.matchesEventFilter(a.id, this.activeFilter));
  }

  /** 切换某条审计的展开状态 */
  private toggleExpand(id: string): void {
    this.expandedId = this.expandedId === id ? '' : id;
  }

  /**
   * 导出审计日志（GET /v1/audit/export，裸数组）
   * 移动端无文件落盘面：取回后如实提示条数
   */
  private async exportAudits(): Promise<void> {
    try {
      const res = await this.api.audit.exportAudit();
      if (res.code === 0 && res.data) {
        this.msg.success(`已从终端取回 ${res.data.length} 条审计日志`);
      } else {
        this.msg.error(res.message && res.message.length > 0 ? res.message : '导出审计日志失败');
      }
    } catch (e) {
      this.logger.error(TAG, '导出审计日志失败', e as Error);
      this.msg.error('导出审计日志失败');
    }
  }

  build() {
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
          btnSize: 'small',
          onTap: () => { this.exportAudits(); }
        })
      }

      // 事件类筛选 Tab
      Scroll() {
        Row({ space: 8 }) {
          ForEach(EVENT_FILTERS, (opt: EventFilterOption) => {
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
          }, (opt: EventFilterOption) => opt.value)
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
          ForEach(this.getFilteredAudits(), (audit: AuditRecordDto) => {
            ListItem() {
              this.buildAuditCard(audit)
            }
          }, (audit: AuditRecordDto) => audit.id)
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
  // 审计卡片构建器
  // ===========================================================================

  /** 单条审计卡片：事件类徽章 + 用户 + 资源 + 时间戳 + 可展开 details */
  @Builder
  buildAuditCard(audit: AuditRecordDto) {
    GlassCard() {
      Column() {
        // 上部：事件类徽章 + 时间戳
        Row() {
          // 事件类徽章
          Row() {
            Text(AuditViewHelper.getEventIcon(audit.id))
              .fontSize(14)
            Text(AuditViewHelper.getEventLabel(audit.id))
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_on_primary'))
              .margin({ left: 4 })
          }
          .padding({ left: 8, right: 8, top: 2, bottom: 2 })
          .borderRadius(this.sm.getRadius('sm'))
          .backgroundColor(this.sm.getColor(AuditViewHelper.getEventColor(audit.id)))

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
        .width('100%')
        .alignItems(VerticalAlign.Center)

        // 用户 + 操作原文
        Row() {
          Text(`用户: ${audit.user}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
            .layoutWeight(1)
        }
        .width('100%')
        .margin({ top: 4 })
        .alignItems(VerticalAlign.Center)
        Text(`操作: ${audit.action}`)
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('text_secondary'))
          .margin({ top: 4 })
          .maxLines(2)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .width('100%')

        // 资源
        Text(`资源: ${AuditViewHelper.truncateResource(audit.resource)}`)
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('text_secondary'))
          .margin({ top: 4 })
          .maxLines(2)
          .textOverflow({ overflow: TextOverflow.Ellipsis })

        // 展开详情按钮
        Text(this.expandedId === audit.id ? '收起 ▲' : '展开 ▼')
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('info'))
          .margin({ top: 4 })
          .onClick(() => { this.toggleExpand(audit.id); })

        // 展开后显示 details JSON
        if (this.expandedId === audit.id) {
          Column() {
            Text('详情')
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
            Text(AuditViewHelper.formatDetails(audit.details))
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
  }
}
