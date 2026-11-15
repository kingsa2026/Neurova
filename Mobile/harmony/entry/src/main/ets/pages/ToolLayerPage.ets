/**
 * ToolLayerPage - 工具层管理页
 *
 * 职责：展示工具层列表，启用/禁用、调整优先级、查看工具
 * 设计：
 *   - ToolLayerViewHelper（导出）：纯视图模型，封装启用状态颜色映射、启用状态图标、启用状态文案、
 *     优先级格式化、工具数格式化、描述截断（默认 80），无 UI 依赖，可独立单元测试；
 *   - ToolLayerPage（@Component）：Stack [主内容列] + [新建 CustomDialog]
 *     主内容列：TopNavMenu(标题"工具层"+返回+新建) + [加载态/空态/列表]；
 *     列表项 GlassCard（可展开/折叠）：name、description、enabled toggle、priority、tools 数量、
 *     展开后显示 tools 数组列表；
 *     新建 CustomDialog：name 输入、description 输入、priority 数字；
 *   - 颜色统一走 StyleManager，路由走 Router，API 暂无工具层专用模块 →
 *     aboutToAppear 加载 mock 静态数据 + TODO 注释 M5 阶段补充真实 API。
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassCard、GlassButton、GlassInput、GlassPanel
 *   - ../libs/api/ApiFacade：统一 API 门面（仅作为占位，未实际调用）
 *   - ../routing/Router：统一路由跳转
 *   - ../libs/style/StyleManager：统一样式 token
 *   - ../libs/logger/Logger：统一日志
 *   - ../libs/message/MessageManager：统一消息提示
 *   - ../libs/types：ToolLayer
 *
 * 用法：
 *   由 Router.push(RouteNames.TOOL_LAYER) 跳转进入；
 *   aboutToAppear 加载 mock 工具层列表（TODO M5 接入真实 API）；
 *   展开/折叠卡片 → 切换 expandedLayerId；
 *   启用/禁用 → 本地切换 enabled + TODO M5 接入 API；
 *   新建 → 弹窗填写 name/description/priority → 提交 → TODO M5 接入 API。
 *
 * TDD：ToolLayerViewHelper 各方法按红绿灯垂直切片逐步实现，详见 ToolLayerPage.test.ets
 */

import { TopNavMenu, GlassCard, GlassButton, GlassInput, GlassPanel } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { ToolLayer } from '../libs/types';

/** 日志标签 */
const TAG = 'ToolLayerPage';

/** 描述截断默认最大长度 */
const DEFAULT_DESC_MAX_LEN = 80;

// ===========================================================================
// ToolLayerViewHelper - 工具层视图模型（纯函数，无 UI 依赖，可独立单元测试）
// ===========================================================================

export class ToolLayerViewHelper {
  /**
   * 获取启用状态对应的颜色 token 名
   * 映射：true→success，false→text_disabled
   */
  static getEnabledColor(enabled: boolean): string {
    if (enabled) return 'success';
    return 'text_disabled';
  }

  /**
   * 获取启用状态对应的图标 emoji
   * 映射：true→✅，false→❌
   */
  static getEnabledIcon(enabled: boolean): string {
    if (enabled) return '✅';
    return '❌';
  }

  /**
   * 获取启用状态对应的中文标签
   * 映射：true→已启用，false→已禁用
   */
  static getEnabledLabel(enabled: boolean): string {
    if (enabled) return '已启用';
    return '已禁用';
  }

  /**
   * 格式化优先级
   * 规则：返回 "优先级 {n}"
   */
  static formatPriority(priority: number): string {
    return `优先级 ${priority}`;
  }

  /**
   * 格式化工具数量
   * 规则：0 → "无工具"；非零 → "工具 {n} 个"
   */
  static formatToolCount(count: number): string {
    if (count === 0) return '无工具';
    return `工具 ${count} 个`;
  }

  /**
   * 截断描述，超长时截取 maxLen 字符并追加省略号
   * @param desc 原始描述
   * @param maxLen 最大字符数，默认 80
   * @return 截断后的描述；未超长则原样返回
   */
  static truncateDescription(desc: string, maxLen: number = DEFAULT_DESC_MAX_LEN): string {
    if (desc.length <= maxLen) return desc;
    return desc.substring(0, maxLen) + '...';
  }
}

/** 新建工具层表单数据 */
interface ToolLayerFormData {
  name: string;
  description: string;
  priority: number;
}

/** 默认表单数据 */
const DEFAULT_FORM: ToolLayerFormData = {
  name: '',
  description: '',
  priority: 1,
};

/**
 * Mock 工具层数据
 * TODO M5 阶段：替换为 api.tools.listLayers() 真实 API
 */
const MOCK_LAYERS: ToolLayer[] = [
  {
    id: 'layer_1',
    name: '核心工具层',
    description: '包含基础文件、搜索、计算等核心工具',
    enabled: true,
    tools: ['file_read', 'file_write', 'search', 'calculate'],
    priority: 1,
  },
  {
    id: 'layer_2',
    name: '网络工具层',
    description: 'HTTP 请求、爬虫、API 调用等网络相关工具',
    enabled: true,
    tools: ['http_get', 'http_post', 'crawl'],
    priority: 2,
  },
  {
    id: 'layer_3',
    name: '实验性工具层',
    description: '尚未稳定的高级工具，包含代码执行、shell 调用、数据库操作、文件系统监控、系统进程管理、定时任务调度、远程通信、加密解密、压缩归档、格式转换、数据清洗、可视化、机器学习推理、知识检索等（演示长描述截断功能）',
    enabled: false,
    tools: [],
    priority: 3,
  },
];

@Component
export struct ToolLayerPage {
  // 工具层列表
  @State layers: ToolLayer[] = [];
  // 加载态
  @State loading: boolean = true;
  // 当前展开的工具层 id（空串表示全部折叠）
  @State expandedLayerId: string = '';
  // 新建弹窗显示状态
  @State showCreateDialog: boolean = false;
  // 新建表单数据（嵌套属性变更需整体重新赋值）
  @State formData: ToolLayerFormData = { ...DEFAULT_FORM };

  // 统一库单例
  private api = ApiFacade.getInstance();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private msg = MessageManager.getInstance();

  aboutToAppear() {
    this.loadLayers();
  }

  /**
   * 加载工具层列表
   * TODO M5 阶段：替换为真实 API（api.tools.listLayers）
   */
  private async loadLayers(): Promise<void> {
    this.loading = true;
    try {
      // TODO M5 阶段补充真实 API
      // const res = await this.api.tools.listLayers();
      // if (res.code === 0 && res.data) { this.layers = res.data; }
      this.layers = MOCK_LAYERS.slice();
    } catch (e) {
      this.logger.error(TAG, '加载工具层失败', e as Error);
      this.msg.error('加载工具层列表失败');
    } finally {
      this.loading = false;
    }
  }

  /**
   * 切换工具层展开/折叠
   * 规则：再次点击同一层折叠；点击不同层切换展开
   */
  private toggleLayer(layerId: string): void {
    this.expandedLayerId = this.expandedLayerId === layerId ? '' : layerId;
  }

  /**
   * 切换启用/禁用
   * TODO M5 阶段：调用真实 API（api.tools.toggleLayer）
   * 当前为本地切换 enabled（嵌套属性变更需整体重新赋值）
   */
  private async toggleEnabled(layer: ToolLayer): Promise<void> {
    try {
      // TODO M5 阶段：const res = await this.api.tools.toggleLayer(layer.id, !layer.enabled);
      this.layers = this.layers.map((l: ToolLayer) => {
        if (l.id === layer.id) {
          return { ...l, enabled: !l.enabled };
        }
        return l;
      });
      this.msg.success(layer.enabled ? '已禁用' : '已启用');
    } catch (e) {
      this.logger.error(TAG, '切换启用失败', e as Error);
      this.msg.error('操作失败');
    }
  }

  /** 打开新建弹窗，重置表单 */
  private openCreateDialog(): void {
    this.formData = { ...DEFAULT_FORM };
    this.showCreateDialog = true;
  }

  /** 输入 name（嵌套属性变更：整体重新赋值） */
  private inputName(v: string): void {
    this.formData = { ...this.formData, name: v };
  }

  /** 输入 description（嵌套属性变更：整体重新赋值） */
  private inputDescription(v: string): void {
    this.formData = { ...this.formData, description: v };
  }

  /** 输入 priority（嵌套属性变更：整体重新赋值） */
  private inputPriority(v: string): void {
    const n = parseInt(v, 10);
    this.formData = { ...this.formData, priority: isNaN(n) ? 1 : n };
  }

  /**
   * 提交新建
   * TODO M5 阶段：调用真实 API（api.tools.createLayer）
   * 当前为本地追加 + TODO 提示
   */
  private async submitCreate(): Promise<void> {
    if (!this.formData.name.trim()) {
      this.msg.warning('请填写名称');
      return;
    }
    try {
      // TODO M5 阶段：const res = await this.api.tools.createLayer({...});
      const newLayer: ToolLayer = {
        id: `layer_${Date.now()}`,
        name: this.formData.name.trim(),
        description: this.formData.description.trim(),
        enabled: true,
        tools: [],
        priority: this.formData.priority,
      };
      this.layers = [...this.layers, newLayer];
      this.msg.success('已创建');
      this.showCreateDialog = false;
    } catch (e) {
      this.logger.error(TAG, '创建工具层失败', e as Error);
      this.msg.error('创建工具层失败');
    }
  }

  build() {
    Stack() {
      Column() {
        // 顶部导航栏：标题"工具层" + 返回 + 新建
        TopNavMenu({
          title: '工具层',
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
        } else if (this.layers.length === 0) {
          Column() {
            Text('暂无工具层')
              .fontSize(this.sm.getFontSize('subtitle'))
              .fontColor(this.sm.getColor('text_secondary'))
              .margin({ bottom: this.sm.getSpacing('md') })
            GlassButton({
              text: '新建工具层',
              type: 'primary',
              size: 'medium',
              onClick: () => { this.openCreateDialog(); }
            })
          }
          .width('100%')
          .layoutWeight(1)
          .justifyContent(FlexAlign.Center)
          .alignItems(HorizontalAlign.Center)
        } else {
          List({ space: 12 }) {
            ForEach(this.layers, (layer: ToolLayer) => {
              ListItem() {
                this.buildLayerCard(layer)
              }
            }, (layer: ToolLayer) => layer.id)
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

      // 新建工具层弹窗
      if (this.showCreateDialog) {
        this.buildCreateDialog()
      }
    }
    .width('100%')
    .height('100%')
  }

  // ===========================================================================
  // 工具层卡片构建器（可展开/折叠）
  // ===========================================================================

  /** 单个工具层卡片：name + description + enabled + priority + tools 数量 + 展开后 tools 列表 */
  @Builder
  buildLayerCard(layer: ToolLayer) {
    GlassCard() {
      Column() {
        // 顶部行：启用图标 + 名称 + 启用 toggle
        Row() {
          Text(ToolLayerViewHelper.getEnabledIcon(layer.enabled))
            .fontSize(20)
          Text(layer.name)
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontWeight(FontWeight.Bold)
            .fontColor(this.sm.getColor('text_primary'))
            .layoutWeight(1)
            .margin({ left: this.sm.getSpacing('sm') })
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
          Toggle({ type: ToggleType.Switch, isOn: layer.enabled })
            .onChange((isOn: boolean) => { this.toggleEnabled(layer); })
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)
        .onClick(() => { this.toggleLayer(layer.id); })

        // 描述（默认 80 字符截断）
        Text(ToolLayerViewHelper.truncateDescription(layer.description))
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('text_secondary'))
          .maxLines(2)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .margin({ top: this.sm.getSpacing('xs') })
          .width('100%')

        // 底部行：启用状态徽章 + 优先级 + 工具数量
        Row() {
          // 启用状态徽章
          Row() {
            Row()
              .width(8)
              .height(8)
              .borderRadius(4)
              .backgroundColor(this.sm.getColor(ToolLayerViewHelper.getEnabledColor(layer.enabled)))
            Text(ToolLayerViewHelper.getEnabledLabel(layer.enabled))
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor(ToolLayerViewHelper.getEnabledColor(layer.enabled)))
              .margin({ left: 4 })
          }
          .alignItems(VerticalAlign.Center)

          Text('·')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_disabled'))
            .margin({ left: this.sm.getSpacing('sm'), right: this.sm.getSpacing('sm') })

          Text(ToolLayerViewHelper.formatPriority(layer.priority))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))

          Text('·')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_disabled'))
            .margin({ left: this.sm.getSpacing('sm'), right: this.sm.getSpacing('sm') })

          Text(ToolLayerViewHelper.formatToolCount(layer.tools.length))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_disabled'))

          // 展开提示
          Text(this.expandedLayerId === layer.id ? '▲' : '▼')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_disabled'))
            .layoutWeight(1)
            .textAlign(TextAlign.End)
        }
        .width('100%')
        .margin({ top: this.sm.getSpacing('xs') })
        .alignItems(VerticalAlign.Center)

        // 展开后：tools 数组列表
        if (this.expandedLayerId === layer.id) {
          Column() {
            if (layer.tools.length === 0) {
              Text('该工具层暂无工具')
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.sm.getColor('text_disabled'))
                .margin({ top: this.sm.getSpacing('sm') })
            } else {
              ForEach(layer.tools, (tool: string) => {
                Row() {
                  Text('🔧')
                    .fontSize(14)
                    .margin({ right: 6 })
                  Text(tool)
                    .fontSize(this.sm.getFontSize('caption'))
                    .fontColor(this.sm.getColor('text_secondary'))
                    .layoutWeight(1)
                    .maxLines(1)
                    .textOverflow({ overflow: TextOverflow.Ellipsis })
                }
                .width('100%')
                .padding({ top: 6, bottom: 6 })
                .border({
                  width: { top: 0.5 },
                  color: this.sm.getColor('divider'),
                })
              }, (tool: string) => tool)
            }
          }
          .width('100%')
          .alignItems(HorizontalAlign.Start)
          .margin({ top: this.sm.getSpacing('sm') })
        }
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
    .width('100%')
  }

  // ===========================================================================
  // 新建工具层弹窗构建器（Stack 内嵌条件渲染）
  // ===========================================================================

  /** 新建工具层弹窗：name 输入 + description 输入 + priority 数字 */
  @Builder
  buildCreateDialog() {
    Stack({ alignContent: Alignment.Center }) {
      // 背景遮罩层
      Column()
        .width('100%')
        .height('100%')
        .backgroundColor(this.sm.getColor('overlay_mask'))
        .onClick(() => { this.showCreateDialog = false; })

      // 面板层
      GlassPanel({ variant: 'elevated', padding: 20 }) {
        Column() {
          Text('新建工具层')
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontWeight(FontWeight.Bold)
            .fontColor(this.sm.getColor('text_primary'))
            .width('100%')

          // 名称
          Text('名称')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .width('100%')
            .margin({ top: this.sm.getSpacing('sm') })
          GlassInput({
            placeholder: '请输入工具层名称',
            value: this.formData.name,
            type: 'text',
            onChange: (v: string) => { this.inputName(v); },
          })
            .margin({ top: 4, bottom: this.sm.getSpacing('sm') })

          // 描述
          Text('描述')
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

          // 优先级
          Text('优先级')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .width('100%')
          GlassInput({
            placeholder: '请输入优先级（数字）',
            value: this.formData.priority.toString(),
            type: 'number',
            onChange: (v: string) => { this.inputPriority(v); },
          })
            .margin({ top: 4, bottom: this.sm.getSpacing('md') })

          // 操作按钮
          Row() {
            GlassButton({
              text: '取消',
              type: 'default',
              size: 'medium',
              onClick: () => { this.showCreateDialog = false; }
            })
            GlassButton({
              text: '创建',
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
