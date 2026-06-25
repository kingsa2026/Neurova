/**
 * CollaborationTemplatePage - 协作模板页
 *
 * 职责：展示协作模板列表，按 category 筛选（project/team/workflow），
 *   点击项查看步骤详情，新建按钮，按使用次数排序
 * 设计：
 *   - CollaborationTemplateViewHelper（导出）：纯视图模型，封装分类颜色映射、
 *     分类图标、分类文案、步骤数格式化、使用次数格式化、描述截断；
 *     无 UI 运行时依赖，可独立单元测试；
 *   - CollaborationTemplatePage（@Component）：Column [TopNavMenu(标题"协作模板"+返回+新建)] +
 *     [category 筛选 Tab（全部/project/team/workflow）] + [加载态/空态/列表]；
 *     列表项 GlassCard：name、category 徽章、描述、步骤数、使用次数、操作按钮；
 *     点击项 → AlertDialog 展示步骤详情；新建 → Stack 内嵌条件渲染弹窗；
 *   - 颜色统一走 StyleManager，路由走 Router，API 暂无 collaboration 专用模块 →
 *     aboutToAppear 加载 mock 静态数据 + TODO 注释 M6 阶段补充真实 API。
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassCard、GlassButton、GlassInput、GlassPanel
 *   - ../libs/api/ApiFacade：统一 API 门面（仅作为占位，未实际调用）
 *   - ../routing/Router：统一路由跳转
 *   - ../libs/style/StyleManager：统一样式 token
 *   - ../libs/logger/Logger：统一日志
 *   - ../libs/message/MessageManager：统一消息提示
 *   - ../libs/types：CollaborationTemplate
 *
 * 用法：
 *   由 Router.push(RouteNames.COLLABORATION_TEMPLATE) 跳转进入；
 *   aboutToAppear 加载 mock 模板列表（TODO M6 接入 api.collaboration.templates.list）；
 *   category 筛选 Tab 切换 → 本地 filterByCategory 过滤；
 *   点击项 → AlertDialog 展示完整步骤列表；
 *   新建 → 弹窗输入名称/描述/分类 → 提交 → TODO M6 接入 API。
 *
 * TDD：CollaborationTemplateViewHelper 各方法按红绿灯垂直切片逐步实现，
 *      详见 CollaborationTemplatePage.test.ets
 */

import { TopNavMenu, GlassCard, GlassButton, GlassInput, GlassPanel } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { CollaborationTemplate } from '../libs/types';

/** 日志标签 */
const TAG = 'CollaborationTemplatePage';

/** 描述截断默认最大长度 */
const DEFAULT_DESC_MAX_LEN = 50;

// ===========================================================================
// CollaborationTemplateViewHelper - 协作模板视图模型（纯函数，无 UI 依赖，可独立单元测试）
//
// 设计：所有方法为 static，输入 → 输出，无副作用；
//       颜色方法返回 StyleManager 的 token 名（如 'primary'），由页面解析为实际颜色值；
//       图标方法返回 emoji 字符串直接渲染；
//       通过本文件 export，供 ohosTest 直接导入测试
// ===========================================================================

export class CollaborationTemplateViewHelper {
  /**
   * 获取模板分类对应的颜色 token 名
   * 映射：project→primary，team→info，workflow→success
   * @param category 分类字符串
   * @return StyleManager 颜色 token 名
   */
  static getCategoryColor(category: string): string {
    if (category === 'project') return 'primary';
    if (category === 'team') return 'info';
    if (category === 'workflow') return 'success';
    // 未覆盖的分类抛错，强制 TDD 红灯逐项补齐
    throw new Error(`getCategoryColor 未实现: ${category}`);
  }

  /**
   * 获取模板分类对应的图标 emoji
   * 映射：project→📋，team→👥，workflow→🔄
   * @param category 分类字符串
   * @return emoji 字符串
   */
  static getCategoryIcon(category: string): string {
    if (category === 'project') return '📋';
    if (category === 'team') return '👥';
    if (category === 'workflow') return '🔄';
    throw new Error(`getCategoryIcon 未实现: ${category}`);
  }

  /**
   * 获取模板分类对应的中文标签
   * 映射：project→项目，team→团队，workflow→工作流
   * @param category 分类字符串
   * @return 中文文案
   */
  static getCategoryLabel(category: string): string {
    if (category === 'project') return '项目';
    if (category === 'team') return '团队';
    if (category === 'workflow') return '工作流';
    throw new Error(`getCategoryLabel 未实现: ${category}`);
  }

  /**
   * 格式化步骤数为展示字符串
   * 规则：空数组 → "0 步"；非空 → "N 步"（N = 数组长度）
   * @param steps 步骤数组（仅依赖 length，字段名按类型约束）
   * @return 步骤数展示字符串
   */
  static formatStepsCount(steps: Array<{ name: string }>): string {
    if (!steps || steps.length === 0) return '0 步';
    return `${steps.length} 步`;
  }

  /**
   * 格式化使用次数为人类可读字符串
   * 规则：0 → "未使用"；1-999 → "{n} 次"；≥1000 → "999+ 次"
   * @param count 使用次数
   * @return 使用次数展示字符串
   */
  static formatUsageCount(count: number): string {
    if (count === 0) return '未使用';
    if (count >= 1000) return '999+ 次';
    return `${count} 次`;
  }

  /**
   * 截断描述文本，超长时截取 maxLen 字符并追加省略号
   * @param desc 原始描述
   * @param maxLen 最大字符数
   * @return 截断后的描述；未超长则原样返回
   */
  static truncateDescription(desc: string, maxLen: number): string {
    if (desc.length <= maxLen) return desc;
    return desc.substring(0, maxLen) + '...';
  }
}

/** 分类筛选 Tab 配置 */
interface CategoryFilterOption {
  value: string;     // 'all' 或具体分类
  label: string;
}

/** 分类筛选 Tab 列表 */
const CATEGORY_FILTERS: CategoryFilterOption[] = [
  { value: 'all', label: '全部' },
  { value: 'project', label: '项目' },
  { value: 'team', label: '团队' },
  { value: 'workflow', label: '工作流' },
];

/** 新建模板表单数据 */
interface TemplateFormData {
  name: string;
  description: string;
  category: string;
}

/** 默认表单数据 */
const DEFAULT_FORM: TemplateFormData = {
  name: '',
  description: '',
  category: 'project',
};

/**
 * Mock 协作模板数据
 * TODO M6 阶段：替换为 api.collaboration.templates.list() 真实 API
 */
const MOCK_TEMPLATES: CollaborationTemplate[] = [
  {
    id: 'tpl_1',
    name: '敏捷开发协作',
    description: '面向小型团队的敏捷开发协作流程，包含需求评审、迭代规划、每日站会等环节',
    category: 'project',
    steps: [
      { name: '需求评审', order: 1 },
      { name: '迭代规划', order: 2 },
      { name: '每日站会', order: 3 },
      { name: '迭代评审', order: 4 },
    ],
    isPublic: true,
    usageCount: 50,
    createdAt: '2025-01-10T08:00:00Z',
    updatedAt: '2025-02-01T10:00:00Z',
  },
  {
    id: 'tpl_2',
    name: '跨部门协作',
    description: '产品、设计、研发三方协作模板',
    category: 'team',
    steps: [
      { name: '需求对齐', order: 1 },
      { name: '设计评审', order: 2 },
    ],
    isPublic: false,
    usageCount: 0,
    createdAt: '2025-01-15T08:00:00Z',
    updatedAt: '2025-01-20T10:00:00Z',
  },
  {
    id: 'tpl_3',
    name: '自动化部署工作流',
    description: 'CI/CD 自动化部署协作流程',
    category: 'workflow',
    steps: [
      { name: '代码合并', order: 1 },
      { name: '自动测试', order: 2 },
      { name: '构建镜像', order: 3 },
      { name: '灰度发布', order: 4 },
      { name: '全量发布', order: 5 },
    ],
    isPublic: true,
    usageCount: 1200,
    createdAt: '2025-02-01T08:00:00Z',
    updatedAt: '2025-03-01T10:00:00Z',
  },
];

@Component
export struct CollaborationTemplatePage {
  // 模板列表
  @State templates: CollaborationTemplate[] = [];
  // 加载态
  @State loading: boolean = true;
  // 当前激活的分类筛选值
  @State activeCategory: string = 'all';
  // 新建弹窗显示状态
  @State showCreateDialog: boolean = false;
  // 新建表单数据（嵌套属性变更需整体重新赋值）
  @State formData: TemplateFormData = { ...DEFAULT_FORM };

  // 统一库单例
  private api = ApiFacade.getInstance();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private msg = MessageManager.getInstance();

  aboutToAppear() {
    this.loadTemplates();
  }

  /**
   * 加载模板列表
   * TODO M6 阶段：替换为真实 API（api.collaboration.templates.list）
   * 当前使用 mock 静态数据，按使用次数降序排序
   */
  private async loadTemplates(): Promise<void> {
    this.loading = true;
    try {
      // TODO M6 阶段补充真实 API
      // const res = await this.api.collaboration.templates.list();
      // if (res.code === 0 && res.data) { this.templates = res.data.items; }
      this.templates = MOCK_TEMPLATES.slice().sort((a: CollaborationTemplate, b: CollaborationTemplate) => {
        return b.usageCount - a.usageCount;
      });
    } catch (e) {
      this.logger.error(TAG, '加载模板失败', e as Error);
      this.msg.error('加载协作模板失败');
    } finally {
      this.loading = false;
    }
  }

  /** 切换分类筛选 */
  private switchCategory(value: string): void {
    this.activeCategory = value;
  }

  /**
   * 获取经分类筛选后的列表
   * 规则：activeCategory === 'all' 返回全量；否则按 category 字段过滤
   */
  private getFilteredTemplates(): CollaborationTemplate[] {
    if (this.activeCategory === 'all') {
      return this.templates;
    }
    return this.templates.filter((t: CollaborationTemplate) => t.category === this.activeCategory);
  }

  /** 打开新建弹窗，重置表单 */
  private openCreateDialog(): void {
    this.formData = { ...DEFAULT_FORM };
    this.showCreateDialog = true;
  }

  /** 选择分类（嵌套属性变更：整体重新赋值） */
  private selectCategory(category: string): void {
    this.formData = { ...this.formData, category };
  }

  /** 输入名称（嵌套属性变更：整体重新赋值） */
  private inputName(v: string): void {
    this.formData = { ...this.formData, name: v };
  }

  /** 输入描述（嵌套属性变更：整体重新赋值） */
  private inputDescription(v: string): void {
    this.formData = { ...this.formData, description: v };
  }

  /**
   * 提交新建模板
   * TODO M6 阶段：调用真实 API（api.collaboration.templates.create）
   * 当前为本地追加 + TODO 提示
   */
  private async submitCreate(): Promise<void> {
    if (!this.formData.name.trim()) {
      this.msg.warning('请填写模板名称');
      return;
    }
    try {
      // TODO M6 阶段：const res = await this.api.collaboration.templates.create(form);
      const now = new Date().toISOString();
      const newTpl: CollaborationTemplate = {
        id: `tpl_${Date.now()}`,
        name: this.formData.name.trim(),
        description: this.formData.description.trim(),
        category: this.formData.category,
        steps: [],
        isPublic: false,
        usageCount: 0,
        createdAt: now,
        updatedAt: now,
      };
      this.templates = [newTpl, ...this.templates];
      this.msg.success('已创建');
      this.showCreateDialog = false;
    } catch (e) {
      this.logger.error(TAG, '创建模板失败', e as Error);
      this.msg.error('创建模板失败');
    }
  }

  /**
   * 查看模板步骤详情
   * AlertDialog 展示完整步骤列表
   */
  private showDetail(tpl: CollaborationTemplate): void {
    const stepsText = tpl.steps.length === 0
      ? '暂无步骤'
      : tpl.steps
          .sort((a, b) => a.order - b.order)
          .map((s, idx) => `${idx + 1}. ${s.name}${s.description ? ' - ' + s.description : ''}`)
          .join('\n');
    AlertDialog.show({
      title: tpl.name,
      message: `分类：${CollaborationTemplateViewHelper.getCategoryLabel(tpl.category)}\n\n` +
        `步骤：\n${stepsText}\n\n` +
        `使用次数：${CollaborationTemplateViewHelper.formatUsageCount(tpl.usageCount)}`,
      autoCancel: true,
      alignment: DialogAlignment.Center,
      primaryButton: {
        value: '关闭',
        action: () => {}
      }
    });
  }

  build() {
    Stack() {
      Column() {
        // 顶部导航栏：标题"协作模板" + 返回 + 新建
        TopNavMenu({
          title: '协作模板',
          showBack: true,
          showMenu: false,
          onBack: () => { this.router.back(); }
        }) {
          GlassButton({
            text: '新建',
            type: 'primary',
            size: 'small',
            onClick: () => { this.openCreateDialog(); }
          })
        }

        // 分类筛选 Tab
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
        } else if (this.getFilteredTemplates().length === 0) {
          Column() {
            Text('暂无模板')
              .fontSize(this.sm.getFontSize('subtitle'))
              .fontColor(this.sm.getColor('text_secondary'))
          }
          .width('100%')
          .layoutWeight(1)
          .justifyContent(FlexAlign.Center)
          .alignItems(HorizontalAlign.Center)
        } else {
          List({ space: 12 }) {
            ForEach(this.getFilteredTemplates(), (tpl: CollaborationTemplate) => {
              ListItem() {
                this.buildTemplateCard(tpl)
              }
            }, (tpl: CollaborationTemplate) => tpl.id)
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

      // 新建模板弹窗
      if (this.showCreateDialog) {
        this.buildCreateDialog()
      }
    }
    .width('100%')
    .height('100%')
  }

  // ===========================================================================
  // 模板卡片构建器
  // ===========================================================================

  /** 单个模板卡片：分类徽章 + 名称 + 描述 + 步骤/使用次数 + 操作按钮 */
  @Builder
  buildTemplateCard(tpl: CollaborationTemplate) {
    GlassCard() {
      Column() {
        // 顶部行：分类图标 + 分类徽章 + 名称
        Row() {
          Text(CollaborationTemplateViewHelper.getCategoryIcon(tpl.category))
            .fontSize(20)
          Text(CollaborationTemplateViewHelper.getCategoryLabel(tpl.category))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_on_primary'))
            .padding({ left: 6, right: 6, top: 2, bottom: 2 })
            .borderRadius(this.sm.getRadius('sm'))
            .backgroundColor(this.sm.getColor(CollaborationTemplateViewHelper.getCategoryColor(tpl.category)))
            .margin({ left: this.sm.getSpacing('xs') })
          Text(tpl.name)
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontWeight(FontWeight.Bold)
            .fontColor(this.sm.getColor('text_primary'))
            .layoutWeight(1)
            .margin({ left: this.sm.getSpacing('sm') })
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)

        // 描述（默认 50 字符截断）
        Text(CollaborationTemplateViewHelper.truncateDescription(
          tpl.description ?? '', DEFAULT_DESC_MAX_LEN))
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('text_secondary'))
          .maxLines(2)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .margin({ top: this.sm.getSpacing('xs') })
          .width('100%')

        // 步骤数 + 使用次数
        Row() {
          Text(CollaborationTemplateViewHelper.formatStepsCount(tpl.steps))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_disabled'))
            .layoutWeight(1)
          Text(CollaborationTemplateViewHelper.formatUsageCount(tpl.usageCount))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_disabled'))
        }
        .width('100%')
        .margin({ top: this.sm.getSpacing('xs') })
        .alignItems(VerticalAlign.Center)

        // 操作按钮：查看详情（右对齐）
        Row() {
          GlassButton({
            text: '详情',
            type: 'default',
            size: 'small',
            onClick: () => { this.showDetail(tpl); }
          })
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
  // 新建模板弹窗构建器（Stack 内嵌条件渲染）
  // ===========================================================================

  /** 新建模板弹窗：名称 + 描述 + 分类选择 */
  @Builder
  buildCreateDialog() {
    Stack({ alignContent: Alignment.Center }) {
      // 背景遮罩层：点击空白处关闭
      Column()
        .width('100%')
        .height('100%')
        .backgroundColor(this.sm.getColor('overlay_mask'))
        .onClick(() => { this.showCreateDialog = false; })

      // 面板层
      GlassPanel({ variant: 'elevated', padding: 20 }) {
        Column() {
          Text('新建协作模板')
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontWeight(FontWeight.Bold)
            .fontColor(this.sm.getColor('text_primary'))
            .width('100%')

          // 名称输入
          Text('模板名称')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .width('100%')
            .margin({ top: this.sm.getSpacing('sm') })
          GlassInput({
            placeholder: '请输入模板名称',
            value: this.formData.name,
            type: 'text',
            onChange: (v: string) => { this.inputName(v); },
          })
            .margin({ top: 4 })

          // 描述输入
          Text('描述')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .width('100%')
            .margin({ top: this.sm.getSpacing('sm') })
          GlassInput({
            placeholder: '请输入描述（可选）',
            value: this.formData.description,
            type: 'text',
            onChange: (v: string) => { this.inputDescription(v); },
          })
            .margin({ top: 4 })

          // 分类选择
          Text('分类')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .width('100%')
            .margin({ top: this.sm.getSpacing('sm') })
          Row() {
            ForEach(CATEGORY_FILTERS.slice(1), (opt: CategoryFilterOption) => {
              GlassButton({
                text: opt.label,
                type: this.formData.category === opt.value ? 'primary' : 'default',
                size: 'small',
                onClick: () => { this.selectCategory(opt.value); }
              })
                .margin({ right: this.sm.getSpacing('xs') })
            }, (opt: CategoryFilterOption) => opt.value)
          }
          .width('100%')
          .margin({ top: this.sm.getSpacing('xs'), bottom: this.sm.getSpacing('md') })

          // 操作按钮
          Row() {
            GlassButton({
              text: '取消',
              type: 'default',
              size: 'medium',
              onClick: () => { this.showCreateDialog = false; }
            })
            GlassButton({
              text: '提交',
              type: 'primary',
              size: 'medium',
              onClick: () => { this.submitCreate(); }
            })
              .margin({ left: this.sm.getSpacing('sm') })
          }
          .width('100%')
          .justifyContent(FlexAlign.End)
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
