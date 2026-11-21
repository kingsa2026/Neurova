/**
 * CollaborationRoomPage - 协作房间页（M13 移动端功能对等）
 *
 * 职责：房间消息流 + 蜂群系统卡片（审批/升级/候选）+ 群主/管理员裁决与升级
 *   处置入口 + 待裁决角标 + 房间发言。与 PC 端 CollaborationRoomPage 同一
 *   套后端契约（collaboration_room_api.py @ /v1/collaboration/rooms）。
 *
 * 设计：
 *   - 数据面走 REST（房间信息/消息历史/待裁决读数），10s 轮询保持新鲜——
 *     移动端房间 v1 不接 session-sync WS（移动 WS 为配对通道，房间会话事件
 *     接入另批）；轮询即得审批/升级/候选卡与处置状态。
 *   - 蜂群卡片判定权与 PC 同口径：平台 admin 或房间群主（room.owner）。
 *   - 升级处置复用既有编排单源：steer=updateSubagent 注入、cancel=cancelRun。
 *   - ForEach key 含 status（裁决后本地改状态触发重渲染）；消息数组整体替换
 *     （不可变更新）。
 *
 * 依赖：../components/glass、../libs/api/ApiFacade、../libs/api/modules/CollaborationApi
 *   （RoomInfoDto/RoomMessageDto/SwarmPendingDto）、../routing/Router、
 *   ../libs/style/StyleManager、../libs/logger/Logger、../libs/message/MessageManager、
 *   ../libs/state/stores/AuthStore
 */

import { TopNavMenu, GlassCard, GlassButton } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import {
  RoomInfoDto,
  RoomMessageDto,
  SwarmPendingDto,
} from '../libs/api/modules/CollaborationApi';
import { ApiResponse } from '../libs/types';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { AuthStore } from '../libs/state/stores/AuthStore';

/** 日志标签 */
const TAG = 'CollaborationRoomPage';

/** 消息历史拉取条数（与 PC 端默认一致） */
const MESSAGE_LIMIT = 200;

/** 轮询间隔（毫秒）：消息/待裁决读数保活 */
const POLL_INTERVAL_MS = 10000;

/** 蜂群卡片种类词表（与后端 ROOM_MSG_KIND_* 对齐） */
const KIND_APPROVAL = 'swarm_approval';
const KIND_ESCALATE = 'swarm_escalate';
const KIND_CANDIDATE = 'swarm_candidate';
const KIND_COLLAB = 'swarm_collab';

// ===========================================================================
// CollaborationRoomViewHelper - 纯视图模型（static，无 UI 依赖，可独立单测）
// ===========================================================================

export class CollaborationRoomViewHelper {
  /** 蜂群卡是否为系统卡片（sender_type=system 且 kind 在词表内） */
  static isSwarmCard(msg: RoomMessageDto): boolean {
    if (msg.sender_type !== 'system') return false;
    return msg.kind === KIND_APPROVAL || msg.kind === KIND_ESCALATE
      || msg.kind === KIND_CANDIDATE || msg.kind === KIND_COLLAB;
  }

  /** 卡片状态徽章颜色 token：绿=生效/合入，红=拒绝/冲突，橙=待修订，蓝=在途 */
  static getStatusColor(status: string): string {
    if (status === 'approved' || status === 'merged') return 'success';
    if (status === 'rejected' || status === 'conflict') return 'error';
    if (status === 'reviseRequired') return 'warning';
    return 'info';
  }

  /** 审批卡可操作：无状态或状态不在终态（approved/rejected） */
  static isApprovalActionable(msg: RoomMessageDto): boolean {
    return msg.kind === KIND_APPROVAL && msg.request_id !== ''
      && msg.status !== 'approved' && msg.status !== 'rejected';
  }

  /** 候选卡可操作：submitted 态 */
  static isCandidateActionable(msg: RoomMessageDto): boolean {
    return msg.kind === KIND_CANDIDATE && msg.candidate_id !== '' && msg.status === 'submitted';
  }

  /** 升级卡可处置：未 resolved（resolved 只读） */
  static isEscalationActionable(msg: RoomMessageDto): boolean {
    return msg.kind === KIND_ESCALATE && msg.subagent_id !== '' && msg.status !== 'resolved';
  }

  /** 卡片种类中文标签 */
  static getKindLabel(msg: RoomMessageDto): string {
    if (msg.kind === KIND_APPROVAL) return '审批请求';
    if (msg.kind === KIND_ESCALATE) return '升级';
    if (msg.kind === KIND_CANDIDATE) return '结果候选';
    if (msg.kind === KIND_COLLAB) return '协作';
    return '系统';
  }

  /** 卡片种类徽章颜色 token */
  static getKindColor(msg: RoomMessageDto): string {
    if (msg.kind === KIND_APPROVAL) return 'warning';
    if (msg.kind === KIND_ESCALATE) return 'error';
    if (msg.kind === KIND_CANDIDATE) return 'info';
    return 'primary';
  }

  /** 时间戳格式化（秒级 epoch 或 ISO 均可；无效回落空串） */
  static formatTimestamp(ts: string): string {
    if (ts === '') return '';
    const n = Number(ts);
    const d = isNaN(n) || n <= 0 ? new Date(ts) : new Date(n * 1000);
    if (isNaN(d.getTime())) return '';
    const hh = d.getHours().toString().padStart(2, '0');
    const mm = d.getMinutes().toString().padStart(2, '0');
    return `${d.getMonth() + 1}/${d.getDate()} ${hh}:${mm}`;
  }
}

/** 消息列表项的渲染键（id + 状态：裁决后本地改状态触发重渲染） */
function messageKey(msg: RoomMessageDto): string {
  return `${msg.id}#${msg.status}`;
}

@Component
export struct CollaborationRoomPage {
  @State roomId: string = '';
  @State roomName: string = '协作房间';
  @State owner: string = '';
  @State messages: RoomMessageDto[] = [];
  @State loading: boolean = true;
  @State sending: boolean = false;
  @State draft: string = '';
  @State pendingApprovals: string[] = [];
  @State pendingCandidates: string[] = [];
  @State errorText: string = '';
  /** 处置备注草稿（key=rid / esc:sid / cid；点击时读取，无需驱动渲染） */
  private noteDrafts: Record<string, string> = {};
  private pollTimer: number = -1;

  private api = ApiFacade.getInstance();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private msg = MessageManager.getInstance();
  private auth: AuthStore = new AuthStore();

  aboutToAppear() {
    const params = this.router.getCurrentParam() as Record<string, Object> | undefined;
    if (params !== undefined) {
      this.roomId = String(params['roomId'] ?? '');
      const name = String(params['roomName'] ?? '');
      if (name !== '') this.roomName = name;
    }
    if (this.roomId === '') {
      this.errorText = '缺少房间标识（请从协作历史进入）';
      this.loading = false;
      return;
    }
    this.loadAll();
    this.pollTimer = setInterval(() => { this.loadMessages(true); }, POLL_INTERVAL_MS);
  }

  aboutToDisappear() {
    if (this.pollTimer !== -1) {
      clearInterval(this.pollTimer);
      this.pollTimer = -1;
    }
  }

  /** 判定权 = 平台 admin 或房间群主（与 PC/后端同口径） */
  private canDecide(): boolean {
    const user = this.auth.user;
    if (user === undefined) return false;
    return user.role === 'admin' || (this.owner !== '' && user.id === this.owner);
  }

  /** 全量加载：房间信息 + 消息 + 待裁决读数 */
  private loadAll(): void {
    this.loadRoom();
    this.loadMessages(false);
  }

  private loadRoom(): void {
    this.api.collaboration.getRoom(this.roomId)
      .then((res: ApiResponse<RoomInfoDto>) => {
        if (res.code === 0 && res.data) {
          this.owner = res.data.owner;
          if (res.data.name !== '') this.roomName = res.data.name;
        }
      })
      .catch((e: Error) => { this.logger.warn(TAG, `房间信息加载失败: ${e.message}`); });
  }

  /**
   * 拉消息 + 待裁决读数。silent=true（轮询）时不改加载态、不清错误文案，
   * 失败仅记日志——避免轮询抖动打断使用。
   */
  private loadMessages(silent: boolean): void {
    if (!silent) this.loading = true;
    this.api.collaboration.listRoomMessages(this.roomId, MESSAGE_LIMIT)
      .then((res: ApiResponse<RoomMessageDto[]>) => {
        if (res.code === 0 && res.data) {
          this.messages = res.data;
          this.errorText = '';
        } else if (!silent) {
          this.errorText = res.message || '消息加载失败';
        }
        return this.api.collaboration.getSwarmPending(this.roomId);
      })
      .then((pendingRes: ApiResponse<SwarmPendingDto>) => {
        if (pendingRes.code === 0 && pendingRes.data) {
          this.pendingApprovals = pendingRes.data.approvals;
          this.pendingCandidates = pendingRes.data.candidates;
        }
      })
      .catch((e: Error) => {
        this.logger.warn(TAG, `消息加载失败: ${e.message}`);
        if (!silent) this.errorText = '消息加载失败';
      })
      .finally(() => { if (!silent) this.loading = false; });
  }

  private sendDraft(): void {
    const text = this.draft.trim();
    if (text === '' || this.sending) return;
    this.sending = true;
    this.api.collaboration.postRoomMessage(this.roomId, text)
      .then((res: ApiResponse<Object>) => {
        if (res.code !== 0) {
          this.msg.error(res.message || '发送失败');
        } else {
          this.draft = '';
          this.loadMessages(true);
        }
      })
      .catch((e: Error) => { this.msg.error('发送失败'); this.logger.warn(TAG, `发言失败: ${e.message}`); })
      .finally(() => { this.sending = false; });
  }

  /** 审批判定：成功后本地即改卡状态（不空等下轮轮询）+ 刷新待裁决读数 */
  private decideApproval(msg: RoomMessageDto, decision: string): void {
    const rid = msg.request_id;
    if (rid === '') return;
    const note = this.noteDrafts[rid] ?? '';
    this.api.collaboration.decideRoomApproval(this.roomId, rid, decision, note)
      .then((res: ApiResponse<Object>) => {
        if (res.code !== 0) { this.msg.error(res.message || '操作失败'); return; }
        this.updateMessageStatus(msg.id, decision === 'approve' ? 'approved' : 'rejected');
        this.loadMessages(true);
        this.msg.success('操作成功');
      })
      .catch((e: Error) => { this.msg.error('操作失败'); this.logger.warn(TAG, `审批判定失败: ${e.message}`); });
  }

  /** 候选处置：intercept→rejected / merge→merged */
  private actCandidate(msg: RoomMessageDto, action: string): void {
    const cid = msg.candidate_id;
    if (cid === '') return;
    this.api.collaboration.roomCandidateAction(this.roomId, cid, action)
      .then((res: ApiResponse<Object>) => {
        if (res.code !== 0) { this.msg.error(res.message || '操作失败'); return; }
        this.updateMessageStatus(msg.id, action === 'merge' ? 'merged' : 'rejected');
        this.loadMessages(true);
        this.msg.success('操作成功');
      })
      .catch((e: Error) => { this.msg.error('操作失败'); this.logger.warn(TAG, `候选处置失败: ${e.message}`); });
  }

  /** 升级处置：steer（注入指示，必填）/ cancel（叫停） */
  private resolveEscalation(msg: RoomMessageDto, action: string): void {
    const sid = msg.subagent_id;
    if (sid === '') return;
    const note = (this.noteDrafts[`esc:${sid}`] ?? '').trim();
    if (action === 'steer' && note === '') {
      this.msg.error('注入指示必须填写内容');
      return;
    }
    this.api.collaboration.resolveRoomEscalation(this.roomId, sid, action, note)
      .then((res: ApiResponse<Object>) => {
        if (res.code !== 0) { this.msg.error(res.message || '操作失败'); return; }
        this.updateMessageStatus(msg.id, 'resolved');
        this.loadMessages(true);
        this.msg.success('操作成功');
      })
      .catch((e: Error) => { this.msg.error('操作失败'); this.logger.warn(TAG, `升级处置失败: ${e.message}`); });
  }

  /** 本地改一条消息的状态（不可变替换，触发 ForEach 重渲染） */
  private updateMessageStatus(messageId: string, status: string): void {
    const next: RoomMessageDto[] = [];
    for (const m of this.messages) {
      if (m.id === messageId) {
        const updated: RoomMessageDto = {
          id: m.id, sender_type: m.sender_type, sender_id: m.sender_id,
          content: m.content, kind: m.kind, status: status, level: m.level,
          request_id: m.request_id, candidate_id: m.candidate_id,
          subagent_id: m.subagent_id, agent_name: m.agent_name,
        };
        next.push(updated);
      } else {
        next.push(m);
      }
    }
    this.messages = next;
  }

  build() {
    Column() {
      TopNavMenu({
        title: this.roomName,
        showBack: true,
        showMenu: false,
        onBack: () => { this.router.back(); }
      })

      // 待裁决角标（审批/候选）
      if (this.pendingApprovals.length > 0 || this.pendingCandidates.length > 0) {
        Row({ space: 8 }) {
          if (this.pendingApprovals.length > 0) {
            Text(`待裁决审批 ${this.pendingApprovals.length}`)
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_on_primary'))
              .backgroundColor(this.sm.getColor('warning'))
              .padding({ left: 10, right: 10, top: 4, bottom: 4 })
              .borderRadius(12)
          }
          if (this.pendingCandidates.length > 0) {
            Text(`待处置候选 ${this.pendingCandidates.length}`)
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_on_primary'))
              .backgroundColor(this.sm.getColor('info'))
              .padding({ left: 10, right: 10, top: 4, bottom: 4 })
              .borderRadius(12)
          }
        }
        .width('100%')
        .padding({ left: this.sm.getSpacing('md'), right: this.sm.getSpacing('md'), top: 6, bottom: 6 })
      }

      if (this.errorText !== '') {
        Text(this.errorText)
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('error'))
          .width('100%')
          .textAlign(TextAlign.Center)
          .padding(8)
      }

      // 消息流
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
      } else if (this.messages.length === 0) {
        Column() {
          Text('暂无消息')
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontColor(this.sm.getColor('text_secondary'))
        }
        .width('100%')
        .layoutWeight(1)
        .justifyContent(FlexAlign.Center)
        .alignItems(HorizontalAlign.Center)
      } else {
        List({ space: 10 }) {
          ForEach(this.messages, (msg: RoomMessageDto) => {
            ListItem() {
              this.buildMessageRow(msg)
            }
          }, (msg: RoomMessageDto) => messageKey(msg))
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

      // 发言输入行
      Row({ space: 8 }) {
        TextInput({ text: this.draft, placeholder: '说点什么…' })
          .fontSize(this.sm.getFontSize('body'))
          .layoutWeight(1)
          .onChange((value: string) => { this.draft = value; })
          .onSubmit(() => { this.sendDraft(); })
        GlassButton({
          text: '发送',
          type: 'primary',
          btnSize: 'small',
          onTap: () => { this.sendDraft(); }
        })
      }
      .width('100%')
      .padding({
        left: this.sm.getSpacing('md'),
        right: this.sm.getSpacing('md'),
        top: this.sm.getSpacing('sm'),
        bottom: this.sm.getSpacing('sm'),
      })
    }
    .width('100%')
    .height('100%')
    .backgroundColor(this.sm.getColor('background'))
  }

  // ===========================================================================
  // 消息行构建器（普通气泡 / 蜂群系统卡片）
  // ===========================================================================

  @Builder
  buildMessageRow(msg: RoomMessageDto) {
    if (CollaborationRoomViewHelper.isSwarmCard(msg)) {
      this.buildSwarmCard(msg)
    } else {
      this.buildBubble(msg)
    }
  }

  @Builder
  buildBubble(msg: RoomMessageDto) {
    Row() {
      Blank().layoutWeight(msg.sender_type === 'user' ? 2 : 0)
      Column() {
        if (msg.sender_type === 'agent' && msg.sender_id !== '') {
          Text(msg.sender_id)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_disabled'))
        }
        Text(msg.content)
          .fontSize(this.sm.getFontSize('body'))
          .fontColor(this.sm.getColor('text_primary'))
      }
      .alignItems(HorizontalAlign.Start)
      .padding(10)
      .borderRadius(this.sm.getRadius('md'))
      .backgroundColor(this.sm.getColor(msg.sender_type === 'user' ? 'primary' : 'surface'))
      .constraintSize({ maxWidth: '80%' })
      Blank().layoutWeight(msg.sender_type === 'user' ? 0 : 2)
    }
    .width('100%')
  }

  @Builder
  buildSwarmCard(msg: RoomMessageDto) {
    Row() {
      Blank().layoutWeight(1)
      Column() {
        // 头部：种类徽章 + 级别 + 状态
        Row({ space: 6 }) {
          Text(CollaborationRoomViewHelper.getKindLabel(msg))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_on_primary'))
            .backgroundColor(this.sm.getColor(CollaborationRoomViewHelper.getKindColor(msg)))
            .padding({ left: 6, right: 6, top: 2, bottom: 2 })
            .borderRadius(this.sm.getRadius('sm'))
          if (msg.level !== '') {
            Text(msg.level)
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
          }
          if (msg.status !== '') {
            Text(msg.status)
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_on_primary'))
              .backgroundColor(this.sm.getColor(CollaborationRoomViewHelper.getStatusColor(msg.status)))
              .padding({ left: 6, right: 6, top: 2, bottom: 2 })
              .borderRadius(this.sm.getRadius('sm'))
          }
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)

        Text(msg.content)
          .fontSize(this.sm.getFontSize('body'))
          .fontColor(this.sm.getColor('text_primary'))
          .margin({ top: 6 })
          .width('100%')

        // 裁决/处置操作区（群主/管理员；按卡种分流）
        if (this.canDecide() && CollaborationRoomViewHelper.isApprovalActionable(msg)) {
          this.buildNoteInput(msg.request_id, '处置备注（可选）')
          Row({ space: 8 }) {
            GlassButton({ text: '批准', type: 'primary', btnSize: 'small',
              onTap: () => { this.decideApproval(msg, 'approve'); } })
            GlassButton({ text: '驳回', type: 'default', btnSize: 'small',
              onTap: () => { this.decideApproval(msg, 'reject'); } })
          }
          .width('100%')
          .justifyContent(FlexAlign.End)
          .margin({ top: 6 })
        } else if (this.canDecide() && CollaborationRoomViewHelper.isCandidateActionable(msg)) {
          Row({ space: 8 }) {
            GlassButton({ text: '拦截', type: 'default', btnSize: 'small',
              onTap: () => { this.actCandidate(msg, 'intercept'); } })
            GlassButton({ text: '采纳', type: 'primary', btnSize: 'small',
              onTap: () => { this.actCandidate(msg, 'merge'); } })
          }
          .width('100%')
          .justifyContent(FlexAlign.End)
          .margin({ top: 6 })
        } else if (this.canDecide() && CollaborationRoomViewHelper.isEscalationActionable(msg)) {
          this.buildNoteInput(`esc:${msg.subagent_id}`, '指示内容（必填）')
          Row({ space: 8 }) {
            GlassButton({ text: '注入指示', type: 'primary', btnSize: 'small',
              onTap: () => { this.resolveEscalation(msg, 'steer'); } })
            GlassButton({ text: '叫停', type: 'default', btnSize: 'small',
              onTap: () => { this.resolveEscalation(msg, 'cancel'); } })
          }
          .width('100%')
          .justifyContent(FlexAlign.End)
          .margin({ top: 6 })
        }
      }
      .alignItems(HorizontalAlign.Start)
      .padding(12)
      .borderRadius(this.sm.getRadius('md'))
      .backgroundColor(this.sm.getColor('surface'))
      .constraintSize({ maxWidth: '92%' })
    }
    .width('100%')
  }

  @Builder
  buildNoteInput(draftKey: string, placeholder: string) {
    TextInput({ text: this.noteDrafts[draftKey] ?? '', placeholder: placeholder })
      .fontSize(this.sm.getFontSize('caption'))
      .width('100%')
      .margin({ top: 6 })
      .onChange((value: string) => { this.noteDrafts[draftKey] = value; })
  }
}
