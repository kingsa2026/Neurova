/**
 * ExperienceKnowledgePage - 经验知识页
 *
 * 职责：展示经验知识列表，支持按 category 分类筛选、新建、查看详情、删除
 * 设计：
 *   - ExperienceKnowledgeViewHelper（导出）：纯视图模型，封装 category 颜色映射、
 *     category 图标映射、importance 格式化、激活次数格式化、内容截断；
 *     无 UI 运行时依赖，可独立单元测试；
 *   - ExperienceKnowledgePage（@Component）：Column [TopNavMenu(标题"经验知识"+返回+新建)]
 *     + [category 筛选 Tab（全部/工作场景/技术细节/用户偏好/失败教训）]
 *     + [加载态/空态/列表]；列表项 GlassCard 含标题、category 徽章、importance 进度条、
 *     内容摘要（截断）、激活次数、最后激活时间、操作按钮（查看/编辑/删除）；
 *     删除走 AlertDialog 二次确认；新建走 Stack 条件渲染弹窗（标题、category 选择、
 *     importance slider、content 文本域）；
 *   - 颜色统一走 StyleManager，路由走 Router，API 走 ApiFacade.cognition，
 *     状态走 AgentsStore（currentAgentId 过滤），日志走 Logger，提示走 MessageManager。
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassCard、GlassButton、GlassInput、GlassPanel
 *   - ../libs/api/ApiFacade：统一 API 门面（cognition.listExperiences/getExperience/
 *     createExperience/updateExperience/removeExperience）
 *   - ../libs/state/stores/AgentsStore：Agent 状态（currentAgentId 过滤）
 *   - ../routing/Router：统一路由跳转
 *   - ../libs/style/StyleManager：统一样式 token
 *   - ../libs/logger/Logger：统一日志
 *   - ../libs/message/MessageManager：统一消息提示
 *   - ../libs/types：Experience
 *
 * 用法：
 *   由 Router.push 跳转进入；
 *   aboutToAppear 加载当前 Agent 的经验列表；
 *   category 筛选 Tab 切换 → 本地 filterByCategory 过滤；
 *   新建按钮 → 展示新建弹窗 → 填写表单 → 调用 api.cognition.createExperience → 刷新列表；
 *   查看按钮 → AlertDialog 展示完整内容；
 *   编辑按钮 → AlertDialog 展示元数据（M5 接入完整编辑流程）；
 *   删除按钮 → AlertDialog 二次确认 → 调用 api.cognition.removeExperience → 刷新列表
 *
 * TDD：ExperienceKnowledgeViewHelper 各方法按红绿灯垂直切片逐步实现，
 *      详见 ExperienceKnowledgePage.test.ets
 */

import { TopNavMenu, GlassCard, GlassButton, GlassInput, GlassPanel } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { AgentsStore } from '../libs/state/stores/AgentsStore';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { Experience } from '../libs/types';

/** 日志标签 */
const TAG = 'ExperienceKnowledgePage';

// ===========================================================================
// ExperienceKnowledgeViewHelper - 经验知识视图模型（纯函数，无 UI 依赖，可独立单元测试）
//
// 设计：所有方法为 static，输入 → 输出，无副作用；
//       颜色方法返回 StyleManager 的 token 名（如 'primary'），由页面解析为实际颜色值；
//       图标方法返回 emoji 字符串直接渲染；
//       通过本文件 export，供 ohosTest 直接导入测试
// ===========================================================================

export class ExperienceKnowledgeViewHelper {
  /**
   * 获取经验 category 对应的颜色 token 名
   * 映射：工作场景→primary，技术细节→info，用户偏好→success，
   *       失败教训→warning，其他→text_disabled
   * @param category 经验类别
   * @return StyleManager 颜色 token 名
   */
  static getCategoryColor(category: string): string {
    if (category === '工作场景') return 'primary';
    if (category === '技术细节') return 'info';
    if (category === '用户偏好') return 'success';
    if (category === '失败教训') return 'warning';
    return 'text_disabled';
  }

  /**
   * 获取经验 category 对应的图标 emoji
   * 映射：工作场景→💼，技术细节→🔧，用户偏好→❤️，失败教训→⚠️，其他→📄
   * @param category 经验类别
   * @return emoji 字符串
   */
  static getCategoryIcon(category: string): string {
    if (category === '工作场景') return '💼';
    if (category === '技术细节') return '🔧';
    if (category === '用户偏好') return '❤️';
    if (category === '失败教训') return '⚠️';
    return '📄';
  }

  /**
   * 格式化 importance 为百分比字符串
   * @param value 重要性 0-1
   * @return 百分比字符串，如 0.5 → "50%"，1 → "100%"
   */
  static formatImportance(value: number): string {
    return `${Math.round(value * 100)}%`;
  }

  /**
   * 格式化激活次数为人类可读字符串
   * @param count 激活次数
   * @return 0 → "未激活"，n > 0 → "激活 n 次"
   */
  static formatActivationCount(count: number): string {
    if (count === 0) return '未激活';
    return `激活 ${count} 次`;
  }

  /**
   * 截断内容，超长时截取 maxLen 字符并追加省略号
   * @param content 原始内容
   * @param maxLen 最大字符数，默认 100
   * @return 截断后的内容；未超长则原样返回
   */
  static truncateContent(content: string, maxLen: number = 100): string {
    if (content.length <= maxLen) return content;
    return content.substring(0, maxLen) + '...';
  }
}

// ===========================================================================
// category 筛选 Tab 配置
// ===========================================================================

/** category 筛选项：value 为 'all' 或具体 category 字符串 */
interface CategoryFilterOption {
  value: string;
  label: string;
}

/** category 筛选 Tab 列表（顺序即展示顺序） */
const CATEGORY_FILTERS: CategoryFilterOption[] = [
  { value: 'all', label: '全部' },
  { value: '工作场景', label: '工作场景' },
  { value: '技术细节', label: '技术细节' },
  { value: '用户偏好', label: '用户偏好' },
  { value: '失败教训', label: '失败教训' },
];

/** 新建表单数据结构 */
interface ExperienceFormData {
  title: string;
  category: string;
  importance: number;
  content: string;
}

@Component
export struct ExperienceKnowledgePage {
  // 经验列表（由 API 加载，驱动列表渲染；筛选在本地进行）
  @State experiences: Experience[] = [];
  // 加载态（控制"加载中..."占位与列表切换）
  @State loading: boolean = true;
  // 当前激活的 category 筛选值：'all' 或具体 category
  @State activeCategory: string = 'all';
  // 新建弹窗显隐
  @State showCreate: boolean = false;
  // 新建表单数据（嵌套对象整体替换以保证响应式）
  @State formData: ExperienceFormData = {
    title: '',
    category: '工作场景',
    importance: 0.5,
    content: '',
  };
  // 提交中态（防止重复提交）
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

  /**
   * 加载当前 Agent 的经验列表
   * 流程：取 currentAgentId → 调用 api.cognition.listExperiences → 写入 experiences
   * 异常：记录日志并提示用户；finally 关闭 loading
   */
  private async loadExperiences(): Promise<void> {
    this.loading = true;
    try {
      const agentId = this.agentsStore.currentAgentId || '';
      const res = await this.api.cognition.listExperiences(agentId);
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

  /**
   * 切换 category 筛选 Tab（本地过滤，无需重新请求后端）
   */
  private switchCategory(value: string): void {
    this.activeCategory = value;
  }

  /**
   * 获取经当前 category 筛选后的列表
   * 规则：activeCategory === 'all' 返回全量；否则按 category 字段过滤
   */
  private getFilteredList(): Experience[] {
    if (this.activeCategory === 'all') {
      return this.experiences;
    }
    return this.experiences.filter((item: Experience) => item.category === this.activeCategory);
  }

  /**
   * 打开新建弹窗
   * 重置表单为初始值，避免上次输入残留
   */
  private openCreate(): void {
    this.formData = {
      title: '',
      category: '工作场景',
      importance: 0.5,
      content: '',
    };
    this.showCreate = true;
  }

  /** 关闭新建弹窗 */
  private closeCreate(): void {
    this.showCreate = false;
  }

  /**
   * 表单字段更新（嵌套对象整体替换，保证 @State 响应式）
   */
  private updateFormField(field: keyof ExperienceFormData, value: string | number): void {
    this.formData = { ...this.formData, [field]: value } as ExperienceFormData;
  }

  /**
   * 提交新建
   * 流程：组装 Partial<Experience> → 调用 api.cognition.createExperience → 成功后关闭弹窗并刷新
   * 异常：记录日志并提示用户；finally 关闭 submitting
   */
  private async submitCreate(): Promise<void> {
    if (!this.formData.title.trim() || !this.formData.content.trim()) {
      this.msg.warning('请填写标题和内容');
      return;
    }
    this.submitting = true;
    try {
      const payload: Partial<Experience> = {
        agentId: this.agentsStore.currentAgentId || '',
        title: this.formData.title.trim(),
        category: this.formData.category,
        importance: this.formData.importance,
        content: this.formData.content.trim(),
        activationCount: 0,
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

  /**
   * 删除前二次确认（AlertDialog）
   */
  private confirmDelete(item: Experience): void {
    AlertDialog.show({
      title: '确认删除',
      message: `确定要删除经验"${item.title}"吗？此操作不可撤销。`,
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

  /**
   * 执行删除
   * 流程：调用 api.cognition.removeExperience → 成功后重新加载列表
   * 异常：记录日志并提示用户
   */
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

  /**
   * 展示经验详情（AlertDialog：完整内容 + 元数据）
   */
  private showDetail(item: Experience): void {
    const message =
      `标题：${item.title}\n\n` +
      `分类：${item.category}\n` +
      `重要性：${ExperienceKnowledgeViewHelper.formatImportance(item.importance)}\n` +
      `${ExperienceKnowledgeViewHelper.formatActivationCount(item.activationCount)}\n` +
      `最后激活：${this.formatTime(item.lastActivatedAt)}\n` +
      `创建时间：${this.formatTime(item.createdAt)}\n\n` +
      `内容：\n${item.content}`;
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

  /**
   * 展示编辑提示（M5 接入完整编辑流程，当前展示元数据）
   */
  private showEdit(item: Experience): void {
    const message =
      `标题：${item.title}\n` +
      `分类：${item.category}\n` +
      `重要性：${ExperienceKnowledgeViewHelper.formatImportance(item.importance)}\n\n` +
      `完整编辑功能开发中（M5 实现）。`;
    AlertDialog.show({
      title: '编辑经验',
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
        // 顶部导航栏：标题"经验知识" + 返回 + 新建按钮（右侧插槽）
        TopNavMenu({
          title: '经验知识',
          showBack: true,
          showMenu: false,
          onBack: () => { this.router.back(); }
        }) {
          GlassButton({
            text: '新建',
            type: 'primary',
            size: 'small',
            onClick: () => { this.openCreate(); }
          })
        }

        // category 筛选 Tab：横向滚动胶囊
        Scroll() {
          Row({ space: 8 }) {
            ForEach(CATEGORY_FILTERS, (opt: CategoryFilterOption) => {
              Text(opt.label)
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.activeCategory === opt.value
                  ? this.sm.getColor('text_on_primary')
                  : this.sm.getColor('text_secondary'))
                .backgroundColor(this.activeCategory === opt.value
                  ? this.sm.getColor('primary')
                  : this.sm.getColor('surface'))
                .padding({ left: 12, right: 12, top: 6, bottom: 6 })
                .borderRadius(16)
                .onClick(() => { this.switchCategory(opt.value); })
            }, (opt: CategoryFilterOption) => opt.value)
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
            ForEach(this.getFilteredList(), (item: Experience) => {
              ListItem() {
                this.buildExperienceCard(item)
              }
            }, (item: Experience) => item.id)
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

      // 新建弹窗：showCreate 为 true 时覆盖在主体之上
      if (this.showCreate) {
        this.buildCreateDialog()
      }
    }
    .width('100%')
    .height('100%')
  }

  // ===========================================================================
  // 经验卡片构建器
  // ===========================================================================

  /** 单条经验卡片：标题 + category 徽章 + importance 进度条 + 内容摘要 + 激活信息 + 操作按钮 */
  @Builder
  buildExperienceCard(item: Experience) {
    GlassCard() {
      Column() {
        // 标题行：图标 + 标题（最多 2 行）
        Row() {
          Text(ExperienceKnowledgeViewHelper.getCategoryIcon(item.category))
            .fontSize(18)
          Text(item.title)
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontWeight(FontWeight.Bold)
            .fontColor(this.sm.getColor('text_primary'))
            .layoutWeight(1)
            .margin({ left: 6 })
            .maxLines(2)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)

        // category 徽章（彩色胶囊）
        Row() {
          Text(item.category)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_on_primary'))
            .padding({ left: 8, right: 8, top: 2, bottom: 2 })
            .borderRadius(10)
            .backgroundColor(this.sm.getColor(ExperienceKnowledgeViewHelper.getCategoryColor(item.category)))
        }
        .width('100%')
        .alignItems(HorizontalAlign.Start)
        .margin({ top: this.sm.getSpacing('sm') })

        // 内容摘要（截断到 100 字符，最多 3 行）
        Text(ExperienceKnowledgeViewHelper.truncateContent(item.content))
          .fontSize(this.sm.getFontSize('body'))
          .fontColor(this.sm.getColor('text_primary'))
          .maxLines(3)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .margin({ top: this.sm.getSpacing('sm') })
          .width('100%')

        // importance 进度条 + 百分比
        Row() {
          Row() {
            Row()
              .width(`${Math.round(item.importance * 100)}%`)
              .height(4)
              .borderRadius(2)
              .backgroundColor(this.sm.getColor('primary'))
          }
          .width(80)
          .height(4)
          .borderRadius(2)
          .backgroundColor(this.sm.getColor('divider'))
          .alignItems(VerticalAlign.Start)

          Text(`重要性 ${ExperienceKnowledgeViewHelper.formatImportance(item.importance)}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .margin({ left: 8 })
        }
        .width('100%')
        .margin({ top: this.sm.getSpacing('sm') })
        .alignItems(VerticalAlign.Center)

        // 激活次数 + 最后激活时间
        Row() {
          Text(ExperienceKnowledgeViewHelper.formatActivationCount(item.activationCount))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
          Text('·')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_disabled'))
            .margin({ left: 6, right: 6 })
          Text(this.formatTime(item.lastActivatedAt))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_disabled'))
            .layoutWeight(1)
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
            .textAlign(TextAlign.End)
        }
        .width('100%')
        .margin({ top: this.sm.getSpacing('sm') })
        .alignItems(VerticalAlign.Center)

        // 操作按钮：查看 / 编辑 / 删除（右对齐）
        Row() {
          GlassButton({
            text: '查看',
            type: 'default',
            size: 'small',
            onClick: () => { this.showDetail(item); }
          })
          GlassButton({
            text: '编辑',
            type: 'default',
            size: 'small',
            onClick: () => { this.showEdit(item); }
          })
            .margin({ left: this.sm.getSpacing('sm') })
          GlassButton({
            text: '删除',
            type: 'danger',
            size: 'small',
            onClick: () => { this.confirmDelete(item); }
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

  // ===========================================================================
  // 新建弹窗构建器（Stack 覆盖层，内嵌实现，不创建单独 CustomDialog 文件）
  // ===========================================================================

  @Builder
  buildCreateDialog() {
    Stack({ alignContent: Alignment.Center }) {
      // 背景遮罩层：点击空白处关闭
      Column()
        .width('100%')
        .height('100%')
        .backgroundColor(this.sm.getColor('overlay_mask'))
        .onClick(() => { this.closeCreate(); })

      // 面板层：居中展示
      GlassPanel({ variant: 'elevated', padding: 20 }) {
        Column() {
          // 标题
          Text('新建经验')
            .fontSize(this.sm.getFontSize('title'))
            .fontWeight(FontWeight.Bold)
            .fontColor(this.sm.getColor('text_primary'))
            .width('100%')

          // 标题输入
          Text('标题')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .margin({ top: this.sm.getSpacing('md') })
          GlassInput({
            placeholder: '请输入经验标题',
            value: this.formData.title,
            type: 'text',
            onChange: (v: string) => { this.updateFormField('title', v); },
          })

          // category 选择
          Text('分类')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .margin({ top: this.sm.getSpacing('sm') })
          Row({ space: 8 }) {
            ForEach(CATEGORY_FILTERS.slice(1), (opt: CategoryFilterOption) => {
              Text(opt.label)
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.formData.category === opt.value
                  ? this.sm.getColor('text_on_primary')
                  : this.sm.getColor('text_secondary'))
                .backgroundColor(this.formData.category === opt.value
                  ? this.sm.getColor('primary')
                  : this.sm.getColor('surface'))
                .padding({ left: 10, right: 10, top: 4, bottom: 4 })
                .borderRadius(12)
                .onClick(() => { this.updateFormField('category', opt.value); })
            }, (opt: CategoryFilterOption) => opt.value)
          }
          .width('100%')
          .margin({ top: 4 })

          // importance 滑块
          Row() {
            Text('重要性')
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .layoutWeight(1)
            Text(ExperienceKnowledgeViewHelper.formatImportance(this.formData.importance))
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_primary'))
          }
          .width('100%')
          .margin({ top: this.sm.getSpacing('sm') })
          Slider({
            value: this.formData.importance,
            min: 0,
            max: 1,
            step: 0.05,
          })
            .width('100%')
            .onChange((value: number) => { this.updateFormField('importance', value); })

          // content 文本域（用 TextArea）
          Text('内容')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .margin({ top: this.sm.getSpacing('sm') })
          TextArea({
            placeholder: '请输入经验内容...',
            text: this.formData.content,
          })
            .width('100%')
            .height(120)
            .fontSize(this.sm.getFontSize('body'))
            .borderRadius(this.sm.getRadius('sm'))
            .backgroundColor(this.sm.getColor('surface'))
            .onChange((v: string) => { this.updateFormField('content', v); })

          // 操作按钮
          Row() {
            GlassButton({
              text: '取消',
              type: 'default',
              size: 'medium',
              onClick: () => { this.closeCreate(); }
            })
            GlassButton({
              text: this.submitting ? '提交中...' : '创建',
              type: 'primary',
              size: 'medium',
              onClick: () => { this.submitCreate(); }
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
