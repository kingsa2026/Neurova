/**
 * CollaborationInitiatePage - 协作发起页
 *
 * 职责：发起协作表单，选择类型（project/team/task/workflow），输入名称描述，
 *   添加参与者，展示状态徽章（pending/initiated/failed），提交后展示发起进度
 * 设计：
 *   - CollaborationInitiateViewHelper（导出）：纯视图模型，封装类型颜色/图标/文案、
 *     状态颜色、参与者数量格式化；无 UI 运行时依赖，可独立单元测试；
 *   - CollaborationInitiatePage（@Component）：Stack [主内容列] + [发起进度弹窗]
 *     主内容列：TopNavMenu(标题"发起协作"+返回) + [表单：类型选择/名称/描述/参与者输入] +
 *     [发起历史列表：展示最近发起的协作及其状态]；
 *     类型选择为胶囊按钮组；参与者通过 GlassInput 输入后回车添加为标签；
 *     提交 → 本地创建 pending 状态记录 → TODO M6 接入 API；
 *   - 颜色统一走 StyleManager，路由走 Router，API 暂无 collaboration 专用模块 →
 *     本地 mock 数据 + TODO 注释 M6 阶段补充真实 API。
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassCard、GlassButton、GlassInput、GlassPanel
 *   - ../libs/api/ApiFacade：统一 API 门面（仅作为占位，未实际调用）
 *   - ../routing/Router：统一路由跳转
 *   - ../libs/style/StyleManager：统一样式 token
 *   - ../libs/logger/Logger：统一日志
 *   - ../libs/message/MessageManager：统一消息提示
 *   - ../libs/types：CollaborationInitiate
 *
 * 用法：
 *   由 Router.push(RouteNames.COLLABORATION_INITIATE) 跳转进入；
 *   填写表单 → 点击"发起" → 本地创建 pending 记录 → TODO M6 接入真实 API；
 *   发起历史列表展示最近发起的协作及其状态徽章。
 *
 * TDD：CollaborationInitiateViewHelper 各方法按红绿灯垂直切片逐步实现，
 *      详见 CollaborationInitiatePage.test.ets
 */

import { TopNavMenu, GlassCard, GlassButton, GlassInput, GlassPanel } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { CollaborationSessionDto, CollaborationStartBody } from '../libs/api/modules/CollaborationApi';
import { Agent } from '../libs/types';
import { AdminUserDto } from '../libs/api/modules/AdminApi';

/** 日志标签 */
const TAG = 'CollaborationInitiatePage';

/** 协作状态别名（发起进度弹窗用：等待/成功/失败） */
type CollabStatus = 'pending' | 'initiated' | 'failed';

// ===========================================================================
// CollaborationInitiateViewHelper - 协作发起视图模型（纯函数，无 UI 依赖，可独立单元测试）
//
// 设计：所有方法为 static，输入 → 输出，无副作用；
//       颜色方法返回 StyleManager 的 token 名（如 'primary'），由页面解析为实际颜色值；
//       图标方法返回 emoji 字符串直接渲染；
//       通过本文件 export，供 ohosTest 直接导入测试
// ===========================================================================

export class CollaborationInitiateViewHelper {
  /**
   * 获取协作会话状态对应的颜色 token 名（后端 project status 词汇）
   * 映射：active→success，archived→warning，suspended→error，其他→info
   * @param status 协作会话状态字符串
   * @return StyleManager 颜色 token 名
   */
  static getSessionStatusColor(status: string): string {
    if (status === 'active') return 'success';
    if (status === 'archived') return 'warning';
    if (status === 'suspended') return 'error';
    return 'info';
  }

  /**
   * 获取协作会话状态对应的中文标签
   * 映射：active→进行中，archived→已归档，suspended→已暂停，其他→未知
   * @param status 协作会话状态字符串
   * @return 中文文案
   */
  static getSessionStatusLabel(status: string): string {
    if (status === 'active') return '进行中';
    if (status === 'archived') return '已归档';
    if (status === 'suspended') return '已暂停';
    return '未知';
  }

  /**
   * 获取发起进度状态对应的颜色 token 名
   * 映射：pending→warning，initiated→success，failed→error
   * @param status 发起状态
   * @return StyleManager 颜色 token 名
   */
  static getStatusColor(status: CollabStatus): string {
    if (status === 'pending') return 'warning';
    if (status === 'initiated') return 'success';
    if (status === 'failed') return 'error';
    throw new Error(`getStatusColor 未实现: ${status}`);
  }

  /**
   * 格式化参与者数量为展示字符串
   * 规则：0 → "无参与者"；1 → "1 人"；N → "N 人"
   * @param count 参与者数量
   * @return 参与者数量展示字符串
   */
  static formatParticipantsCount(count: number): string {
    if (count === 0) return '无参与者';
    return `${count} 人`;
  }
}

/** 发起表单数据 */
interface InitiateFormData {
  name: string;
  description: string;
  participants: string[];     // userId 或 agentId 列表
  participantInput: string;  // 当前输入中的参与者
}

/** 默认表单数据 */
const DEFAULT_FORM: InitiateFormData = {
  name: '',
  description: '',
  participants: [],
  participantInput: '',
};

/** 默认表单工厂（ArkTS 禁 spread 复制，集中此处） */
function defaultForm(): InitiateFormData {
  const form: InitiateFormData = {
    name: '',
    description: '',
    participants: [],
    participantInput: '',
  };
  return form;
}

/** 发起进度弹窗状态 */
interface ProgressState {
  visible: boolean;
  status: CollabStatus;
  message: string;
}

@Component
export struct CollaborationInitiatePage {
  // 发起表单数据（嵌套属性变更需整体重新赋值）
  @State formData: InitiateFormData = defaultForm();
  // 已发起的协作会话列表（真实 DTO：GET /v1/collaboration/sessions）
  @State initiated: CollaborationSessionDto[] = [];
  // 发起进度弹窗
  @State progress: ProgressState = {
    visible: false,
    status: 'pending',
    message: '',
  };
  // 参与者选择：类型（用户 / Agent 单选）+ 现有候选（下拉）+ 当前选中
  @State participantKind: string = 'agent';
  @State agents: Agent[] = [];
  @State users: AdminUserDto[] = [];
  @State selectedParticipantId: string = '';

  // 统一库单例
  private api = ApiFacade.getInstance();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private msg = MessageManager.getInstance();

  aboutToAppear() {
    this.loadInitiated();
    this.loadParticipantCandidates();
  }

  /** 加载参与者候选：现有 Agent（按账号）+ 用户列表（非管理员可能 403，诚实降级为空） */
  private async loadParticipantCandidates(): Promise<void> {
    try {
      this.agents = await this.api.agents.list();
    } catch (e) {
      this.logger.error(TAG, 'Agent 候选加载失败', e as Error);
    }
    try {
      const res = await this.api.admin.listUsers();
      this.users = res.items;
    } catch (e) {
      this.logger.error(TAG, '用户候选加载失败（需要管理员权限）', e as Error);
    }
  }

  /** 参与者下拉选项（随类型切换：Agent 名 / 用户名） */
  private participantOptions(): SelectOption[] {
    const out: SelectOption[] = [];
    if (this.participantKind === 'user') {
      for (const u of this.users) {
        const so: SelectOption = { value: u.username };
        out.push(so);
      }
      return out;
    }
    for (const a of this.agents) {
      const so: SelectOption = { value: a.name };
      out.push(so);
    }
    return out;
  }

  /** 参与者下拉选项对应的 ID（与 participantOptions 同序） */
  private participantOptionIds(): string[] {
    const out: string[] = [];
    if (this.participantKind === 'user') {
      for (const u of this.users) {
        out.push(String(u.id));
      }
      return out;
    }
    for (const a of this.agents) {
      out.push(a.id);
    }
    return out;
  }

  /** 当前选中下标（未选择返回 0，展示占位文案） */
  private selectedParticipantIndex(): number {
    const ids = this.participantOptionIds();
    for (let i = 0; i < ids.length; i++) {
      if (ids[i] === this.selectedParticipantId) {
        return i;
      }
    }
    return 0;
  }

  /** 下拉框展示文案（未选择时为占位提示） */
  private selectedParticipantLabel(): string {
    if (this.selectedParticipantId === '') {
      return '请选择参与者';
    }
    const ids = this.participantOptionIds();
    const opts = this.participantOptions();
    for (let i = 0; i < ids.length; i++) {
      if (ids[i] === this.selectedParticipantId && i < opts.length) {
        return opts[i].value as string;
      }
    }
    return '请选择参与者';
  }

  /** 把下拉选中的参与者加入列表 */
  private addSelectedParticipant(): void {
    if (this.selectedParticipantId === '') {
      this.msg.warning('请先在下拉菜单选择参与者');
      return;
    }
    if (this.formData.participants.includes(this.selectedParticipantId)) {
      this.msg.warning('参与者已存在');
      return;
    }
    const next = this.formData.participants.slice();
    next.push(this.selectedParticipantId);
    this.formData = { name: this.formData.name, description: this.formData.description, participants: next, participantInput: '' };
    this.selectedParticipantId = '';
  }

  /**
   * 加载已发起的协作列表（真实 API：GET /v1/collaboration/sessions，P1-34）
   */
  private async loadInitiated(): Promise<void> {
    try {
      const res = await this.api.collaboration.listSessions(50, 0);
      if (res.code === 0 && res.data) {
        this.initiated = res.data;
      } else {
        this.msg.error(res.message || '加载发起列表失败');
      }
    } catch (e) {
      this.logger.error(TAG, '加载发起列表失败', e as Error);
    }
  }

  /** 输入名称（嵌套属性变更：整体重新赋值） */
  private inputName(v: string): void {
    this.formData = { name: v, description: this.formData.description, participants: this.formData.participants, participantInput: this.formData.participantInput };
  }

  /** 输入描述（嵌套属性变更：整体重新赋值） */
  private inputDescription(v: string): void {
    this.formData = { name: this.formData.name, description: v, participants: this.formData.participants, participantInput: this.formData.participantInput };
  }

  /** 移除参与者（嵌套属性变更：整体重新赋值） */
  private removeParticipant(p: string): void {
    const next = this.formData.participants.filter((x: string) => x !== p);
    this.formData = { name: this.formData.name, description: this.formData.description, participants: next, participantInput: this.formData.participantInput };
  }

  /**
   * 提交发起协作（真实 API：POST /v1/collaboration/start，P1-34）
   * 名称/描述放 context 随 participants 一起提交，结果由服务端落库。
   */
  private async submitInitiate(): Promise<void> {
    if (!this.formData.name.trim()) {
      this.msg.warning('请填写协作名称');
      return;
    }
    // 显示发起进度弹窗（pending 状态）
    this.progress = {
      visible: true,
      status: 'pending',
      message: '正在发起协作...',
    };
    try {
      const context: Record<string, Object> = {
        'name': this.formData.name.trim(),
        'description': this.formData.description.trim(),
      };
      const body: CollaborationStartBody = {
        participants: this.formData.participants.slice(),
        context: context,
      };
      const res = await this.api.collaboration.startCollaboration(body);
      if (res.code === 0) {
        // 更新进度弹窗为成功，并刷新真实列表
        this.progress = {
          visible: true,
          status: 'initiated',
          message: '协作已成功发起',
        };
        await this.loadInitiated();
      } else {
        this.progress = {
          visible: true,
          status: 'failed',
          message: res.message || '发起协作失败',
        };
      }
    } catch (e) {
      this.logger.error(TAG, '发起协作失败', e as Error);
      this.progress = {
        visible: true,
        status: 'failed',
        message: '发起协作失败',
      };
    }
  }

  /** 关闭进度弹窗并重置表单 */
  private closeProgress(): void {
    if (this.progress.status === 'initiated') {
      // 成功后重置表单
      this.formData = defaultForm();
    }
    const next: ProgressState = { visible: false, status: this.progress.status, message: this.progress.message };
    this.progress = next;
  }

  build() {
    Stack() {
      Column() {
        // 顶部导航栏：标题"发起协作" + 返回
        TopNavMenu({
          title: '发起协作',
          showBack: true,
          showMenu: false,
          onBack: () => { this.router.back(); }
        })

        // 主体内容：表单 + 发起历史列表
        Scroll() {
          Column() {
            // 表单区域
            this.buildForm()

            // 发起历史列表
            Text('最近发起')
              .fontSize(this.sm.getFontSize('subtitle'))
              .fontWeight(FontWeight.Bold)
              .fontColor(this.sm.getColor('text_primary'))
              .width('100%')
              .margin({ top: this.sm.getSpacing('lg'), bottom: this.sm.getSpacing('sm') })

            if (this.initiated.length === 0) {
              Text('暂无发起记录')
                .fontSize(this.sm.getFontSize('body'))
                .fontColor(this.sm.getColor('text_secondary'))
                .width('100%')
                .textAlign(TextAlign.Center)
                .padding({ top: this.sm.getSpacing('lg'), bottom: this.sm.getSpacing('lg') })
            } else {
              ForEach(this.initiated, (item: CollaborationSessionDto) => {
                this.buildInitiatedCard(item)
              }, (item: CollaborationSessionDto) => item.id)
            }
          }
          .width('100%')
          .padding({
            left: this.sm.getSpacing('md'),
            right: this.sm.getSpacing('md'),
            top: this.sm.getSpacing('sm'),
            bottom: this.sm.getSpacing('lg'),
          })
        }
        .layoutWeight(1)
        .scrollBar(BarState.Off)
      }
      .width('100%')
      .height('100%')
      .backgroundColor(this.sm.getColor('background'))

      // 发起进度弹窗
      if (this.progress.visible) {
        this.buildProgressDialog()
      }
    }
    .width('100%')
    .height('100%')
  }

  // ===========================================================================
  // 表单构建器
  // ===========================================================================

  /** 发起表单：名称 + 描述 + 参与者 + 提交按钮（后端 /collaboration/start 无类型维度） */
  @Builder
  buildForm() {
    Column() {
    GlassCard() {
      Column() {
        // 名称输入
        Text('协作名称')
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('text_secondary'))
          .width('100%')
        GlassInput({
          placeholder: '请输入协作名称',
          value: this.formData.name,
          type: 'text',
          onChange: (v: string) => { this.inputName(v); },
        })
          .margin({ top: 4, bottom: this.sm.getSpacing('sm') })

        // 描述输入
        Text('描述（可选）')
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('text_secondary'))
          .width('100%')
        GlassInput({
          placeholder: '请输入描述',
          value: this.formData.description,
          type: 'text',
          onChange: (v: string) => { this.inputDescription(v); },
        })
          .margin({ top: 4, bottom: this.sm.getSpacing('sm') })

        // 参与者：类型单选（用户 / Agent）+ 按类型下拉选现有用户/Agent
        Text('参与者类型')
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('text_secondary'))
          .width('100%')
        Row({ space: 8 }) {
          Text('Agent')
            .fontSize(this.sm.getFontSize('body_sm'))
            .fontColor(this.participantKind === 'agent'
              ? this.sm.getColor('text_on_primary')
              : this.sm.getColor('text_secondary'))
            .backgroundColor(this.participantKind === 'agent'
              ? this.sm.getColor('primary')
              : this.sm.getColor('surface'))
            .padding({ left: 14, right: 14, top: 6, bottom: 6 })
            .borderRadius(14)
            .onClick(() => {
              this.participantKind = 'agent';
              this.selectedParticipantId = '';
            })
          Text('用户')
            .fontSize(this.sm.getFontSize('body_sm'))
            .fontColor(this.participantKind === 'user'
              ? this.sm.getColor('text_on_primary')
              : this.sm.getColor('text_secondary'))
            .backgroundColor(this.participantKind === 'user'
              ? this.sm.getColor('primary')
              : this.sm.getColor('surface'))
            .padding({ left: 14, right: 14, top: 6, bottom: 6 })
            .borderRadius(14)
            .onClick(() => {
              this.participantKind = 'user';
              this.selectedParticipantId = '';
            })
        }
        .width('100%')
        .margin({ top: 4 })

        Text('选择参与者')
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('text_secondary'))
          .width('100%')
          .margin({ top: this.sm.getSpacing('xs') })
        Select(this.participantOptions())
          .selected(this.selectedParticipantIndex())
          .value(this.selectedParticipantLabel())
          .font({ size: this.sm.getFontSize('body_sm') })
          .fontColor(this.sm.getColor('text_primary'))
          .selectedOptionFont({ size: this.sm.getFontSize('body_sm') })
          .optionFont({ size: this.sm.getFontSize('body_sm') })
          .width('100%')
          .margin({ top: 4 })
          .onSelect((index: number) => {
            const ids = this.participantOptionIds();
            if (index >= 0 && index < ids.length) {
              this.selectedParticipantId = ids[index];
            }
          })

        Row() {
          GlassButton({
            text: '添加',
            type: 'default',
            btnSize: 'small',
            onTap: () => { this.addSelectedParticipant(); }
          })
        }
        .width('100%')
        .margin({ top: 4 })

        // 参与者列表
        Text(CollaborationInitiateViewHelper.formatParticipantsCount(this.formData.participants.length))
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('text_disabled'))
          .width('100%')
          .margin({ top: this.sm.getSpacing('xs') })

        if (this.formData.participants.length > 0) {
          // 参与者标签
          Flex({ wrap: FlexWrap.Wrap }) {
            ForEach(this.formData.participants, (p: string) => {
              Row() {
                Text(p)
                  .fontSize(this.sm.getFontSize('caption'))
                  .fontColor(this.sm.getColor('text_primary'))
                Text(' ×')
                  .fontSize(this.sm.getFontSize('caption'))
                  .fontColor(this.sm.getColor('text_secondary'))
                  .onClick(() => { this.removeParticipant(p); })
              }
              .padding({ left: 8, right: 8, top: 4, bottom: 4 })
              .borderRadius(this.sm.getRadius('sm'))
              .backgroundColor(this.sm.getColor('surface'))
              .margin({ right: this.sm.getSpacing('xs'), bottom: this.sm.getSpacing('xs') })
            }, (p: string) => p)
          }
          .width('100%')
          .margin({ top: this.sm.getSpacing('xs') })
        }

        // 提交按钮
        GlassButton({
          text: '发起协作',
          type: 'primary',
          btnSize: 'medium',
          onTap: () => { this.submitInitiate(); }
        })
          .width('100%')
          .margin({ top: this.sm.getSpacing('md') })
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
    }
    .width('100%')
  }

  // ===========================================================================
  // 发起历史卡片构建器
  // ===========================================================================

  /** 单个发起历史卡片：状态徽章 + 名称 + 参与者数 */
  @Builder
  buildInitiatedCard(item: CollaborationSessionDto) {
    Column() {
    GlassCard() {
      Column() {
        // 顶部行：名称 + 状态徽章
        Row() {
          Text('🔄')
            .fontSize(20)
          Text(item.name)
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontWeight(FontWeight.Bold)
            .fontColor(this.sm.getColor('text_primary'))
            .layoutWeight(1)
            .margin({ left: this.sm.getSpacing('sm') })
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
          // 状态徽章（后端 project status 真实词汇）
          Text(CollaborationInitiateViewHelper.getSessionStatusLabel(item.status))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor(CollaborationInitiateViewHelper.getSessionStatusColor(item.status)))
            .padding({ left: 6, right: 6, top: 2, bottom: 2 })
            .borderRadius(this.sm.getRadius('sm'))
            .backgroundColor(this.sm.getColor('surface'))
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)

        // 描述（如有）
        if (item.description) {
          Text(item.description)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .maxLines(2)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
            .margin({ top: this.sm.getSpacing('xs') })
            .width('100%')
        }

        // 参与者数量（成员来自真实会话 members）
        Text(CollaborationInitiateViewHelper.formatParticipantsCount(item.members.length))
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('text_disabled'))
          .margin({ top: 4 })
          .width('100%')
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
    }
    .width('100%')
  }

  // ===========================================================================
  // 发起进度弹窗构建器（Stack 内嵌条件渲染）
  // ===========================================================================

  /** 发起进度弹窗：根据 status 展示 pending/initiated/failed */
  @Builder
  buildProgressDialog() {
    Stack({ alignContent: Alignment.Center }) {
      // 背景遮罩层
      Column()
        .width('100%')
        .height('100%')
        .backgroundColor(this.sm.getColor('overlay_mask'))

      // 面板层
      Column() {
      GlassPanel({ variant: 'elevated', innerPadding: 20 }) {
        Column() {
          Text('发起进度')
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontWeight(FontWeight.Bold)
            .fontColor(this.sm.getColor('text_primary'))
            .width('100%')

          Text(this.progress.message)
            .fontSize(this.sm.getFontSize('body'))
            .fontColor(this.sm.getColor(
              CollaborationInitiateViewHelper.getStatusColor(this.progress.status)))
            .width('100%')
            .margin({ top: this.sm.getSpacing('md') })
            .textAlign(TextAlign.Center)

          // pending 状态不显示关闭按钮（模拟不可中断）
          if (this.progress.status !== 'pending') {
            GlassButton({
              text: '关闭',
              type: this.progress.status === 'failed' ? 'danger' : 'primary',
              btnSize: 'medium',
              onTap: () => { this.closeProgress(); }
            })
              .width('100%')
              .margin({ top: this.sm.getSpacing('md') })
          }
        }
        .width('100%')
        .alignItems(HorizontalAlign.Center)
      }
      }
      .width('80%')
    }
    .width('100%')
    .height('100%')
  }
}
