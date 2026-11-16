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
import { CollaborationTemplateDto, TemplateCreateBody } from '../libs/api/modules/CollaborationApi';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';

/** 日志标签 */
const TAG = 'CollaborationTemplatePage';

/** 描述截断默认最大长度 */
const DEFAULT_DESC_MAX_LEN = 50;

// ===========================================================================
// CollaborationTemplateViewHelper - 协作模板视图模型（纯函数，无 UI 依赖，可独立单元测试）
//
// 设计：所有方法为 static，输入 → 输出，无副作用；
//       通过本文件 export，供 ohosTest 直接导入测试
// ===========================================================================

export class CollaborationTemplateViewHelper {
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

/** 新建模板表单数据 */
interface TemplateFormData {
  name: string;
  description: string;
}

/** 默认表单数据 */
const DEFAULT_FORM: TemplateFormData = {
  name: '',
  description: '',
};

/** 默认表单工厂（ArkTS 禁 spread 复制，集中此处） */
function defaultForm(): TemplateFormData {
  const form: TemplateFormData = { name: '', description: '' };
  return form;
}

@Component
export struct CollaborationTemplatePage {
  // 模板列表（真实 DTO：GET /v1/collaboration/templates）
  @State templates: CollaborationTemplateDto[] = [];
  // 加载态
  @State loading: boolean = true;
  // 新建弹窗显示状态
  @State showCreateDialog: boolean = false;
  // 新建表单数据（嵌套属性变更需整体重新赋值）
  @State formData: TemplateFormData = defaultForm();

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
   * 加载模板列表（真实 API：GET /v1/collaboration/templates，P1-34）
   * 按更新时间倒序排序
   */
  private async loadTemplates(): Promise<void> {
    this.loading = true;
    try {
      const res = await this.api.collaboration.listTemplates(100);
      if (res.code === 0 && res.data) {
        this.templates = res.data.slice().sort((a: CollaborationTemplateDto, b: CollaborationTemplateDto) => {
          return new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime();
        });
      } else {
        this.msg.error(res.message || '加载协作模板失败');
      }
    } catch (e) {
      this.logger.error(TAG, '加载模板失败', e as Error);
      this.msg.error('加载协作模板失败');
    } finally {
      this.loading = false;
    }
  }

  /** 打开新建弹窗，重置表单 */
  private openCreateDialog(): void {
    this.formData = defaultForm();
    this.showCreateDialog = true;
  }

  /** 输入名称（嵌套属性变更：整体重新赋值） */
  private inputName(v: string): void {
    this.formData = { name: v, description: this.formData.description };
  }

  /** 输入描述（嵌套属性变更：整体重新赋值） */
  private inputDescription(v: string): void {
    this.formData = { name: this.formData.name, description: v };
  }

  /**
   * 提交新建模板（真实 API：POST /v1/collaboration/templates，P1-34）
   */
  private async submitCreate(): Promise<void> {
    if (!this.formData.name.trim()) {
      this.msg.warning('请填写模板名称');
      return;
    }
    try {
      const body: TemplateCreateBody = {
        name: this.formData.name.trim(),
        description: this.formData.description.trim(),
        workflow: {},
        participants: [],
      };
      const res = await this.api.collaboration.createTemplate(body);
      if (res.code === 0 && res.data) {
        this.templates = [res.data, ...this.templates];
        this.msg.success('已创建');
        this.showCreateDialog = false;
      } else {
        this.msg.error(res.message || '创建模板失败');
      }
    } catch (e) {
      this.logger.error(TAG, '创建模板失败', e as Error);
      this.msg.error('创建模板失败');
    }
  }

  /**
   * 查看模板详情（AlertDialog 展示参与者与时间）
   */
  private showDetail(tpl: CollaborationTemplateDto): void {
    const participantsText = tpl.participants.length === 0 ? '无' : tpl.participants.join('、');
    AlertDialog.show({
      title: tpl.name,
      message: `描述：${tpl.description || '无'}\n\n` +
        `参与者：${participantsText}\n\n` +
        `创建时间：${tpl.created_at}\n更新时间：${tpl.updated_at}`,
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
            btnSize: 'small',
            onTap: () => { this.openCreateDialog(); }
          })
        }

        // 主体内容：加载态 / 空态 / 列表 三选一（后端模板无分类维度，不设筛选 Tab）
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
        } else if (this.templates.length === 0) {
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
            ForEach(this.templates, (tpl: CollaborationTemplateDto) => {
              ListItem() {
                this.buildTemplateCard(tpl)
              }
            }, (tpl: CollaborationTemplateDto) => tpl.template_id)
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

  /** 单个模板卡片：名称 + 描述 + 参与者数 + 更新时间 + 操作按钮 */
  @Builder
  buildTemplateCard(tpl: CollaborationTemplateDto) {
    Column() {
    GlassCard() {
      Column() {
        // 顶部行：名称
        Row() {
          Text('📋')
            .fontSize(20)
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

        // 参与者数 + 更新时间
        Row() {
          Text(CollaborationTemplateViewHelper.formatParticipantsCount(tpl.participants.length))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_disabled'))
            .layoutWeight(1)
          Text(`更新：${tpl.updated_at}`)
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
            btnSize: 'small',
            onTap: () => { this.showDetail(tpl); }
          })
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
      Column() {
      GlassPanel({ variant: 'elevated', innerPadding: 20 }) {
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

          // 操作按钮
          Row() {
            GlassButton({
              text: '取消',
              type: 'default',
              btnSize: 'medium',
              onTap: () => { this.showCreateDialog = false; }
            })
            GlassButton({
              text: '提交',
              type: 'primary',
              btnSize: 'medium',
              onTap: () => { this.submitCreate(); }
            })
              .margin({ left: this.sm.getSpacing('sm') })
          }
          .width('100%')
          .justifyContent(FlexAlign.End)
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
