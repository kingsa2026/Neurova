/**
 * SessionSyncPage - 会话同步页
 *
 * 职责：展示会话同步记录列表，按 sessionId 或 agentId 筛选，支持立即同步、新建
 * 设计：
 *   - SessionSyncViewHelper（导出）：纯视图模型，封装状态颜色映射、状态图标映射、
 *     状态标签映射、消息数格式化、相对时间格式化，无 UI 运行时依赖，可独立单元测试；
 *   - SessionSyncPage（@Component）：Stack[Column[TopNavMenu(标题"会话同步"+返回+新建)]
 *     + [加载态/空态/列表] + [新建弹窗]]；
 *     列表项 GlassCard 含状态徽章、源/目标渠道、消息数、最后同步时间、操作按钮（立即同步/删除）；
 *     新建弹窗内嵌 Stack 条件渲染；
 *   - 颜色统一走 StyleManager（返回 token 名），路由走 Router，
 *     API 走 ApiFacade.sessionSync，消息走 MessageManager。
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassCard、GlassButton、GlassInput、GlassPanel
 *   - ../libs/api/ApiFacade：统一 API 门面（sessionSync 模块）
 *   - ../routing/Router：统一路由跳转
 *   - ../libs/style/StyleManager：统一样式 token
 *   - ../libs/logger/Logger：统一日志
 *   - ../libs/message/MessageManager：统一消息提示
 *   - ../libs/types：SessionSync
 *
 * 用法：
 *   由 Router.push 跳转进入；
 *   aboutToAppear 调用 api.sessionSync.list 加载列表；
 *   新建按钮 → 打开弹窗 → 调用 api.sessionSync.create → 刷新列表；
 *   立即同步按钮 → 调用 api.sessionSync.trigger → 提示结果并刷新列表；
 *   删除按钮 → AlertDialog 二次确认 → 调用 api.sessionSync.remove → 刷新列表
 *
 * TDD：SessionSyncViewHelper 各方法按红绿灯垂直切片逐步实现，
 *      详见 SessionSyncPage.test.ets
 */

import { TopNavMenu, GlassCard, GlassButton, GlassInput, GlassPanel } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { SyncSessionDto, SyncSessionCreateBody } from '../libs/api/modules/SessionSyncApi';

/** 日志标签 */
const TAG = 'SessionSyncPage';

/** 会话同步状态类型（后端为自由字符串，宽松接收） */
type SyncStatus = string;

/** 分钟/小时/天的毫秒数常量 */
const MINUTE_MS = 60 * 1000;
const HOUR_MS = 60 * MINUTE_MS;
const DAY_MS = 24 * HOUR_MS;

// ===========================================================================
// SessionSyncViewHelper - 会话同步视图模型（纯函数，无 UI 依赖，可独立单元测试）
//
// 设计：所有方法为 static，输入 → 输出，无副作用；
//       颜色方法返回 StyleManager 的 token 名（如 'status_success'），由页面解析为实际颜色值；
//       通过本文件 export，供 ohosTest 直接导入测试
// ===========================================================================

export class SessionSyncViewHelper {
  /**
   * 获取会话同步状态对应的颜色 token 名
   * 映射：synced/active→status_success, partial→status_warning, failed→status_error,
   *       closed/ended→text_secondary；未知状态回落 status_warning
   * @param status 同步状态（后端自由字符串）
   * @return StyleManager 颜色 token 名
   */
  static getStatusColor(status: SyncStatus): string {
    if (status === 'synced' || status === 'active') return 'status_success';
    if (status === 'partial') return 'status_warning';
    if (status === 'failed') return 'status_error';
    if (status === 'closed' || status === 'ended') return 'text_secondary';
    return 'status_warning';
  }

  /**
   * 获取会话同步状态对应的图标 emoji
   * 映射：synced/active→✅, partial→⚠️, failed→❌, closed/ended→⏹️；未知→⚠️
   * @param status 同步状态（后端自由字符串）
   * @return emoji 字符串
   */
  static getStatusIcon(status: SyncStatus): string {
    if (status === 'synced' || status === 'active') return '✅';
    if (status === 'partial') return '⚠️';
    if (status === 'failed') return '❌';
    if (status === 'closed' || status === 'ended') return '⏹️';
    return '⚠️';
  }

  /**
   * 获取会话同步状态对应的中文标签
   * 映射：synced→已同步, active→进行中, partial→部分同步, failed→同步失败,
   *       closed/ended→已结束；未知→原样展示
   * @param status 同步状态（后端自由字符串）
   * @return 中文标签
   */
  static getStatusLabel(status: SyncStatus): string {
    if (status === 'synced') return '已同步';
    if (status === 'active') return '进行中';
    if (status === 'partial') return '部分同步';
    if (status === 'failed') return '同步失败';
    if (status === 'closed' || status === 'ended') return '已结束';
    return status;
  }

  /**
   * 格式化消息数为文案
   * 规则：
   *   - count ≤ 0 → "无消息"
   *   - 1 ≤ count ≤ 999 → "{count}条"
   *   - count ≥ 1000 → "999+条"（封顶显示）
   * @param count 消息数量
   * @return 消息数文案
   */
  static formatMessageCount(count: number): string {
    if (count <= 0) return '无消息';
    if (count >= 1000) return '999+条';
    return `${count}条`;
  }

  /**
   * 格式化 ISO 时间戳为相对时间文案
   * 规则：
   *   - 无效时间（空字符串/无法解析） → "-"
   *   - diff < 1 分钟 → "刚刚"
   *   - diff < 1 小时 → "{n}分钟前"
   *   - diff < 1 天 → "{n}小时前"
   *   - 否则 → "{n}天前"
   *   说明：未来时间视为刚刚（diff 截断为 0）
   * @param timestamp ISO 时间字符串
   * @return 相对时间文案
   */
  static formatRelativeTime(timestamp: string): string {
    if (!timestamp || timestamp.length === 0) return '-';
    const tsMs = Date.parse(timestamp);
    if (isNaN(tsMs)) return '-';
    // 未来时间视为刚刚
    const diff = Math.max(0, Date.now() - tsMs);
    if (diff < MINUTE_MS) return '刚刚';
    if (diff < HOUR_MS) return `${Math.floor(diff / MINUTE_MS)}分钟前`;
    if (diff < DAY_MS) return `${Math.floor(diff / HOUR_MS)}小时前`;
    return `${Math.floor(diff / DAY_MS)}天前`;
  }
}

/** 会话同步表单数据（新建用） */
interface SessionSyncFormData {
  sessionId: string;
  sourceChannel: string;
  targetChannel: string;
}

@Component
export struct SessionSyncPage {
  // 会话同步列表（由 API 加载，驱动列表渲染；/v1/sync/sessions 真实数据）
  @State syncs: SyncSessionDto[] = [];
  // 加载态
  @State loading: boolean = true;
  // 新建弹窗显示状态
  @State showDialog: boolean = false;
  // 表单数据（@State 嵌套属性变更整体重新赋值）
  @State formData: SessionSyncFormData = {
    sessionId: '',
    sourceChannel: '',
    targetChannel: '',
  };

  // 统一库单例
  private api = ApiFacade.getInstance();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private msg = MessageManager.getInstance();

  aboutToAppear() {
    this.loadSyncs();
  }

  /**
   * 加载会话同步列表（GET /v1/sync/sessions，按 token 主体过滤）
   * 流程：调用 api.sessionSync.list → 写入 syncs
   * 异常：记录日志并把后端原因透出；无论成败 finally 关闭 loading
   */
  private async loadSyncs(): Promise<void> {
    this.loading = true;
    try {
      const res = await this.api.sessionSync.list(undefined, undefined);
      if (res.code === 0 && res.data) {
        this.syncs = res.data.items;
      }
    } catch (e) {
      this.logger.error(TAG, '加载会话同步失败', e as Error);
      this.msg.error((e as Error).message.length > 0 ? (e as Error).message : '加载会话同步列表失败');
    } finally {
      this.loading = false;
    }
  }

  /** 打开新建弹窗，重置表单数据 */
  private openCreateDialog(): void {
    this.formData = { sessionId: '', sourceChannel: '', targetChannel: '' };
    this.showDialog = true;
  }

  /**
   * 提交新建（POST /v1/sync/sessions：agent_id + external_id + metadata）
   * 流程：组装 body → 调用 api.sessionSync.create → 成功后关闭弹窗并刷新列表
   * 异常：记录日志并把后端原因透出
   */
  private async submitCreate(): Promise<void> {
    if (!this.formData.sessionId) {
      this.msg.warning('请填写外部会话 ID');
      return;
    }
    try {
      const metadata: Record<string, Object> = {};
      metadata['source_channel'] = this.formData.sourceChannel;
      metadata['target_channel'] = this.formData.targetChannel;
      const body: SyncSessionCreateBody = {
        agent_id: 'default',
        external_id: this.formData.sessionId,
        metadata: metadata,
      };
      await this.api.sessionSync.create(body);
      this.msg.success('创建成功');
      this.showDialog = false;
      this.loadSyncs();
    } catch (e) {
      this.logger.error(TAG, '创建会话同步失败', e as Error);
      this.msg.error((e as Error).message.length > 0 ? (e as Error).message : '创建会话同步失败');
    }
  }

  /**
   * 立即同步（后端无手动触发端点——实时同步走 WS /v1/sync/ws/{session_id}，
   * api.sessionSync.trigger 会 throw 点名，这里 catch 透出原因）
   */
  private async triggerSync(item: SyncSessionDto): Promise<void> {
    try {
      await this.api.sessionSync.trigger(item.session_id);
      this.msg.success('同步成功');
      this.loadSyncs();
    } catch (e) {
      this.logger.error(TAG, '触发同步失败', e as Error);
      this.msg.error((e as Error).message.length > 0 ? (e as Error).message : '触发同步失败');
    }
  }

  /** 删除前二次确认（AlertDialog） */
  private confirmDelete(item: SyncSessionDto): void {
    AlertDialog.show({
      title: '确认删除',
      message: `确定要结束该同步会话吗？此操作不可撤销。`,
      autoCancel: true,
      alignment: DialogAlignment.Center,
      primaryButton: {
        value: '取消',
        action: () => {}
      },
      secondaryButton: {
        value: '删除',
        fontColor: this.sm.getColor('error'),
        action: () => { this.deleteSync(item.session_id); }
      }
    });
  }

  /**
   * 执行删除（DELETE /v1/sync/sessions/{id}，结束会话）
   * 流程：调用 api.sessionSync.remove → 成功后刷新列表
   * 异常：记录日志并把后端原因透出
   */
  private async deleteSync(syncId: string): Promise<void> {
    try {
      await this.api.sessionSync.remove(syncId);
      this.msg.success('删除成功');
      this.loadSyncs();
    } catch (e) {
      this.logger.error(TAG, '删除会话同步失败', e as Error);
      this.msg.error((e as Error).message.length > 0 ? (e as Error).message : '删除会话同步失败');
    }
  }

  build() {
    Stack({ alignContent: Alignment.Center }) {
      Column() {
        // 顶部导航栏：标题"会话同步" + 返回按钮 + 新建按钮（右侧插槽）
        TopNavMenu({
          title: '会话同步',
          showBack: true,
          showMenu: false,
          onBack: () => { this.router.back(); }
        }) {
          GlassButton({
            text: '新建',
            type: 'primary',
            btnSize: 'small',
            onTap: () => { this.openCreateDialog(); }
          })
        }

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
        } else if (this.syncs.length === 0) {
          Column() {
            Text('暂无会话同步记录')
              .fontSize(this.sm.getFontSize('subtitle'))
              .fontColor(this.sm.getColor('text_secondary'))
          }
          .width('100%')
          .layoutWeight(1)
          .justifyContent(FlexAlign.Center)
          .alignItems(HorizontalAlign.Center)
        } else {
          List({ space: 12 }) {
            ForEach(this.syncs, (item: SyncSessionDto) => {
              ListItem() {
                this.buildSyncCard(item)
              }
            }, (item: SyncSessionDto) => item.session_id)
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

      // 新建弹窗：内嵌 Stack 条件渲染
      if (this.showDialog) {
        this.buildCreateDialog()
      }
    }
    .width('100%')
    .height('100%')
  }

  // ===========================================================================
  // 会话同步卡片构建器
  // ===========================================================================

  /**
   * 单个会话同步卡片（真实 /v1/sync/sessions 字段）：
   * 状态徽章 + session_id/agent/conversation + 历史消息数 + 最近活动时间 + 活跃渠道 + 操作按钮
   */
  @Builder
  buildSyncCard(item: SyncSessionDto) {
    Column() {
    GlassCard() {
      Column() {
        // 上部：状态徽章（图标 + 文案 + 圆点）
        Row() {
          Text(SessionSyncViewHelper.getStatusIcon(item.status))
            .fontSize(16)
          Text(SessionSyncViewHelper.getStatusLabel(item.status))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor(SessionSyncViewHelper.getStatusColor(item.status)))
            .margin({ left: 4 })
          Row()
            .width(8)
            .height(8)
            .borderRadius(4)
            .backgroundColor(this.sm.getColor(SessionSyncViewHelper.getStatusColor(item.status)))
            .margin({ left: 6 })
        }
        .alignItems(VerticalAlign.Center)

        // 会话标识 + 归属
        Text(item.session_id)
          .fontSize(this.sm.getFontSize('subtitle'))
          .fontWeight(FontWeight.Bold)
          .fontColor(this.sm.getColor('text_primary'))
          .maxLines(2)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .margin({ top: 8 })

        Text(`Agent：${item.agent_id} · 会话：${item.conversation_id}`)
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('text_secondary'))
          .margin({ top: 4 })

        // 底部行：历史消息数 · 最近活动时间
        Row() {
          Text(SessionSyncViewHelper.formatMessageCount(item.history_size))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
          Text('·')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_disabled'))
            .margin({ left: 6, right: 6 })
          Text(`最近活动：${SessionSyncViewHelper.formatRelativeTime(item.last_activity)}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_disabled'))
        }
        .width('100%')
        .margin({ top: 8 })
        .alignItems(VerticalAlign.Center)

        // 活跃渠道（如有）
        if (item.active_channels.length > 0) {
          Text(`活跃渠道：${item.active_channels.join('、')}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_disabled'))
            .margin({ top: 4 })
        }

        // 操作按钮：立即同步/删除（右对齐）
        Row() {
          GlassButton({
            text: '立即同步',
            type: 'primary',
            btnSize: 'small',
            onTap: () => { this.triggerSync(item); }
          })
          GlassButton({
            text: '删除',
            type: 'danger',
            btnSize: 'small',
            onTap: () => { this.confirmDelete(item); }
          })
            .margin({ left: this.sm.getSpacing('sm') })
        }
        .width('100%')
        .justifyContent(FlexAlign.End)
        .margin({ top: this.sm.getSpacing('md') })
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
    }
    .width('100%')
  }

  // ===========================================================================
  // 新建弹窗构建器
  // ===========================================================================

  /** 新建会话同步弹窗：sessionId + sourceChannel + targetChannel */
  @Builder
  buildCreateDialog() {
    Stack({ alignContent: Alignment.Center }) {
      // 背景遮罩层：点击空白处关闭
      Column()
        .width('100%')
        .height('100%')
        .backgroundColor(this.sm.getColor('overlay_mask'))
        .onClick(() => { this.showDialog = false; })

      // 面板层：居中展示
      Column() {
      GlassPanel({ variant: 'elevated', innerPadding: 20 }) {
        Column() {
          Text('新建会话同步')
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontWeight(FontWeight.Bold)
            .fontColor(this.sm.getColor('text_primary'))
            .width('100%')

          // 会话 ID
          Text('会话 ID')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .width('100%')
            .margin({ top: this.sm.getSpacing('sm') })
          GlassInput({
            placeholder: '请输入会话 ID',
            value: this.formData.sessionId,
            type: 'text',
            onChange: (v: string) => { this.formData = { sessionId: v, sourceChannel: this.formData.sourceChannel, targetChannel: this.formData.targetChannel }; }
          })
            .margin({ top: 4 })

          // 源渠道
          Text('源渠道')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .width('100%')
            .margin({ top: this.sm.getSpacing('sm') })
          GlassInput({
            placeholder: '如 feishu',
            value: this.formData.sourceChannel,
            type: 'text',
            onChange: (v: string) => { this.formData = { sessionId: this.formData.sessionId, sourceChannel: v, targetChannel: this.formData.targetChannel }; }
          })
            .margin({ top: 4 })

          // 目标渠道
          Text('目标渠道')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .width('100%')
            .margin({ top: this.sm.getSpacing('sm') })
          GlassInput({
            placeholder: '如 dingtalk',
            value: this.formData.targetChannel,
            type: 'text',
            onChange: (v: string) => { this.formData = { sessionId: this.formData.sessionId, sourceChannel: this.formData.sourceChannel, targetChannel: v }; }
          })
            .margin({ top: 4 })

          // 操作按钮
          Row() {
            GlassButton({
              text: '取消',
              type: 'default',
              btnSize: 'medium',
              onTap: () => { this.showDialog = false; }
            })
            GlassButton({
              text: '创建',
              type: 'primary',
              btnSize: 'medium',
              onTap: () => { this.submitCreate(); }
            })
              .margin({ left: this.sm.getSpacing('sm') })
          }
          .width('100%')
          .justifyContent(FlexAlign.End)
          .margin({ top: this.sm.getSpacing('md') })
        }
        .width('100%')
        .alignItems(HorizontalAlign.Start)
      }
      }
      .width('90%')
    }
    .width('100%')
    .height('100%')
  }
}
