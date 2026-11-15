/**
 * ContextChannelPage - 上下文消息页
 *
 * 职责：展示当前会话的上下文消息列表（按角色筛选），删除消息
 * 设计：
 *   - ContextChannelViewHelper（导出）：纯视图模型，封装 role 颜色映射、role 图标映射、
 *     role 中文标签、tokens 格式化、content 截断；无 UI 运行时依赖，可独立单元测试；
 *   - ContextChannelPage（@Component）：Column [TopNavMenu(标题"上下文消息"+返回)]
 *     + [role 筛选 Tab（全部/system/user/assistant/tool）]
 *     + [加载态/空态/错误态/列表]；列表项 GlassCard 含 role 徽章、content 摘要、
 *     tokens、创建时间、操作（删除）；删除走 AlertDialog 二次确认；
 *   - 颜色统一走 StyleManager，路由走 Router，API 走 ApiFacade.runtime，
 *     日志走 Logger，提示走 MessageManager；sessionId 通过 router 参数获取
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassCard、GlassButton
 *   - ../libs/api/ApiFacade：统一 API 门面（runtime.listContextMessages/removeContextMessage）
 *   - ../routing/Router：统一路由跳转 + 路由参数获取
 *   - ../libs/style/StyleManager：统一样式 token
 *   - ../libs/logger/Logger：统一日志
 *   - ../libs/message/MessageManager：统一消息提示
 *   - ../libs/types：ContextMessage、ContextRole
 *
 * 用法：
 *   由 Router.push 跳转进入，需通过路由参数传递 sessionId；
 *   aboutToAppear 解析 router 参数获取 sessionId，调用 api.runtime.listContextMessages 加载列表；
 *   role 筛选 Tab 切换 → 本地 filterByRole 过滤；
 *   删除 → AlertDialog 二次确认 → api.runtime.removeContextMessage → 刷新列表
 *
 * TDD：ContextChannelViewHelper 各方法按红绿灯垂直切片逐步实现，
 *      详见 ContextChannelPage.test.ets
 */

import { TopNavMenu, GlassCard, GlassButton } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { ContextMessage, ContextRole } from '../libs/types';

/** 日志标签 */
const TAG = 'ContextChannelPage';

// ===========================================================================
// ContextChannelViewHelper - 上下文消息视图模型（纯函数，无 UI 依赖，可独立单元测试）
//
// 设计：所有方法为 static，输入 → 输出，无副作用；
//       颜色方法返回 StyleManager 的 token 名（如 'primary'），由页面解析为实际颜色值；
//       图标方法返回 emoji 字符串直接渲染；
//       通过本文件 export，供 ohosTest 直接导入测试
// ===========================================================================

export class ContextChannelViewHelper {
  /**
   * 获取消息 role 对应的颜色 token 名
   * 映射：system→text_secondary，user→primary，assistant→success，tool→warning
   * @param role 上下文消息角色
   * @return StyleManager 颜色 token 名
   */
  static getRoleColor(role: ContextRole): string {
    if (role === 'system') return 'text_secondary';
    if (role === 'user') return 'primary';
    if (role === 'assistant') return 'success';
    return 'warning'; // tool
  }

  /**
   * 获取消息 role 对应的图标 emoji
   * 映射：system→⚙️，user→👤，assistant→🤖，tool→🔧
   * @param role 上下文消息角色
   * @return emoji 字符串
   */
  static getRoleIcon(role: ContextRole): string {
    if (role === 'system') return '⚙️';
    if (role === 'user') return '👤';
    if (role === 'assistant') return '🤖';
    return '🔧'; // tool
  }

  /**
   * 获取消息 role 的中文标签
   * 映射：system→系统，user→用户，assistant→助手，tool→工具
   * @param role 上下文消息角色
   * @return 中文标签字符串
   */
  static getRoleLabel(role: ContextRole): string {
    if (role === 'system') return '系统';
    if (role === 'user') return '用户';
    if (role === 'assistant') return '助手';
    return '工具'; // tool
  }

  /**
   * 格式化 tokens 数量为人类可读字符串
   * 映射：<1024→"N tokens"，<1048576→"X.XK tokens"，>=1048576→"X.XM tokens"
   * @param tokens token 数量
   * @return 格式化后的字符串，保留 1 位小数（K/M 模式）
   */
  static formatTokens(tokens: number): string {
    if (tokens < 1024) {
      return `${tokens} tokens`;
    }
    if (tokens < 1048576) {
      const k = tokens / 1024;
      return `${k.toFixed(1)}K tokens`;
    }
    const m = tokens / 1048576;
    return `${m.toFixed(1)}M tokens`;
  }

  /**
   * 截断内容，超长时截取 maxLen 字符并追加省略号
   * @param content 原始内容
   * @param maxLen 最大字符数，默认 200
   * @return 截断后的内容；未超长则原样返回
   */
  static truncateContent(content: string, maxLen: number = 200): string {
    if (content.length <= maxLen) return content;
    return content.substring(0, maxLen) + '...';
  }
}

// ===========================================================================
// role 筛选 Tab 配置
// ===========================================================================

interface RoleFilterOption {
  value: string;             // 'all' 或具体 ContextRole
  label: string;
}

/** role 筛选 Tab 列表（顺序即展示顺序） */
const ROLE_FILTERS: RoleFilterOption[] = [
  { value: 'all', label: '全部' },
  { value: 'system', label: '系统' },
  { value: 'user', label: '用户' },
  { value: 'assistant', label: '助手' },
  { value: 'tool', label: '工具' },
];

@Component
export struct ContextChannelPage {
  // 上下文消息列表（由 API 加载，驱动列表渲染；筛选在本地进行）
  @State messages: ContextMessage[] = [];
  // 加载态
  @State loading: boolean = true;
  // 错误态（sessionId 缺失或加载异常时为 true）
  @State hasError: boolean = false;
  // 错误文案
  @State errorMessage: string = '';
  // 当前会话 ID（由路由参数获取）
  @State sessionId: string = '';
  // 当前激活的 role 筛选值：'all' 或具体 role
  @State activeRole: string = 'all';

  // 统一库单例
  private api = ApiFacade.getInstance();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private msg = MessageManager.getInstance();

  aboutToAppear() {
    this.parseSessionId();
    if (this.sessionId) {
      this.loadMessages();
    }
  }

  /**
   * 从路由参数解析 sessionId
   * 流程：router.getCurrentParam() → 取 sessionId 字段 → 写入 @State
   * 异常：无 sessionId → 进入错误态，提示"会话 ID 缺失"
   */
  private parseSessionId(): void {
    const params = this.router.getCurrentParam() as { sessionId?: string } | undefined;
    const sid = params?.sessionId || '';
    if (!sid) {
      this.hasError = true;
      this.errorMessage = '会话 ID 缺失';
      this.loading = false;
      return;
    }
    this.sessionId = sid;
  }

  /**
   * 加载上下文消息列表
   * 流程：调用 api.runtime.listContextMessages(sessionId) → 写入 messages
   * 异常：记录日志并提示用户；finally 关闭 loading
   */
  private async loadMessages(): Promise<void> {
    this.loading = true;
    this.hasError = false;
    try {
      const res = await this.api.runtime.listContextMessages(this.sessionId);
      if (res.code === 0 && res.data) {
        this.messages = res.data.items;
      } else {
        this.hasError = true;
        this.errorMessage = res.message || '加载失败';
      }
    } catch (e) {
      this.logger.error(TAG, '加载上下文消息失败', e as Error);
      this.hasError = true;
      this.errorMessage = '加载上下文消息失败';
    } finally {
      this.loading = false;
    }
  }

  /**
   * 切换 role 筛选 Tab（本地过滤）
   */
  private switchRole(value: string): void {
    this.activeRole = value;
  }

  /**
   * 获取经当前 role 筛选后的列表
   * 规则：activeRole === 'all' 返回全量；否则按 role 字段过滤
   */
  private getFilteredMessages(): ContextMessage[] {
    if (this.activeRole === 'all') {
      return this.messages;
    }
    return this.messages.filter((m: ContextMessage) => m.role === this.activeRole);
  }

  /**
   * 删除前二次确认（AlertDialog）
   */
  private confirmDelete(message: ContextMessage): void {
    AlertDialog.show({
      title: '确认删除',
      message: `确定要删除这条${ContextChannelViewHelper.getRoleLabel(message.role)}消息吗？此操作不可撤销。`,
      autoCancel: true,
      alignment: DialogAlignment.Center,
      primaryButton: {
        value: '取消',
        action: () => {}
      },
      secondaryButton: {
        value: '删除',
        fontColor: this.sm.getColor('error'),
        action: () => { this.deleteMessage(message.id); }
      }
    });
  }

  /**
   * 执行删除
   * 流程：调用 api.runtime.removeContextMessage → 成功后重新加载列表
   */
  private async deleteMessage(messageId: string): Promise<void> {
    try {
      const res = await this.api.runtime.removeContextMessage(messageId);
      if (res.code === 0) {
        this.msg.success('删除成功');
        this.loadMessages();
      } else {
        this.msg.error(res.message || '删除失败');
      }
    } catch (e) {
      this.logger.error(TAG, '删除上下文消息失败', e as Error);
      this.msg.error('删除失败');
    }
  }

  /** 格式化时间（YYYY-MM-DD HH:mm），无值回退 '未知' */
  private formatTime(timeStr: string): string {
    if (!timeStr) return '未知';
    const d = new Date(timeStr);
    if (isNaN(d.getTime())) return '未知';
    const yyyy = d.getFullYear();
    const MM = (d.getMonth() + 1).toString().padStart(2, '0');
    const dd = d.getDate().toString().padStart(2, '0');
    const hh = d.getHours().toString().padStart(2, '0');
    const mm = d.getMinutes().toString().padStart(2, '0');
    return `${yyyy}-${MM}-${dd} ${hh}:${mm}`;
  }

  build() {
    Column() {
      // 顶部导航栏：标题"上下文消息" + 返回
      TopNavMenu({
        title: '上下文消息',
        showBack: true,
        showMenu: false,
        onBack: () => { this.router.back(); }
      })

      // role 筛选 Tab：横向滚动胶囊
      Scroll() {
        Row({ space: 8 }) {
          ForEach(ROLE_FILTERS, (opt: RoleFilterOption) => {
            Text(opt.label)
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.activeRole === opt.value
                ? this.sm.getColor('text_on_primary')
                : this.sm.getColor('text_secondary'))
              .backgroundColor(this.activeRole === opt.value
                ? this.sm.getColor('primary')
                : this.sm.getColor('surface'))
              .padding({ left: 12, right: 12, top: 6, bottom: 6 })
              .borderRadius(16)
              .onClick(() => { this.switchRole(opt.value); })
          }, (opt: RoleFilterOption) => opt.value)
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

      // 主体：加载态 / 错误态 / 空态 / 列表
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
      } else if (this.hasError) {
        // 错误态：展示 errorMessage + 重新加载按钮
        Column() {
          Text('⚠️ ' + this.errorMessage)
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontColor(this.sm.getColor('error'))
            .margin({ bottom: this.sm.getSpacing('md') })
            .textAlign(TextAlign.Center)
          GlassButton({
            text: '重新加载',
            type: 'primary',
            size: 'medium',
            onClick: () => { this.loadMessages(); }
          })
        }
        .width('100%')
        .layoutWeight(1)
        .justifyContent(FlexAlign.Center)
        .alignItems(HorizontalAlign.Center)
      } else if (this.getFilteredMessages().length === 0) {
        Column() {
          Text('暂无上下文消息')
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontColor(this.sm.getColor('text_secondary'))
        }
        .width('100%')
        .layoutWeight(1)
        .justifyContent(FlexAlign.Center)
        .alignItems(HorizontalAlign.Center)
      } else {
        List({ space: 12 }) {
          ForEach(this.getFilteredMessages(), (message: ContextMessage) => {
            ListItem() {
              this.buildMessageCard(message)
            }
          }, (message: ContextMessage) => message.id)
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
  // 消息卡片构建器
  // ===========================================================================

  /** 单条消息卡片：role 徽章 / content 摘要 / tokens / 创建时间 / 操作按钮 */
  @Builder
  buildMessageCard(message: ContextMessage) {
    GlassCard() {
      Column() {
        // 上部：role 徽章 + tokens（右对齐）
        Row() {
          // role 徽章：图标 + 标签
          Row() {
            Text(ContextChannelViewHelper.getRoleIcon(message.role))
              .fontSize(14)
            Text(ContextChannelViewHelper.getRoleLabel(message.role))
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_on_primary'))
              .margin({ left: 4 })
          }
          .padding({ left: 8, right: 8, top: 2, bottom: 2 })
          .borderRadius(10)
          .backgroundColor(this.sm.getColor(ContextChannelViewHelper.getRoleColor(message.role)))
          .alignItems(VerticalAlign.Center)

          // tokens（右对齐）
          Text(ContextChannelViewHelper.formatTokens(message.tokens))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .layoutWeight(1)
            .textAlign(TextAlign.End)
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)

        // content 摘要（截断到 200 字符，最多 4 行省略）
        Text(ContextChannelViewHelper.truncateContent(message.content))
          .fontSize(this.sm.getFontSize('body'))
          .fontColor(this.sm.getColor('text_primary'))
          .maxLines(4)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .margin({ top: this.sm.getSpacing('sm') })
          .width('100%')

        // 底部行：创建时间
        Row() {
          Text(this.formatTime(message.createdAt))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_disabled'))
            .layoutWeight(1)
          GlassButton({
            text: '删除',
            type: 'danger',
            size: 'small',
            onClick: () => { this.confirmDelete(message); }
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
