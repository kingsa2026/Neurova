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
import { CollaborationInitiate } from '../libs/types';

/** 日志标签 */
const TAG = 'CollaborationInitiatePage';

/** 协作类型别名（与 CollaborationInitiate.type 对齐） */
type CollabType = 'project' | 'team' | 'task' | 'workflow';

/** 协作状态别名（与 CollaborationInitiate.status 对齐） */
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
   * 获取协作类型对应的颜色 token 名
   * 映射：project→primary，team→info，task→success，workflow→warning
   * @param type 协作类型
   * @return StyleManager 颜色 token 名
   */
  static getTypeColor(type: CollabType): string {
    if (type === 'project') return 'primary';
    if (type === 'team') return 'info';
    if (type === 'task') return 'success';
    if (type === 'workflow') return 'warning';
    // 未覆盖的类型抛错，强制 TDD 红灯逐项补齐
    throw new Error(`getTypeColor 未实现: ${type}`);
  }

  /**
   * 获取协作类型对应的图标 emoji
   * 映射：project→📋，team→👥，task→✅，workflow→🔄
   * @param type 协作类型
   * @return emoji 字符串
   */
  static getTypeIcon(type: CollabType): string {
    if (type === 'project') return '📋';
    if (type === 'team') return '👥';
    if (type === 'task') return '✅';
    if (type === 'workflow') return '🔄';
    throw new Error(`getTypeIcon 未实现: ${type}`);
  }

  /**
   * 获取协作类型对应的中文标签
   * 映射：project→项目，team→团队，task→任务，workflow→工作流
   * @param type 协作类型
   * @return 中文文案
   */
  static getTypeLabel(type: CollabType): string {
    if (type === 'project') return '项目';
    if (type === 'team') return '团队';
    if (type === 'task') return '任务';
    if (type === 'workflow') return '工作流';
    throw new Error(`getTypeLabel 未实现: ${type}`);
  }

  /**
   * 获取发起状态对应的颜色 token 名
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

/** 类型选项配置 */
interface TypeOption {
  value: CollabType;
  label: string;
  icon: string;
}

/** 类型选项列表 */
const TYPE_OPTIONS: TypeOption[] = [
  { value: 'project', label: '项目', icon: '📋' },
  { value: 'team', label: '团队', icon: '👥' },
  { value: 'task', label: '任务', icon: '✅' },
  { value: 'workflow', label: '工作流', icon: '🔄' },
];

/** 发起表单数据 */
interface InitiateFormData {
  type: CollabType;
  name: string;
  description: string;
  participants: string[];     // userId 或 agentId 列表
  participantInput: string;  // 当前输入中的参与者
}

/** 默认表单数据 */
const DEFAULT_FORM: InitiateFormData = {
  type: 'project',
  name: '',
  description: '',
  participants: [],
  participantInput: '',
};

/** 发起进度弹窗状态 */
interface ProgressState {
  visible: boolean;
  status: CollabStatus;
  message: string;
}

/**
 * Mock 最近发起的协作列表
 * TODO M6 阶段：替换为 api.collaboration.initiate.list() 真实 API
 */
const MOCK_INITIATED: CollaborationInitiate[] = [
  {
    id: 'init_1',
    type: 'project',
    name: 'Q1 产品规划协作',
    description: '产品、设计、研发三方协作完成 Q1 规划',
    participants: ['user_1', 'user_2', 'agent_1'],
    status: 'initiated',
    initiatedAt: '2025-03-01T10:00:00Z',
    createdAt: '2025-03-01T09:50:00Z',
  },
  {
    id: 'init_2',
    type: 'task',
    name: '紧急 bug 修复协作',
    participants: ['user_3'],
    status: 'failed',
    createdAt: '2025-03-02T14:00:00Z',
  },
];

@Component
export struct CollaborationInitiatePage {
  // 发起表单数据（嵌套属性变更需整体重新赋值）
  @State formData: InitiateFormData = { ...DEFAULT_FORM };
  // 最近发起的协作列表
  @State initiated: CollaborationInitiate[] = [];
  // 发起进度弹窗
  @State progress: ProgressState = {
    visible: false,
    status: 'pending',
    message: '',
  };

  // 统一库单例
  private api = ApiFacade.getInstance();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private msg = MessageManager.getInstance();

  aboutToAppear() {
    this.loadInitiated();
  }

  /**
   * 加载最近发起的协作列表
   * TODO M6 阶段：替换为真实 API（api.collaboration.initiate.list）
   */
  private async loadInitiated(): Promise<void> {
    try {
      // TODO M6 阶段补充真实 API
      this.initiated = MOCK_INITIATED.slice();
    } catch (e) {
      this.logger.error(TAG, '加载发起列表失败', e as Error);
    }
  }

  /** 选择类型（嵌套属性变更：整体重新赋值） */
  private selectType(type: CollabType): void {
    this.formData = { ...this.formData, type };
  }

  /** 输入名称（嵌套属性变更：整体重新赋值） */
  private inputName(v: string): void {
    this.formData = { ...this.formData, name: v };
  }

  /** 输入描述（嵌套属性变更：整体重新赋值） */
  private inputDescription(v: string): void {
    this.formData = { ...this.formData, description: v };
  }

  /** 输入参与者 ID（嵌套属性变更：整体重新赋值） */
  private inputParticipant(v: string): void {
    this.formData = { ...this.formData, participantInput: v };
  }

  /** 添加参与者（回车或点击添加按钮触发，嵌套属性变更：整体重新赋值） */
  private addParticipant(): void {
    const v = this.formData.participantInput.trim();
    if (!v) return;
    if (this.formData.participants.includes(v)) {
      this.msg.warning('参与者已存在');
      return;
    }
    this.formData = {
      ...this.formData,
      participants: [...this.formData.participants, v],
      participantInput: '',
    };
  }

  /** 移除参与者（嵌套属性变更：整体重新赋值） */
  private removeParticipant(p: string): void {
    this.formData = {
      ...this.formData,
      participants: this.formData.participants.filter((x: string) => x !== p),
    };
  }

  /**
   * 提交发起协作
   * TODO M6 阶段：调用真实 API（api.collaboration.initiate.create）
   * 当前为本地创建 pending 记录 → 模拟发起成功 → TODO 提示
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
      // TODO M6 阶段：const res = await this.api.collaboration.initiate.create(form);
      // 模拟异步发起
      const now = new Date().toISOString();
      const newInit: CollaborationInitiate = {
        id: `init_${Date.now()}`,
        type: this.formData.type,
        name: this.formData.name.trim(),
        description: this.formData.description.trim(),
        participants: this.formData.participants.slice(),
        status: 'initiated',
        initiatedAt: now,
        createdAt: now,
      };
      this.initiated = [newInit, ...this.initiated];
      // 更新进度弹窗为成功
      this.progress = {
        visible: true,
        status: 'initiated',
        message: '协作已成功发起',
      };
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
      this.formData = { ...DEFAULT_FORM };
    }
    this.progress = { ...this.progress, visible: false };
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
              ForEach(this.initiated, (item: CollaborationInitiate) => {
                this.buildInitiatedCard(item)
              }, (item: CollaborationInitiate) => item.id)
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

  /** 发起表单：类型选择 + 名称 + 描述 + 参与者 + 提交按钮 */
  @Builder
  buildForm() {
    GlassCard() {
      Column() {
        // 类型选择
        Text('协作类型')
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('text_secondary'))
          .width('100%')
        Row() {
          ForEach(TYPE_OPTIONS, (opt: TypeOption) => {
            GlassButton({
              text: `${opt.icon} ${opt.label}`,
              type: this.formData.type === opt.value ? 'primary' : 'default',
              size: 'small',
              onClick: () => { this.selectType(opt.value); }
            })
              .margin({ right: this.sm.getSpacing('xs') })
          }, (opt: TypeOption) => opt.value)
        }
        .width('100%')
        .margin({ top: this.sm.getSpacing('xs'), bottom: this.sm.getSpacing('sm') })

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

        // 参与者输入
        Text('参与者')
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('text_secondary'))
          .width('100%')
        Row() {
          GlassInput({
            placeholder: '输入 userId 或 agentId',
            value: this.formData.participantInput,
            type: 'text',
            onChange: (v: string) => { this.inputParticipant(v); },
          })
            .layoutWeight(1)
          GlassButton({
            text: '添加',
            type: 'default',
            size: 'small',
            onClick: () => { this.addParticipant(); }
          })
            .margin({ left: this.sm.getSpacing('xs') })
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
          size: 'medium',
          onClick: () => { this.submitInitiate(); }
        })
          .width('100%')
          .margin({ top: this.sm.getSpacing('md') })
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
    .width('100%')
  }

  // ===========================================================================
  // 发起历史卡片构建器
  // ===========================================================================

  /** 单个发起历史卡片：类型徽章 + 名称 + 状态徽章 + 参与者数 */
  @Builder
  buildInitiatedCard(item: CollaborationInitiate) {
    GlassCard() {
      Column() {
        // 顶部行：类型图标 + 类型徽章 + 名称 + 状态徽章
        Row() {
          Text(CollaborationInitiateViewHelper.getTypeIcon(item.type))
            .fontSize(20)
          Text(CollaborationInitiateViewHelper.getTypeLabel(item.type))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_on_primary'))
            .padding({ left: 6, right: 6, top: 2, bottom: 2 })
            .borderRadius(this.sm.getRadius('sm'))
            .backgroundColor(this.sm.getColor(CollaborationInitiateViewHelper.getTypeColor(item.type)))
            .margin({ left: this.sm.getSpacing('xs') })
          Text(item.name)
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontWeight(FontWeight.Bold)
            .fontColor(this.sm.getColor('text_primary'))
            .layoutWeight(1)
            .margin({ left: this.sm.getSpacing('sm') })
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
          // 状态徽章
          Text(item.status)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor(CollaborationInitiateViewHelper.getStatusColor(item.status)))
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

        // 参与者数量
        Text(CollaborationInitiateViewHelper.formatParticipantsCount(item.participants.length))
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('text_disabled'))
          .margin({ top: 4 })
          .width('100%')
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
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
      GlassPanel({ variant: 'elevated', padding: 20 }) {
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
              size: 'medium',
              onClick: () => { this.closeProgress(); }
            })
              .width('100%')
              .margin({ top: this.sm.getSpacing('md') })
          }
        }
        .width('100%')
        .alignItems(HorizontalAlign.Center)
      }
      .width('80%')
    }
    .width('100%')
    .height('100%')
  }
}
