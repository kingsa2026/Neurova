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
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { Project, Team, Task } from '../libs/types';

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
   * 映射：projects→📁, teams→👥, tasks→✅
   * @param module 模块标识
   * @return emoji 字符串
   */
  static getModuleIcon(module: string): string {
    if (module === 'projects') return '📁';
    if (module === 'teams') return '👥';
    if (module === 'tasks') return '✅';
    return '📦';
  }

  /**
   * 获取模块对应的中文标签
   * 映射：projects→项目, teams→团队, tasks→任务
   * @param module 模块标识
   * @return 中文标签
   */
  static getModuleLabel(module: string): string {
    if (module === 'projects') return '项目';
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
   * 映射：projects→primary, teams→info, tasks→warning
   * @param module 模块标识
   * @return StyleManager 颜色 token 名
   */
  static getModuleColor(module: string): string {
    if (module === 'projects') return 'primary';
    if (module === 'teams') return 'info';
    if (module === 'tasks') return 'warning';
    return 'text_secondary';
  }
}

/** 模块标识联合类型别名（用于快捷入口列表） */
type ModuleKey = 'projects' | 'teams' | 'tasks';

/** 快捷入口配置 */
interface ModuleEntry {
  key: ModuleKey;
}

/** 全部快捷入口（顺序：项目/团队/任务） */
const MODULE_ENTRIES: ModuleEntry[] = [
  { key: 'projects' },
  { key: 'teams' },
  { key: 'tasks' },
];

@Component
export struct CollaborationPage {
  // 项目列表（用于统计数量）
  @State projects: Project[] = [];
  // 团队列表
  @State teams: Team[] = [];
  // 任务列表
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
   * 并行加载项目/团队/任务列表
   * 流程：Promise.allSettled 三路并发 → 写入对应 @State
   * 异常：单路失败不影响其他；全部失败时显示错误态
   */
  private async loadOverview(): Promise<void> {
    this.loading = true;
    this.errorMessage = '';
    try {
      const [projectsRes, teamsRes, tasksRes] = await Promise.all([
        this.api.collaboration.listProjects().catch((e: Object) => {
          this.logger.error(TAG, '加载项目失败', e as Error);
          return null;
        }),
        this.api.collaboration.listTeams().catch((e: Object) => {
          this.logger.error(TAG, '加载团队失败', e as Error);
          return null;
        }),
        this.api.collaboration.listTasks().catch((e: Object) => {
          this.logger.error(TAG, '加载任务失败', e as Error);
          return null;
        }),
      ]);
      if (projectsRes && projectsRes.code === 0 && projectsRes.data) {
        this.projects = projectsRes.data.items;
      }
      if (teamsRes && teamsRes.code === 0 && teamsRes.data) {
        this.teams = teamsRes.data.items;
      }
      if (tasksRes && tasksRes.code === 0 && tasksRes.data) {
        this.tasks = tasksRes.data.items;
      }
      if (!projectsRes && !teamsRes && !tasksRes) {
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

  /** 点击快捷入口（路由待注册，当前以消息提示占位） */
  private handleEntryClick(module: string): void {
    const label = CollaborationViewHelper.getModuleLabel(module);
    this.msg.info(`跳转到${label}页`);
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
            size: 'medium',
            onClick: () => { this.loadOverview(); }
          })
            .margin({ top: this.sm.getSpacing('md') })
        }
        .width('100%')
        .layoutWeight(1)
        .justifyContent(FlexAlign.Center)
        .alignItems(HorizontalAlign.Center)
      } else {
        // 概览内容：3 个统计卡 + 3 个快捷入口
        List({ space: 12 }) {
          // 三个统计卡（项目数/团队数/待办任务数）
          ListItem() {
            this.buildStatCard('projects', this.projects.length)
          }
          ListItem() {
            this.buildStatCard('teams', this.teams.length)
          }
          ListItem() {
            this.buildStatCard('tasks',
              parseInt(CollaborationViewHelper.formatPendingTasks(this.tasks)))
          }

          // 三个快捷入口按钮
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
    .width('100%')
  }

  // ===========================================================================
  // 快捷入口按钮组构建器
  // ===========================================================================

  /** 3 个快捷入口按钮：项目/团队/任务 */
  @Builder
  buildEntryButtons() {
    Row({ space: this.sm.getSpacing('sm') }) {
      ForEach(MODULE_ENTRIES, (entry: ModuleEntry) => {
        GlassButton({
          text: `${CollaborationViewHelper.getModuleIcon(entry.key)} ${CollaborationViewHelper.getModuleLabel(entry.key)}`,
          type: 'default',
          size: 'medium',
          onClick: () => { this.handleEntryClick(entry.key); }
        })
          .layoutWeight(1)
      }, (entry: ModuleEntry) => entry.key)
    }
    .width('100%')
    .alignItems(VerticalAlign.Center)
  }
}
