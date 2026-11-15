/**
 * MemorySettingsPage - 记忆设置页
 *
 * 职责：记忆设置表单（容量、保留天数、温度阈值滑块、自动归档开关、自动遗忘开关、索引字段多选）
 * 设计：
 *   - MemorySettingsViewHelper（导出）：纯视图模型，封装容量颜色映射、容量格式化、
 *     保留天数格式化、温度阈值颜色、温度阈值格式化（1 位小数）、索引字段列表格式化，
 *     无 UI 依赖，可独立单元测试；
 *   - MemorySettingsPage（@Component）：Stack [主内容列]
 *     主内容列：TopNavMenu(标题"记忆设置"+返回+保存) + [加载态/表单]；
 *     表单：容量输入、保留天数输入、温度阈值滑块、自动归档开关、自动遗忘开关、
 *     索引字段多选（点击切换选中状态）；
 *   - 颜色统一走 StyleManager（返回 token 名），路由走 Router，
 *     API 暂无记忆设置专用模块 → aboutToAppear 加载 mock 静态数据 + TODO M6 接入真实 API。
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassCard、GlassButton、GlassInput
 *   - ../libs/api/ApiFacade：统一 API 门面（仅作为占位，未实际调用）
 *   - ../libs/state/stores/AgentsStore：Agent 状态（currentAgentId）
 *   - ../routing/Router：统一路由跳转
 *   - ../libs/style/StyleManager：统一样式 token
 *   - ../libs/logger/Logger：统一日志
 *   - ../libs/message/MessageManager：统一消息提示
 *   - ../libs/types：MemorySettings
 *
 * 用法：
 *   由 Router.push(RouteNames.MEMORY_SETTINGS) 跳转进入；
 *   aboutToAppear 加载当前 Agent 的记忆设置（TODO M6 接入真实 API api.memorySettings.*）；
 *   修改表单 → 保存按钮 → TODO M6 接入 api.memorySettings.update。
 *
 * TDD：MemorySettingsViewHelper 各方法按红绿灯垂直切片逐步实现，详见 MemorySettingsPage.test.ets
 */

import { TopNavMenu, GlassCard, GlassButton, GlassInput } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { AgentsStore } from '../libs/state/stores/AgentsStore';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { MemorySettings } from '../libs/types';

/** 日志标签 */
const TAG = 'MemorySettingsPage';

/** 可选索引字段列表 */
const AVAILABLE_INDEXED_FIELDS: string[] = ['content', 'tags', 'type', 'source', 'timestamp'];

/** 默认记忆设置（用于新建 Agent） */
const DEFAULT_SETTINGS: MemorySettings = {
  agentId: '',
  enabled: true,
  capacity: 1000,
  retentionDays: 30,
  temperatureThreshold: 0.5,
  autoArchive: true,
  autoForget: false,
  indexedFields: ['content', 'tags'],
  updatedAt: '',
};

// ===========================================================================
// MemorySettingsViewHelper - 记忆设置视图模型（纯函数，无 UI 依赖，可独立单元测试）
//
// 设计：所有方法为 static，输入 → 输出，无副作用；
//       颜色方法返回 StyleManager 的 token 名（如 'warning'），由页面解析为实际颜色值；
//       通过本文件 export，供 ohosTest 直接导入测试
// ===========================================================================

export class MemorySettingsViewHelper {
  /**
   * 获取容量对应的颜色 token 名
   * 规则：< 100 → error；100-1000 → warning；> 1000 → success
   * @param capacity 容量数值
   * @return StyleManager 颜色 token 名
   */
  static getCapacityColor(capacity: number): string {
    if (capacity < 100) return 'error';
    if (capacity > 1000) return 'success';
    return 'warning';
  }

  /**
   * 格式化容量
   * 规则：返回 "N 条"
   * @param capacity 容量数值
   * @return 容量文案
   */
  static formatCapacity(capacity: number): string {
    return `${capacity} 条`;
  }

  /**
   * 格式化保留天数
   * 规则：0 → "永久保留"；非零 → "N 天"
   * @param days 保留天数
   * @return 保留天数文案
   */
  static formatRetentionDays(days: number): string {
    if (days === 0) return '永久保留';
    return `${days} 天`;
  }

  /**
   * 获取温度阈值对应的颜色 token 名
   * 规则：< 0.3 → info；0.3-0.7 → warning；> 0.7 → error
   * @param threshold 温度阈值（0-1）
   * @return StyleManager 颜色 token 名
   */
  static getTemperatureColor(threshold: number): string {
    if (threshold < 0.3) return 'info';
    if (threshold > 0.7) return 'error';
    return 'warning';
  }

  /**
   * 格式化温度阈值（1 位小数）
   * 规则：返回 "0.X" 格式
   * @param threshold 温度阈值（0-1）
   * @return 温度阈值文案
   */
  static formatTemperature(threshold: number): string {
    return threshold.toFixed(1);
  }

  /**
   * 格式化索引字段列表
   * 规则：空数组 → "未索引"；1 个 → 字段名；多个 → "f1, f2 等 N 项"（最多显示 2 个）
   * @param fields 索引字段数组
   * @return 索引字段文案
   */
  static formatIndexedFields(fields: string[]): string {
    if (fields.length === 0) return '未索引';
    if (fields.length === 1) return fields[0];
    const first2 = fields.slice(0, 2).join(', ');
    return `${first2} 等 ${fields.length} 项`;
  }
}

/**
 * Mock 记忆设置数据
 * TODO M6 阶段：替换为 api.memorySettings.get(agentId) 真实 API
 */
const MOCK_SETTINGS: MemorySettings = {
  agentId: 'agent_1',
  enabled: true,
  capacity: 1000,
  retentionDays: 30,
  temperatureThreshold: 0.5,
  autoArchive: true,
  autoForget: false,
  indexedFields: ['content', 'tags'],
  updatedAt: '2025-06-01T00:00:00Z',
};

@Component
export struct MemorySettingsPage {
  // 记忆设置（嵌套属性变更需整体重新赋值）
  @State settings: MemorySettings = { ...DEFAULT_SETTINGS };
  // 加载态
  @State loading: boolean = true;
  // 当前 Agent ID
  @State agentId: string = '';

  // 统一库单例
  private api = ApiFacade.getInstance();
  private agentsStore = new AgentsStore();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private msg = MessageManager.getInstance();

  aboutToAppear() {
    this.loadSettings();
  }

  /**
   * 加载当前 Agent 的记忆设置
   * TODO M6 阶段：替换为真实 API（api.memorySettings.get）
   */
  private async loadSettings(): Promise<void> {
    this.loading = true;
    try {
      this.agentId = this.agentsStore.currentAgentId || '';
      // TODO M6 阶段补充真实 API
      // const res = await this.api.memorySettings.get(this.agentId);
      // if (res.code === 0 && res.data) { this.settings = res.data; }
      this.settings = { ...MOCK_SETTINGS, agentId: this.agentId };
    } catch (e) {
      this.logger.error(TAG, '加载记忆设置失败', e as Error);
      this.msg.error('加载记忆设置失败');
    } finally {
      this.loading = false;
    }
  }

  /**
   * 保存设置
   * TODO M6 阶段：调用真实 API（api.memorySettings.update）
   */
  private async saveSettings(): Promise<void> {
    try {
      // TODO M6 阶段：const res = await this.api.memorySettings.update(this.agentId, this.settings);
      this.msg.success('保存成功');
    } catch (e) {
      this.logger.error(TAG, '保存记忆设置失败', e as Error);
      this.msg.error('保存失败');
    }
  }

  /** 切换 enabled（嵌套属性变更：整体重新赋值） */
  private toggleEnabled(): void {
    this.settings = { ...this.settings, enabled: !this.settings.enabled };
  }

  /** 输入容量（嵌套属性变更：整体重新赋值） */
  private inputCapacity(v: string): void {
    const n = parseInt(v, 10);
    this.settings = { ...this.settings, capacity: isNaN(n) ? 0 : n };
  }

  /** 输入保留天数（嵌套属性变更：整体重新赋值） */
  private inputRetentionDays(v: string): void {
    const n = parseInt(v, 10);
    this.settings = { ...this.settings, retentionDays: isNaN(n) ? 0 : Math.max(0, n) };
  }

  /** 滑动温度阈值（嵌套属性变更：整体重新赋值） */
  private slideTemperature(value: number): void {
    this.settings = { ...this.settings, temperatureThreshold: value };
  }

  /** 切换 autoArchive（嵌套属性变更：整体重新赋值） */
  private toggleAutoArchive(): void {
    this.settings = { ...this.settings, autoArchive: !this.settings.autoArchive };
  }

  /** 切换 autoForget（嵌套属性变更：整体重新赋值） */
  private toggleAutoForget(): void {
    this.settings = { ...this.settings, autoForget: !this.settings.autoForget };
  }

  /**
   * 切换索引字段选中状态（嵌套属性变更：整体重新赋值）
   * 规则：已选中则移除；未选中则追加
   */
  private toggleIndexedField(field: string): void {
    const fields = this.settings.indexedFields.slice();
    const idx = fields.indexOf(field);
    if (idx >= 0) {
      fields.splice(idx, 1);
    } else {
      fields.push(field);
    }
    this.settings = { ...this.settings, indexedFields: fields };
  }

  build() {
    Stack() {
      Column() {
        // 顶部导航栏：标题"记忆设置" + 返回 + 保存
        TopNavMenu({
          title: '记忆设置',
          showBack: true,
          showMenu: false,
          onBack: () => { this.router.back(); }
        }) {
          GlassButton({
            text: '保存',
            type: 'primary',
            size: 'small',
            onClick: () => { this.saveSettings(); }
          })
        }

        // 主体内容：加载态 / 表单 二选一
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
        } else {
          Scroll() {
            Column() {
              // 启用开关
              this.buildEnabledRow()
              // 容量
              this.buildCapacityRow()
              // 保留天数
              this.buildRetentionDaysRow()
              // 温度阈值
              this.buildTemperatureRow()
              // 自动归档
              this.buildAutoArchiveRow()
              // 自动遗忘
              this.buildAutoForgetRow()
              // 索引字段
              this.buildIndexedFieldsRow()
            }
            .width('100%')
            .padding({
              left: this.sm.getSpacing('md'),
              right: this.sm.getSpacing('md'),
              top: this.sm.getSpacing('sm'),
              bottom: this.sm.getSpacing('sm'),
            })
            .alignItems(HorizontalAlign.Start)
          }
          .layoutWeight(1)
          .width('100%')
          .scrollBar(BarState.Off)
        }
      }
      .width('100%')
      .height('100%')
      .backgroundColor(this.sm.getColor('background'))
    }
    .width('100%')
    .height('100%')
  }

  // ===========================================================================
  // 表单行构建器
  // ===========================================================================

  /** 启用开关行 */
  @Builder
  buildEnabledRow() {
    GlassCard() {
      Row() {
        Column() {
          Text('启用记忆')
            .fontSize(this.sm.getFontSize('body'))
            .fontColor(this.sm.getColor('text_primary'))
          Text('关闭后将不再记录新记忆')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .margin({ top: 2 })
        }
        .alignItems(HorizontalAlign.Start)
        .layoutWeight(1)

        Toggle({ type: ToggleType.Switch, isOn: this.settings.enabled })
          .onChange((isOn: boolean) => { this.toggleEnabled(); })
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)
    }
    .width('100%')
    .margin({ bottom: 12 })
  }

  /** 容量行 */
  @Builder
  buildCapacityRow() {
    GlassCard() {
      Column() {
        Row() {
          Text('容量')
            .fontSize(this.sm.getFontSize('body'))
            .fontColor(this.sm.getColor('text_primary'))
            .layoutWeight(1)

          // 容量徽章（颜色根据容量大小）
          Text(MemorySettingsViewHelper.formatCapacity(this.settings.capacity))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_on_primary'))
            .padding({ left: 8, right: 8, top: 2, bottom: 2 })
            .borderRadius(10)
            .backgroundColor(this.sm.getColor(MemorySettingsViewHelper.getCapacityColor(this.settings.capacity)))
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)

        GlassInput({
          placeholder: '请输入容量（条数）',
          value: this.settings.capacity.toString(),
          type: 'number',
          onChange: (v: string) => { this.inputCapacity(v); },
        })
          .margin({ top: this.sm.getSpacing('sm') })
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
    .width('100%')
    .margin({ bottom: 12 })
  }

  /** 保留天数行 */
  @Builder
  buildRetentionDaysRow() {
    GlassCard() {
      Column() {
        Row() {
          Text('保留天数')
            .fontSize(this.sm.getFontSize('body'))
            .fontColor(this.sm.getColor('text_primary'))
            .layoutWeight(1)

          Text(MemorySettingsViewHelper.formatRetentionDays(this.settings.retentionDays))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)

        GlassInput({
          placeholder: '请输入保留天数（0 = 永久）',
          value: this.settings.retentionDays.toString(),
          type: 'number',
          onChange: (v: string) => { this.inputRetentionDays(v); },
        })
          .margin({ top: this.sm.getSpacing('sm') })
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
    .width('100%')
    .margin({ bottom: 12 })
  }

  /** 温度阈值行（滑块） */
  @Builder
  buildTemperatureRow() {
    GlassCard() {
      Column() {
        Row() {
          Text('温度阈值')
            .fontSize(this.sm.getFontSize('body'))
            .fontColor(this.sm.getColor('text_primary'))
            .layoutWeight(1)

          Text(MemorySettingsViewHelper.formatTemperature(this.settings.temperatureThreshold))
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontWeight(FontWeight.Bold)
            .fontColor(this.sm.getColor(MemorySettingsViewHelper.getTemperatureColor(this.settings.temperatureThreshold)))
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)

        // 滑块
        Slider({
          value: this.settings.temperatureThreshold,
          min: 0,
          max: 1,
          step: 0.1,
        })
          .width('100%')
          .margin({ top: this.sm.getSpacing('sm') })
          .onChange((value: number, mode: SliderChangeMode) => {
            this.slideTemperature(value);
          })
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
    .width('100%')
    .margin({ bottom: 12 })
  }

  /** 自动归档行 */
  @Builder
  buildAutoArchiveRow() {
    GlassCard() {
      Row() {
        Column() {
          Text('自动归档')
            .fontSize(this.sm.getFontSize('body'))
            .fontColor(this.sm.getColor('text_primary'))
          Text('超过保留天数的记忆自动归档')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .margin({ top: 2 })
        }
        .alignItems(HorizontalAlign.Start)
        .layoutWeight(1)

        Toggle({ type: ToggleType.Switch, isOn: this.settings.autoArchive })
          .onChange((isOn: boolean) => { this.toggleAutoArchive(); })
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)
    }
    .width('100%')
    .margin({ bottom: 12 })
  }

  /** 自动遗忘行 */
  @Builder
  buildAutoForgetRow() {
    GlassCard() {
      Row() {
        Column() {
          Text('自动遗忘')
            .fontSize(this.sm.getFontSize('body'))
            .fontColor(this.sm.getColor('text_primary'))
          Text('低于温度阈值的记忆自动遗忘')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .margin({ top: 2 })
        }
        .alignItems(HorizontalAlign.Start)
        .layoutWeight(1)

        Toggle({ type: ToggleType.Switch, isOn: this.settings.autoForget })
          .onChange((isOn: boolean) => { this.toggleAutoForget(); })
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)
    }
    .width('100%')
    .margin({ bottom: 12 })
  }

  /** 索引字段行（多选） */
  @Builder
  buildIndexedFieldsRow() {
    GlassCard() {
      Column() {
        Row() {
          Text('索引字段')
            .fontSize(this.sm.getFontSize('body'))
            .fontColor(this.sm.getColor('text_primary'))
            .layoutWeight(1)

          Text(MemorySettingsViewHelper.formatIndexedFields(this.settings.indexedFields))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)

        // 可选字段列表（点击切换选中状态）
        Flex({ wrap: FlexWrap.Wrap }) {
          ForEach(AVAILABLE_INDEXED_FIELDS, (field: string) => {
            Text(field)
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.settings.indexedFields.indexOf(field) >= 0
                ? this.sm.getColor('text_on_primary')
                : this.sm.getColor('text_primary'))
              .padding({ left: 10, right: 10, top: 4, bottom: 4 })
              .borderRadius(12)
              .backgroundColor(this.settings.indexedFields.indexOf(field) >= 0
                ? this.sm.getColor('primary')
                : this.sm.getColor('divider'))
              .margin({ right: 8, top: 8 })
              .onClick(() => { this.toggleIndexedField(field); })
          }, (field: string) => field)
        }
        .width('100%')
        .margin({ top: this.sm.getSpacing('sm') })
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
    .width('100%')
  }
}
