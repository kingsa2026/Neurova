/**
 * CollaborationPage - 协作概览页
 *
 * 职责：协作功能概览入口页，展示项目/团队/任务统计卡 + 快捷入口按钮
 * 设计：
 *   - CollaborationViewHelper（导出）：纯视图模型，封装模块图标映射、模块标签映射、
 *     数量格式化、待办任务统计、模块颜色映射，无 UI 运行时依赖，可独立单元测试；
 *   - CollaborationPage（@Component）：Column[TopNavMenu(标题"协作"+返回)]
 *     + [加载态/空态/内容]；
 *     内容为 3 个 GlassCard 概览（项目数、团队数、待办任务数）+
 *     3 个快捷入口按钮（项目/团队/任务）；
 *     点击入口按钮跳转对应页面（路由待注册，当前以消息提示占位）；
 *   - 颜色统一走 StyleManager（返回 token 名），路由走 Router，
 *     API 走 ApiFacade.collaboration（listProjects/listTeams/listTasks），
 *     消息走 MessageManager
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassCard、GlassButton、GlassPanel
 *   - ../libs/api/ApiFacade：统一 API 门面（collaboration 模块）
 *   - ../routing/Router：统一路由跳转
 *   - ../libs/style/StyleManager：统一样式 token
 *   - ../libs/logger/Logger：统一日志
 *   - ../libs/message/MessageManager：统一消息提示
 *   - ../libs/types：Project、Team、Task
 *
 * 用法：
 *   由 Router.push 跳转进入；
 *   aboutToAppear 并行调用 api.collaboration.listProjects/listTeams/listTasks
 *   加载统计数据并展示；
 *   点击快捷入口按钮 → 跳转对应详情页（占位消息提示）
 *
 * TDD：CollaborationViewHelper 各方法按红绿灯垂直切片逐步实现，
 *      详见 CollaborationPage.test.ets
 */

import { TopNavMenu, GlassCard, GlassButton } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { Router, RouteNames } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { Task } from '../libs/types';
import { CollaborationStatsDto } from '../libs/api/modules/CollaborationApi';

/** 日志标签 */
const TAG = 'CollaborationPage';

// ===========================================================================
// CollaborationViewHelper - 协作概览视图模型（纯函数，无 UI 依赖，可独立单元测试）
//
// 设计：所有方法为 static，输入 → 输出，无副作用；
//       颜色方法返回 StyleManager 的 token 名（如 'primary'），由页面解析为实际颜色值；
//       通过本文件 export，供 ohosTest 直接导入测试
// ===========================================================================

export class CollaborationViewHelper {
  /**
   * 获取模块对应的图标 emoji
   * 映射：projects→📁, templates→🧩, sessions→💬, workflows→🔄, teams→👥, tasks→✅
   * @param module 模块标识
   * @return emoji 字符串
   */
  static getModuleIcon(module: string): string {
    if (module === 'projects') return '📁';
    if (module === 'templates') return '🧩';
    if (module === 'sessions') return '💬';
    if (module === 'workflows') return '🔄';
    if (module === 'teams') return '👥';
    if (module === 'tasks') return '✅';
    return '📦';
  }

  /**
   * 获取模块对应的中文标签
   * 映射：projects→项目, templates→模板, sessions→进行中会话, workflows→工作流,
   *       teams→团队, tasks→任务
   * @param module 模块标识
   * @return 中文标签
   */
  static getModuleLabel(module: string): string {
    if (module === 'projects') return '项目';
    if (module === 'templates') return '模板';
    if (module === 'sessions') return '进行中会话';
    if (module === 'workflows') return '工作流';
    if (module === 'teams') return '团队';
    if (module === 'tasks') return '任务';
    return '未知';
  }

  /**
   * 格式化数量为文案
   * 规则：0 → "无"，正数 → 数字字符串
   * @param count 数量
   * @return 数量文案
   */
  static formatCount(count: number): string {
    if (count <= 0) return '无';
    return count.toString();
  }

  /**
   * 统计待办任务（status 为 'todo' 或 'in_progress'）数量并返回字符串
   * @param tasks 任务列表
   * @return 待办数量字符串，如 "2"
   */
  static formatPendingTasks(tasks: Task[]): string {
    if (!tasks || tasks.length === 0) return '0';
    let count = 0;
    for (const t of tasks) {
      if (t.status === 'todo' || t.status === 'in_progress') {
        count++;
      }
    }
    return count.toString();
  }

  /**
   * 获取模块对应的颜色 token 名
   * 映射：projects→primary, templates→info, sessions→success, workflows→warning,
   *       teams→info, tasks→warning
   * @param module 模块标识
   * @return StyleManager 颜色 token 名
   */
  static getModuleColor(module: string): string {
    if (module === 'projects') return 'primary';
    if (module === 'templates') return 'info';
    if (module === 'sessions') return 'success';
    if (module === 'workflows') return 'warning';
    if (module === 'teams') return 'info';
    if (module === 'tasks') return 'warning';
    return 'text_secondary';
  }
}

/** 快捷入口配置（key=展示标识，route=真实路由名） */
interface ModuleEntry {
  key: string;
  route: string;
}

/** 全部快捷入口（模板/历史/发起/任务——均已在 PageMap 注册，可真实跳转） */
const MODULE_ENTRIES: ModuleEntry[] = [
  { key: 'templates', route: RouteNames.COLLABORATION_TEMPLATE },
  { key: 'sessions', route: RouteNames.COLLABORATION_HISTORY },
  { key: 'tasks', route: RouteNames.TASK },
];

@Component
export struct CollaborationPage {
  // 协作概览统计（GET /v1/collaboration/stats 真实数据）
  @State stats: CollaborationStatsDto | undefined = undefined;
  // 任务列表（看板任务，待办统计用）
  @State tasks: Task[] = [];
  // 加载态
  @State loading: boolean = true;
  // 错误信息（非空时显示错误态）
  @State errorMessage: string = '';

  // 统一库单例
  private api = ApiFacade.getInstance();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private msg = MessageManager.getInstance();

  aboutToAppear() {
    this.loadOverview();
  }

  /**
   * 加载协作概览（GET /v1/collaboration/stats + 看板任务）
   * 流程：stats 与 tasks 两路并发，单路失败不影响另一路；全部失败显示错误态
   * 异常：记录日志并把后端原因透出
   */
  private async loadOverview(): Promise<void> {
    this.loading = true;
    this.errorMessage = '';
    try {
      const statsRes = await this.api.collaboration.getStats().catch((e: Object) => {
        this.logger.error(TAG, '加载协作统计失败', e as Error);
        return null;
      });
      const tasksRes = await this.api.collaboration.listTasks().catch((e: Object) => {
        this.logger.error(TAG, '加载任务失败', e as Error);
        return null;
      });
      if (statsRes && statsRes.code === 0 && statsRes.data) {
        this.stats = statsRes.data;
      }
      if (tasksRes && tasksRes.code === 0 && tasksRes.data) {
        this.tasks = tasksRes.data.items;
      }
      if (!statsRes && !tasksRes) {
        this.errorMessage = '加载协作数据失败';
        this.msg.error('加载协作数据失败');
      }
    } catch (e) {
      this.logger.error(TAG, '加载协作概览失败', e as Error);
      this.errorMessage = '加载协作数据失败';
      this.msg.error('加载协作数据失败');
    } finally {
      this.loading = false;
    }
  }

  /** 点击快捷入口（真实跳转：模板/历史/任务页均已在 PageMap 注册） */
  private handleEntryClick(route: string): void {
    this.router.push(route);
  }

  build() {
    Column() {
      // 顶部导航栏：标题"协作" + 返回按钮
      TopNavMenu({
        title: '协作',
        showBack: true,
        showMenu: false,
        onBack: () => { this.router.back(); }
      })

      // 主体：加载态 / 错误态 / 空态 / 内容
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
      } else if (this.errorMessage.length > 0) {
        Column() {
          Text(this.errorMessage)
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontColor(this.sm.getColor('error'))
          GlassButton({
            text: '重试',
            type: 'primary',
            btnSize: 'medium',
            onTap: () => { this.loadOverview(); }
          })
            .margin({ top: this.sm.getSpacing('md') })
        }
        .width('100%')
        .layoutWeight(1)
        .justifyContent(FlexAlign.Center)
        .alignItems(HorizontalAlign.Center)
      } else {
        // 概览内容：统计卡（真实 /collaboration/stats）+ 快捷入口
        List({ space: 12 }) {
          ListItem() {
            this.buildStatCard('projects', this.stats !== undefined ? this.stats.projects : 0)
          }
          ListItem() {
            this.buildStatCard('templates', this.stats !== undefined ? this.stats.templates : 0)
          }
          ListItem() {
            this.buildStatCard('sessions', this.stats !== undefined ? this.stats.sessions : 0)
          }
          ListItem() {
            this.buildStatCard('workflows', this.stats !== undefined ? this.stats.workflows : 0)
          }
          ListItem() {
            this.buildStatCard('tasks',
              parseInt(CollaborationViewHelper.formatPendingTasks(this.tasks)))
          }

          // 快捷入口按钮
          ListItem() {
            this.buildEntryButtons()
          }
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
  }

  // ===========================================================================
  // 统计卡构建器
  // ===========================================================================

  /** 单个统计卡：图标 + 模块名 + 数量 */
  @Builder
  buildStatCard(module: string, count: number) {
    Column() {
    GlassCard() {
      Row() {
        Text(CollaborationViewHelper.getModuleIcon(module))
          .fontSize(32)
          .width(48)
          .height(48)
          .textAlign(TextAlign.Center)

        Column() {
          Text(CollaborationViewHelper.getModuleLabel(module))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
          Text(CollaborationViewHelper.formatCount(count))
            .fontSize(this.sm.getFontSize('title'))
            .fontWeight(FontWeight.Bold)
            .fontColor(this.sm.getColor(CollaborationViewHelper.getModuleColor(module)))
            .margin({ top: 4 })
        }
        .layoutWeight(1)
        .alignItems(HorizontalAlign.Start)
        .margin({ left: this.sm.getSpacing('sm') })
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)
    }
    }
    .width('100%')
  }

  // ===========================================================================
  // 快捷入口按钮组构建器
  // ===========================================================================

  /** 快捷入口按钮组：模板/历史(会话)/任务——真实路由跳转 */
  @Builder
  buildEntryButtons() {
    Row({ space: this.sm.getSpacing('sm') }) {
      ForEach(MODULE_ENTRIES, (entry: ModuleEntry) => {
        GlassButton({
          text: `${CollaborationViewHelper.getModuleIcon(entry.key)} ${CollaborationViewHelper.getModuleLabel(entry.key)}`,
          type: 'default',
          btnSize: 'small',
          onTap: () => { this.handleEntryClick(entry.route); }
        })
          .layoutWeight(1)
      }, (entry: ModuleEntry) => entry.key)
    }
    .width('100%')
    .alignItems(VerticalAlign.Center)
  }
}
