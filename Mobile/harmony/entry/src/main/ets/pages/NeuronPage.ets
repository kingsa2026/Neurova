/**
 * NeuronPage - NEURON 实体页（M9.2 监控域契约迁移）
 *
 * 职责：展示 NEURON 依赖图谱实体列表（GET /v1/neuron/entities，真实端点），
 *   按 entity_type 筛选，显示图谱统计（/v1/neuron/stats），支持新建实体
 *   （POST /v1/neuron/entities）与详情查看。
 * 设计：
 *   - NeuronViewHelper（导出）：纯视图模型（保留名称截断等纯函数，供 ohosTest 回归），
 *     无 UI 运行时依赖；
 *   - NeuronPage（@Component）：Stack[Column[TopNavMenu(标题"神经元"+返回+新建)]
 *     + [图谱统计条] + [entity_type 筛选输入]
 *     + [加载态/错误态/空态/列表] + [详情弹窗] + [新建弹窗]]；
 *     列表项 GlassCard 含实体名、类型徽章、ID、创建时间；
 *   - 旧页面渲染的 activation/threshold/放电（fireNeuron）为已退役的虚构契约——
 *     后端 /v1/neuron 无这些字段与端点，本页不再展示。
 *   - 颜色统一走 StyleManager（返回 token 名），路由走 Router，
 *     API 走 ApiFacade.monitor（listNeurons/getNeuronStats/createNeuronEntity），
 *     消息走 MessageManager
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassCard、GlassButton、GlassInput、GlassPanel
 *   - ../libs/api/ApiFacade：统一 API 门面（monitor 模块）
 *   - ../libs/api/modules/MonitorApi：NEURON 真实 DTO
 *   - ../routing/Router：统一路由跳转
 *   - ../libs/style/StyleManager：统一样式 token
 *   - ../libs/logger/Logger：统一日志
 *   - ../libs/message/MessageManager：统一消息提示
 *
 * 用法：
 *   由 Router.push 跳转进入；
 *   aboutToAppear 调用 api.monitor.listNeurons + getNeuronStats 加载；
 *   entity_type 筛选 → 重新加载；新建按钮 → 弹窗填 name/entity_type → 创建
 *
 * TDD：NeuronViewHelper 各方法按红绿灯垂直切片逐步实现，详见 NeuronPage.test.ets
 */

import { TopNavMenu, GlassCard, GlassButton, GlassInput, GlassPanel } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { NeuronEntityDto, NeuronStatsDto } from '../libs/api/modules/MonitorApi';

/** 日志标签 */
const TAG = 'NeuronPage';

/** 默认神经元名称截断长度（神经元页为 100 字符） */
const DEFAULT_TRUNCATE_LEN = 100;

// ===========================================================================
// NeuronViewHelper - 神经元视图模型（纯函数，无 UI 依赖，可独立单元测试）
//
// 设计：所有方法为 static，输入 → 输出，无副作用；
//       颜色方法返回 StyleManager 的 token 名（'info'/'success'/'error'/
//   'warning'/'text_secondary'），由页面解析为实际颜色值；
//       通过本文件 export，供 ohosTest 直接导入测试
// ===========================================================================

export class NeuronViewHelper {
  /**
   * 获取神经元状态对应的颜色 token 名
   * 映射：idle→text_secondary, active→info, firing→success, inhibited→error
   * @param state 神经元状态
   * @return StyleManager 颜色 token 名
   */
  static getStateColor(state: string): string {
    if (state === 'idle') return 'text_secondary';
    if (state === 'active') return 'info';
    if (state === 'firing') return 'success';
    return 'error';
  }

  /**
   * 获取神经元状态对应的图标 emoji
   * 映射：idle→💤, active→⚡, firing→🔥, inhibited→🚫
   * @param state 神经元状态
   * @return emoji 字符串
   */
  static getStateIcon(state: string): string {
    if (state === 'idle') return '💤';
    if (state === 'active') return '⚡';
    if (state === 'firing') return '🔥';
    return '🚫';
  }

  /**
   * 获取神经元状态对应的中文标签
   * 映射：idle→空闲, active→活跃, firing→激发, inhibited→抑制
   * @param state 神经元状态
   * @return 中文标签
   */
  static getStateLabel(state: string): string {
    if (state === 'idle') return '空闲';
    if (state === 'active') return '活跃';
    if (state === 'firing') return '激发';
    return '抑制';
  }

  /**
   * 格式化激活值为百分比字符串
   * 规则：
   *   - activation 范围 [0, 1]，超出则截断到边界
   *   - 保留 1 位小数，格式 "XX.X%"
   * @param activation 激活值（0-1）
   * @return 百分比字符串
   */
  static formatActivation(activation: number): string {
    // 截断到 [0, 1] 范围
    const clamped = Math.max(0, Math.min(1, activation));
    const percent = clamped * 100;
    return `${percent.toFixed(1)}%`;
  }

  /**
   * 获取激活进度条对应的颜色 token 名（按激活值分级）
   * 映射：
   *   - <0.3 → info（低激活，蓝色）
   *   - 0.3~0.7 → warning（中激活，黄色）
   *   - >0.7 → success（高激活，绿色）
   * @param activation 激活值（0-1）
   * @return StyleManager 颜色 token 名
   */
  static getActivationBarColor(activation: number): string {
    if (activation < 0.3) return 'info';
    if (activation > 0.7) return 'success';
    return 'warning';
  }

  /**
   * 截断神经元名称
   * 规则：
   *   - name 为空 → 原样返回
   *   - 长度 ≤ maxLen → 原样返回
   *   - 长度 > maxLen → 截取前 maxLen 字符并追加省略号 "..."
   * @param name 神经元名称
   * @param maxLen 最大长度，默认 100
   * @return 截断后的名称
   */
  static truncateNeuronName(name: string, maxLen?: number): string {
    const len = maxLen !== undefined ? maxLen : DEFAULT_TRUNCATE_LEN;
    if (!name || name.length === 0) return name;
    if (name.length <= len) return name;
    return name.substring(0, len) + '...';
  }
}

/** 新建实体表单数据 */
interface EntityFormData {
  name: string;
  entityType: string;
}

@Component
export struct NeuronPage {
  // 实体列表（/v1/neuron/entities 真实数据）
  @State entities: NeuronEntityDto[] = [];
  // 图谱统计（/v1/neuron/stats）
  @State stats: NeuronStatsDto | undefined = undefined;
  // 加载态
  @State loading: boolean = true;
  // 错误文案（非空时显示错误态）
  @State errorMsg: string = '';
  // entity_type 筛选输入值
  @State entityTypeFilter: string = '';
  // 详情弹窗显示状态
  @State showDetailDialog: boolean = false;
  // 当前查看详情的实体
  @State currentEntity: NeuronEntityDto | undefined = undefined;
  // 新建弹窗显示状态
  @State showCreateDialog: boolean = false;
  // 新建表单
  @State formData: EntityFormData = { name: '', entityType: '' };

  // 统一库单例
  private api = ApiFacade.getInstance();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private msg = MessageManager.getInstance();

  aboutToAppear() {
    this.loadEntities();
  }

  /**
   * 加载实体列表 + 图谱统计
   * 流程：调用 api.monitor.listNeurons / getNeuronStats → 写入状态
   * 异常：记录日志并把后端原因透出到错误态
   */
  private async loadEntities(): Promise<void> {
    this.loading = true;
    this.errorMsg = '';
    try {
      const entityType = this.entityTypeFilter.length > 0 ? this.entityTypeFilter : undefined;
      const res = await this.api.monitor.listNeurons(entityType, { page: 1, size: 200 });
      this.entities = res.data ?? [];
      const statsRes = await this.api.monitor.getNeuronStats();
      this.stats = statsRes.data;
    } catch (e) {
      this.logger.error(TAG, '加载 NEURON 实体失败', e as Error);
      this.errorMsg = (e as Error).message.length > 0 ? (e as Error).message : '加载实体列表失败';
    } finally {
      this.loading = false;
    }
  }

  /** entity_type 筛选输入变更 */
  private onFilterChange(v: string): void {
    this.entityTypeFilter = v;
  }

  /** 触发筛选（重新加载） */
  private applyFilter(): void {
    this.loadEntities();
  }

  /** 打开详情弹窗 */
  private openDetail(n: NeuronEntityDto): void {
    this.currentEntity = n;
    this.showDetailDialog = true;
  }

  /** 关闭详情弹窗 */
  private closeDetail(): void {
    this.showDetailDialog = false;
    this.currentEntity = undefined;
  }

  /** 打开新建弹窗，重置表单 */
  private openCreateDialog(): void {
    this.formData = { name: '', entityType: '' };
    this.showCreateDialog = true;
  }

  /**
   * 提交新建实体（POST /v1/neuron/entities，真实端点）
   * 异常：记录日志并把后端原因透出
   */
  private async submitCreate(): Promise<void> {
    if (this.formData.name.length === 0) {
      this.msg.warning('请填写实体名称');
      return;
    }
    if (this.formData.entityType.length === 0) {
      this.msg.warning('请填写实体类型');
      return;
    }
    try {
      const metadata: Record<string, Object> = {};
      await this.api.monitor.createNeuronEntity(this.formData.name, this.formData.entityType, metadata);
      this.msg.success('实体创建成功');
      this.showCreateDialog = false;
      this.loadEntities();
    } catch (e) {
      this.logger.error(TAG, '创建实体失败', e as Error);
      this.msg.error((e as Error).message.length > 0 ? (e as Error).message : '创建实体失败');
    }
  }

  /** 格式化 epoch 秒为本地日期时间 */
  private formatEpoch(seconds: number): string {
    if (seconds <= 0) return '-';
    const d = new Date(seconds * 1000);
    const mm = (d.getMonth() + 1).toString().padStart(2, '0');
    const dd = d.getDate().toString().padStart(2, '0');
    const hh = d.getHours().toString().padStart(2, '0');
    const mi = d.getMinutes().toString().padStart(2, '0');
    return `${d.getFullYear()}-${mm}-${dd} ${hh}:${mi}`;
  }

  /** metadata 键清单（弹窗展示用） */
  private metadataKeys(metadata: Record<string, Object>): string {
    const keys = Object.keys(metadata);
    if (keys.length === 0) return '无';
    return keys.join('、');
  }

  build() {
    Stack({ alignContent: Alignment.Center }) {
      Column() {
        // 顶部导航栏：标题"神经元" + 返回按钮 + 新建按钮
        TopNavMenu({
          title: '神经元',
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

        // 图谱统计条（/v1/neuron/stats）
        if (this.stats !== undefined) {
          Row({ space: 12 }) {
            Text(`实体 ${this.stats.total_entities}`)
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('info'))
            Text(`关系 ${this.stats.total_edges}`)
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('success'))
            Text(`实体类型 ${this.stats.entity_types}`)
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('warning'))
            Text(`依赖类型 ${this.stats.dependency_types}`)
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
          }
          .width('100%')
          .justifyContent(FlexAlign.Center)
          .padding({ top: 6, bottom: 6 })
        }

        // entity_type 筛选输入 + 筛选按钮
        Row({ space: 8 }) {
          GlassInput({
            placeholder: '按 entity_type 筛选',
            value: this.entityTypeFilter,
            type: 'text',
            onChange: (v: string) => { this.onFilterChange(v); }
          })
            .layoutWeight(1)
          GlassButton({
            text: '筛选',
            type: 'default',
            btnSize: 'small',
            onTap: () => { this.applyFilter(); }
          })
        }
        .width('100%')
        .padding({ left: this.sm.getSpacing('md'), right: this.sm.getSpacing('md'), top: 4, bottom: 4 })
        .alignItems(VerticalAlign.Center)

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
        } else if (this.errorMsg.length > 0) {
          Column() {
            Text('实体列表加载失败')
              .fontSize(this.sm.getFontSize('subtitle'))
              .fontColor(this.sm.getColor('error'))
            Text(this.errorMsg)
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .margin({ top: 8 })
            GlassButton({
              text: '重试',
              type: 'default',
              btnSize: 'small',
              onTap: () => { this.loadEntities(); }
            })
              .margin({ top: 12 })
          }
          .width('90%')
          .layoutWeight(1)
          .justifyContent(FlexAlign.Center)
          .alignItems(HorizontalAlign.Center)
        } else if (this.entities.length === 0) {
          Column() {
            Text('暂无实体')
              .fontSize(this.sm.getFontSize('subtitle'))
              .fontColor(this.sm.getColor('text_secondary'))
          }
          .width('100%')
          .layoutWeight(1)
          .justifyContent(FlexAlign.Center)
          .alignItems(HorizontalAlign.Center)
        } else {
          List({ space: 12 }) {
            ForEach(this.entities, (n: NeuronEntityDto) => {
              ListItem() {
                this.buildEntityCard(n)
              }
            }, (n: NeuronEntityDto) => n.id)
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

      // 详情弹窗：内嵌 Stack 条件渲染
      if (this.showDetailDialog) {
        this.buildDetailDialog()
      }

      // 新建弹窗：内嵌 Stack 条件渲染
      if (this.showCreateDialog) {
        this.buildCreateDialog()
      }
    }
    .width('100%')
    .height('100%')
  }

  // ===========================================================================
  // 实体卡片构建器
  // ===========================================================================

  /** 单个实体卡片：类型徽章 + 名称 + ID + 创建时间 */
  @Builder
  buildEntityCard(n: NeuronEntityDto) {
    Column() {
    GlassCard() {
      Column() {
        // 上部：类型徽章 + 名称
        Row() {
          Text(n.entity_type)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('info'))
            .padding({ left: 8, right: 8, top: 2, bottom: 2 })
            .backgroundColor(this.sm.getColor('surface'))
            .borderRadius(10)

          Text(NeuronViewHelper.truncateNeuronName(n.name, DEFAULT_TRUNCATE_LEN))
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontWeight(FontWeight.Bold)
            .fontColor(this.sm.getColor('text_primary'))
            .margin({ left: 8 })
            .layoutWeight(1)
            .maxLines(2)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)

        // ID + 创建时间
        Text(`ID：${n.id}`)
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('text_secondary'))
          .margin({ top: 4 })
        Text(`创建：${this.formatEpoch(n.created_at)}`)
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('text_secondary'))
          .margin({ top: 4 })

        // 查看详情按钮
        GlassButton({
          text: '查看详情',
          type: 'default',
          btnSize: 'small',
          onTap: () => { this.openDetail(n); }
        })
          .margin({ top: this.sm.getSpacing('md') })
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
    }
    .width('100%')
    .onClick(() => { this.openDetail(n); })
  }

  // ===========================================================================
  // 详情弹窗构建器
  // ===========================================================================

  /** 实体详情弹窗：名称/ID/类型/创建更新时间/metadata 键 */
  @Builder
  buildDetailDialog() {
    Stack({ alignContent: Alignment.Center }) {
      // 背景遮罩层
      Column()
        .width('100%')
        .height('100%')
        .backgroundColor(this.sm.getColor('overlay_mask'))
        .onClick(() => { this.closeDetail(); })

      // 面板层
      Column() {
      GlassPanel({ variant: 'elevated', innerPadding: 20 }) {
        Scroll() {
          Column() {
            Text('实体详情')
              .fontSize(this.sm.getFontSize('subtitle'))
              .fontWeight(FontWeight.Bold)
              .fontColor(this.sm.getColor('text_primary'))
              .width('100%')

            if (this.currentEntity !== undefined) {
              Text(`名称：${this.currentEntity.name}`)
                .fontSize(this.sm.getFontSize('body'))
                .fontColor(this.sm.getColor('text_primary'))
                .width('100%')
                .margin({ top: 8 })

              Text(`ID：${this.currentEntity.id}`)
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.sm.getColor('text_secondary'))
                .width('100%')
                .margin({ top: 4 })

              Text(`类型：${this.currentEntity.entity_type}`)
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.sm.getColor('text_secondary'))
                .width('100%')
                .margin({ top: 4 })

              Text(`创建：${this.formatEpoch(this.currentEntity.created_at)}`)
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.sm.getColor('text_secondary'))
                .width('100%')
                .margin({ top: 4 })

              Text(`更新：${this.formatEpoch(this.currentEntity.updated_at)}`)
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.sm.getColor('text_secondary'))
                .width('100%')
                .margin({ top: 4 })

              Text(`metadata：${this.metadataKeys(this.currentEntity.metadata)}`)
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.sm.getColor('text_secondary'))
                .width('100%')
                .margin({ top: 4 })
            }

            // 操作按钮
            Row() {
              GlassButton({
                text: '关闭',
                type: 'default',
                btnSize: 'medium',
                onTap: () => { this.closeDetail(); }
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
        .scrollBar(BarState.Off)
      }
      }
      .width('90%')
      .height('80%')
    }
    .width('100%')
    .height('100%')
  }

  // ===========================================================================
  // 新建弹窗构建器
  // ===========================================================================

  /** 新建实体弹窗：name + entity_type（POST /v1/neuron/entities） */
  @Builder
  buildCreateDialog() {
    Stack({ alignContent: Alignment.Center }) {
      // 背景遮罩层：点击空白处关闭
      Column()
        .width('100%')
        .height('100%')
        .backgroundColor(this.sm.getColor('overlay_mask'))
        .onClick(() => { this.showCreateDialog = false; })

      // 面板层：居中展示
      Column() {
      GlassPanel({ variant: 'elevated', innerPadding: 20 }) {
        Column() {
          Text('新建实体')
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontWeight(FontWeight.Bold)
            .fontColor(this.sm.getColor('text_primary'))
            .width('100%')

          // 实体名称
          Text('实体名称')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .width('100%')
            .margin({ top: this.sm.getSpacing('sm') })
          GlassInput({
            placeholder: '请输入实体名称',
            value: this.formData.name,
            type: 'text',
            onChange: (v: string) => { this.formData = { name: v, entityType: this.formData.entityType }; }
          })
            .margin({ top: 4 })

          // 实体类型
          Text('实体类型')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .width('100%')
            .margin({ top: this.sm.getSpacing('sm') })
          GlassInput({
            placeholder: '如 service / component / person',
            value: this.formData.entityType,
            type: 'text',
            onChange: (v: string) => { this.formData = { name: this.formData.name, entityType: v }; }
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
