/**
 * ExperienceKnowledgePage - 经验知识页（技能经验库，真实契约版）
 *
 * 数据：GET /v1/experience/ranking?agent_id=&page=&size=
 *       （experience_knowledge_api.py 契约投影：id/agent_id/task_type/
 *        skill_name/context/outcome/success_rate/proficiency/
 *        experience_count/lessons/adoption_outcome）
 * 操作：POST /experience/records（手动结晶）、DELETE /experience/{id}。
 * 筛选：outcome 三态（成功/失败/未验证）——后端真实字段，替代旧假 category。
 */

import { TopNavMenu, GlassCard, GlassButton, GlassInput, GlassPanel } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { AgentsStore } from '../libs/state/stores/AgentsStore';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { ExperienceDto } from '../libs/api/modules/CognitionApi';

/** 日志标签 */
const TAG = 'ExperienceKnowledgePage';

/** 结果筛选 Tab 配置：value 为后端 outcome 词汇 */
interface OutcomeFilterOption {
  value: string;
  label: string;
}

/** 结果筛选列表（''=全部） */
const OUTCOME_FILTERS: OutcomeFilterOption[] = [
  { value: '', label: '全部' },
  { value: 'success', label: '成功' },
  { value: 'failure', label: '失败' },
  { value: 'unevidenced', label: '未验证' },
];

/** 新建表单数据结构 */
interface ExperienceFormData {
  taskType: string;
  context: string;
  outcome: string;
  lessons: string;
}

@Component
export struct ExperienceKnowledgePage {
  // 经验列表（由 API 加载，驱动列表渲染；outcome 筛选在本地进行）
  @State experiences: ExperienceDto[] = [];
  // 加载态
  @State loading: boolean = true;
  // 当前 outcome 筛选值：'' 或 success/failure/unevidenced
  @State activeOutcome: string = '';
  // 新建弹窗显隐
  @State showCreate: boolean = false;
  // 新建表单数据
  @State formData: ExperienceFormData = {
    taskType: '',
    context: '',
    outcome: 'success',
    lessons: '',
  };
  // 提交中态
  @State submitting: boolean = false;

  // 统一库单例
  private api = ApiFacade.getInstance();
  private agentsStore = new AgentsStore();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private msg = MessageManager.getInstance();

  aboutToAppear() {
    this.loadExperiences();
  }

  /** 加载当前 Agent 的经验列表 */
  private async loadExperiences(): Promise<void> {
    this.loading = true;
    try {
      const agentId = this.agentsStore.currentAgentId || '';
      const res = await this.api.cognition.listExperiences(agentId, 1, 50);
      if (res.code === 0 && res.data) {
        this.experiences = res.data.items;
      }
    } catch (e) {
      this.logger.error(TAG, '加载经验失败', e as Error);
      this.msg.error('加载经验列表失败');
    } finally {
      this.loading = false;
    }
  }

  /** 切换 outcome 筛选 */
  private switchOutcome(value: string): void {
    this.activeOutcome = value;
  }

  /** 按 outcome 筛选后的列表 */
  private getFilteredList(): ExperienceDto[] {
    if (this.activeOutcome.length === 0) {
      return this.experiences;
    }
    return this.experiences.filter((item: ExperienceDto) => item.outcome === this.activeOutcome);
  }

  private openCreate(): void {
    this.formData = {
      taskType: '',
      context: '',
      outcome: 'success',
      lessons: '',
    };
    this.showCreate = true;
  }

  private closeCreate(): void {
    this.showCreate = false;
  }

  private updateFormField(field: keyof ExperienceFormData, value: string): void {
    this.formData = { ...this.formData, [field]: value } as ExperienceFormData;
  }

  /** 提交新建（AddExperienceRecordRequest 契约） */
  private async submitCreate(): Promise<void> {
    if (!this.formData.taskType.trim() || !this.formData.context.trim()) {
      this.msg.warning('请填写任务类型和上下文');
      return;
    }
    this.submitting = true;
    try {
      const payload: Record<string, Object> = {
        'agent_id': this.agentsStore.currentAgentId || 'default',
        'task_type': this.formData.taskType.trim(),
        'context': this.formData.context.trim(),
        'outcome': this.formData.outcome,
        'lessons': [this.formData.lessons.trim()],
      };
      const res = await this.api.cognition.createExperience(payload);
      if (res.code === 0) {
        this.msg.success('创建成功');
        this.showCreate = false;
        this.loadExperiences();
      } else {
        this.msg.error(res.message || '创建失败');
      }
    } catch (e) {
      this.logger.error(TAG, '创建经验失败', e as Error);
      this.msg.error('创建经验失败');
    } finally {
      this.submitting = false;
    }
  }

  private confirmDelete(item: ExperienceDto): void {
    AlertDialog.show({
      title: '确认删除',
      message: `确定要删除经验"${item.skill_name}"吗？此操作不可撤销。`,
      autoCancel: true,
      alignment: DialogAlignment.Center,
      primaryButton: {
        value: '取消',
        action: () => {}
      },
      secondaryButton: {
        value: '删除',
        fontColor: this.sm.getColor('error'),
        action: () => { this.deleteExperience(item.id); }
      }
    });
  }

  private async deleteExperience(experienceId: string): Promise<void> {
    try {
      const res = await this.api.cognition.removeExperience(experienceId);
      if (res.code === 0) {
        this.msg.success('删除成功');
        this.loadExperiences();
      } else {
        this.msg.error(res.message || '删除失败');
      }
    } catch (e) {
      this.logger.error(TAG, '删除经验失败', e as Error);
      this.msg.error('删除经验失败');
    }
  }

  /** 展示经验详情 */
  private showDetail(item: ExperienceDto): void {
    const message =
      `任务类型：${item.task_type}\n\n` +
      `结果：${item.outcome}\n` +
      `熟练度：${ExperienceKnowledgeViewHelper.formatProficiency(item.proficiency)}\n` +
      `创建时间：${this.formatTime(item.created_at)}\n\n` +
      `上下文：\n${item.context}`;
    AlertDialog.show({
      title: '经验详情',
      message,
      autoCancel: true,
      alignment: DialogAlignment.Center,
      primaryButton: {
        value: '关闭',
        action: () => {}
      }
    });
  }

  /** 格式化时间（YYYY-MM-DD HH:mm），无值回退 '未知' */
  private formatTime(timeStr?: string): string {
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
    Stack({ alignContent: Alignment.Center }) {
      Column() {
        // 顶部导航栏
        TopNavMenu({
          title: '经验知识',
          showBack: true,
          showMenu: false,
          onBack: () => { this.router.back(); }
        }) {
          GlassButton({
            text: '新建',
            type: 'primary',
            btnSize: 'small',
            onTap: () => { this.openCreate(); }
          })
        }

        // outcome 筛选 Tab
        Scroll() {
          Row({ space: 8 }) {
            ForEach(OUTCOME_FILTERS, (opt: OutcomeFilterOption) => {
              Text(opt.label)
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.activeOutcome === opt.value
                  ? this.sm.getColor('text_on_primary')
                  : this.sm.getColor('text_secondary'))
                .backgroundColor(this.activeOutcome === opt.value
                  ? this.sm.getColor('primary')
                  : this.sm.getColor('surface'))
                .padding({ left: 12, right: 12, top: 6, bottom: 6 })
                .borderRadius(16)
                .onClick(() => { this.switchOutcome(opt.value); })
            }, (opt: OutcomeFilterOption) => opt.value)
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

        // 主体：加载态 / 空态 / 列表
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
        } else if (this.getFilteredList().length === 0) {
          Column() {
            Text('暂无经验')
              .fontSize(this.sm.getFontSize('subtitle'))
              .fontColor(this.sm.getColor('text_secondary'))
          }
          .width('100%')
          .layoutWeight(1)
          .justifyContent(FlexAlign.Center)
          .alignItems(HorizontalAlign.Center)
        } else {
          List({ space: 12 }) {
            ForEach(this.getFilteredList(), (item: ExperienceDto) => {
              ListItem() {
                this.buildExperienceCard(item)
              }
            }, (item: ExperienceDto) => item.id)
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

      // 新建弹窗
      if (this.showCreate) {
        this.buildCreateDialog()
      }
    }
    .width('100%')
    .height('100%')
  }

  /** 单条经验卡片：技能名 + task_type 徽章 + outcome 徽章 + 熟练度 + 上下文 + 操作 */
  @Builder
  buildExperienceCard(item: ExperienceDto) {
    GlassCard() {
      Column() {
        // 标题行：技能名 + outcome 徽章
        Row() {
          Text(item.skill_name)
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontWeight(FontWeight.Bold)
            .fontColor(this.sm.getColor('text_primary'))
            .layoutWeight(1)
            .maxLines(2)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
          Text(item.outcome)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_on_primary'))
            .padding({ left: 8, right: 8, top: 2, bottom: 2 })
            .borderRadius(10)
            .backgroundColor(this.sm.getColor('primary'))
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)

        // 上下文摘要
        Text(ExperienceKnowledgeViewHelper.truncateContent(item.context))
          .fontSize(this.sm.getFontSize('body'))
          .fontColor(this.sm.getColor('text_primary'))
          .maxLines(3)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .margin({ top: this.sm.getSpacing('sm') })
          .width('100%')

        // 熟练度进度条（后端未测量时为 null，展示兜底 0%）
        Row() {
          Row() {
            Row()
              .width(`${Math.round((item.proficiency === null ? 0 : item.proficiency) * 100)}%`)
              .height(4)
              .borderRadius(2)
              .backgroundColor(this.sm.getColor('primary'))
          }
          .width(80)
          .height(4)
          .borderRadius(2)
          .backgroundColor(this.sm.getColor('divider'))
          .alignItems(VerticalAlign.Start)

          Text(`熟练度 ${ExperienceKnowledgeViewHelper.formatProficiency(item.proficiency)}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .margin({ left: 8 })
        }
        .width('100%')
        .margin({ top: this.sm.getSpacing('sm') })
        .alignItems(VerticalAlign.Center)

        // 经验次数 + 创建时间
        Row() {
          Text(`经验 ${item.experience_count} 次`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
          Text('·')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_disabled'))
            .margin({ left: 6, right: 6 })
          Text(this.formatTime(item.created_at))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_disabled'))
            .layoutWeight(1)
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
            .textAlign(TextAlign.End)
        }
        .width('100%')
        .margin({ top: this.sm.getSpacing('sm') })

        // 操作按钮：查看 / 删除
        Row() {
          GlassButton({
            text: '查看',
            type: 'default',
            btnSize: 'small',
            onTap: () => { this.showDetail(item); }
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
    .width('100%')
  }

  /** 新建弹窗（AddExperienceRecordRequest 契约字段） */
  @Builder
  buildCreateDialog() {
    Stack({ alignContent: Alignment.Center }) {
      Column()
        .width('100%')
        .height('100%')
        .backgroundColor(this.sm.getColor('overlay_mask'))
        .onClick(() => { this.closeCreate(); })

      GlassPanel({ variant: 'elevated', innerPadding: 20 }) {
        Column() {
          Text('新建经验')
            .fontSize(this.sm.getFontSize('title'))
            .fontWeight(FontWeight.Bold)
            .fontColor(this.sm.getColor('text_primary'))
            .width('100%')

          Text('任务类型')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .margin({ top: this.sm.getSpacing('md') })
          GlassInput({
            placeholder: '如 数据清洗、周报生成',
            value: this.formData.taskType,
            type: 'text',
            onChange: (v: string) => { this.updateFormField('taskType', v); },
          })

          Text('结果')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .margin({ top: this.sm.getSpacing('sm') })
          Row({ space: 8 }) {
            ForEach(['success', 'failure', 'unevidenced'], (o: string) => {
              Text(o)
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.formData.outcome === o
                  ? this.sm.getColor('text_on_primary')
                  : this.sm.getColor('text_secondary'))
                .backgroundColor(this.formData.outcome === o
                  ? this.sm.getColor('primary')
                  : this.sm.getColor('surface'))
                .padding({ left: 10, right: 10, top: 4, bottom: 4 })
                .borderRadius(12)
                .onClick(() => { this.updateFormField('outcome', o); })
            }, (o: string) => o)
          }
          .width('100%')
          .margin({ top: 4 })

          Text('上下文')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .margin({ top: this.sm.getSpacing('sm') })
          TextArea({
            placeholder: '请输入调用上下文...',
            text: this.formData.context,
          })
            .width('100%')
            .height(100)
            .fontSize(this.sm.getFontSize('body'))
            .borderRadius(this.sm.getRadius('sm'))
            .backgroundColor(this.sm.getColor('surface'))
            .onChange((v: string) => { this.updateFormField('context', v); })

          Text('经验教训（选填）')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .margin({ top: this.sm.getSpacing('sm') })
          GlassInput({
            placeholder: '请输入经验教训',
            value: this.formData.lessons,
            type: 'text',
            onChange: (v: string) => { this.updateFormField('lessons', v); },
          })

          Row() {
            GlassButton({
              text: '取消',
              type: 'default',
              btnSize: 'medium',
              onTap: () => { this.closeCreate(); }
            })
            GlassButton({
              text: this.submitting ? '提交中...' : '创建',
              type: 'primary',
              btnSize: 'medium',
              onTap: () => { this.submitCreate(); }
            })
              .margin({ left: this.sm.getSpacing('sm') })
              .layoutWeight(1)
          }
          .width('100%')
          .justifyContent(FlexAlign.End)
          .margin({ top: this.sm.getSpacing('md') })
        }
        .width('100%')
        .alignItems(HorizontalAlign.Start)
      }
      .width('90%')
    }
    .width('100%')
    .height('100%')
  }
}

/**
 * ExperienceKnowledgeViewHelper - 展示纯函数集合
 */
export class ExperienceKnowledgeViewHelper {
  /** 熟练度格式化（0-1 → 百分比；后端未测量为 null 时兜底 0%） */
  static formatProficiency(value: number | null): string {
    const v = value === null ? 0 : value;
    return `${Math.round(v * 100)}%`;
  }

  /** 内容截断到 100 字符 */
  static truncateContent(content: string): string {
    if (content.length <= 100) {
      return content;
    }
    return content.slice(0, 100) + '…';
  }
}
