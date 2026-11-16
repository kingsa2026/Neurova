/**
 * SandboxPage - 沙盒环境页（R6 接真实 API）
 *
 * 职责：展示沙盒会话列表（/v1/sandbox），按状态筛选，新建（默认镜像）、
 *       执行代码（内嵌命令面板）、销毁
 * 设计：
 *   - SandboxViewHelper（导出）：纯视图模型，封装状态颜色/图标/标签映射
 *     （后端 status 开放集合，未知值兜默认）、超时格式化、步骤数格式化、
 *     时间格式化；无 UI 依赖，可独立单元测试；
 *   - SandboxPage（@Component）：Column [TopNavMenu(标题"沙盒环境"+返回+新建)]
 *     + [status 筛选 Tab] + [加载态/空态/列表] + [执行面板（选中 running 沙盒）]；
 *     列表项 GlassCard：状态徽章、名称、镜像/语言、超时/步骤数、agent/topic、
 *     操作（执行/销毁）；
 *   - 颜色统一走 StyleManager，路由走 Router，已接线 PageMap（P1-33）；
 *     数据源 SandboxApi（R6：替换 mock）。
 *
 * 契约说明（诚实缺省）：
 *   - _publicView：id/name/status/image/language/timeout/steps_count/
 *     created_at/updated_at/agent_id/topic——后端无 CPU/内存限制、暴露端口、
 *     过期时间字段（旧 mock 契约），本页不再渲染这些列；
 *   - status 值域 running/failed/timeout/committed（开放集合兜默认）；
 *   - 思维沙箱保留 id 'null'（无容器承载）：不可执行代码、不可销毁（后端 400
 *     拦截），如实提示；
 *   - 新建走默认镜像（后端 DEFAULT_IMAGE python:3.11-slim，白名单校验 400
 *     拒因透传）；执行面板仅对 running 代码沙箱开放。
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassCard、GlassButton
 *   - ../libs/api/ApiFacade：统一 API 门面（api.sandbox.*）
 *   - ../libs/api/modules/SandboxApi：SandboxViewDto/SandboxExecDto 契约
 *   - ../routing/Router、../libs/style/StyleManager、../libs/logger/Logger、
 *     ../libs/message/MessageManager
 *
 * 用法：
 *   由 Router.push(RouteNames.SANDBOX) 跳转进入；
 *   aboutToAppear 经 api.sandbox.list() 加载；
 *   status 筛选 Tab 切换 → 本地过滤；
 *   新建 → api.sandbox.start({})（默认镜像）→ 刷新；
 *   执行 → 选中沙盒 → 执行面板输入命令 → api.sandbox.execute() → 展示 stdout/stderr；
 *   销毁 → AlertDialog 二次确认 → api.sandbox.destroy() → 刷新。
 */

import { TopNavMenu, GlassCard, GlassButton } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { SandboxViewDto, SandboxExecDto } from '../libs/api/modules/SandboxApi';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';

/** 日志标签 */
const TAG = 'SandboxPage';

/** 思维沙箱保留 id（后端 THOUGHT_SESSION_ID） */
const THOUGHT_SESSION_ID = 'null';

/** 一分钟秒数（超时展示换算） */
const ONE_MINUTE_SECONDS = 60;

// ===========================================================================
// SandboxViewHelper - 沙盒环境视图模型（纯函数，无 UI 依赖，可独立单元测试）
// ===========================================================================

export class SandboxViewHelper {
  /**
   * 获取沙盒状态对应的颜色 token 名（未知兜 'text_secondary'——status 开放集合）
   * 映射：running→success、failed→error、timeout→warning、committed→info
   * @param status 沙盒状态
   * @return StyleManager 颜色 token 名
   */
  static getStatusColor(status: string): string {
    if (status === 'running') return 'success';
    if (status === 'failed') return 'error';
    if (status === 'timeout') return 'warning';
    if (status === 'committed') return 'info';
    return 'text_secondary';
  }

  /**
   * 获取沙盒状态对应的图标 emoji（未知兜 '📦'）
   * @param status 沙盒状态
   * @return emoji 字符串
   */
  static getStatusIcon(status: string): string {
    if (status === 'running') return '▶️';
    if (status === 'failed') return '⚠️';
    if (status === 'timeout') return '⌛';
    if (status === 'committed') return '✅';
    return '📦';
  }

  /**
   * 获取沙盒状态对应的中文标签（未知原样返回）
   * 映射：running→运行中、failed→失败、timeout→超时、committed→已提交
   * @param status 沙盒状态
   * @return 中文标签
   */
  static getStatusLabel(status: string): string {
    if (status === 'running') return '运行中';
    if (status === 'failed') return '失败';
    if (status === 'timeout') return '超时';
    if (status === 'committed') return '已提交';
    return status;
  }

  /**
   * 判断是否思维沙箱（保留 id 'null'：无容器承载）
   * @param sandboxId 沙盒 id
   * @return 是否思维沙箱
   */
  static isThoughtSandbox(sandboxId: string | null): boolean {
    return sandboxId === null || sandboxId === THOUGHT_SESSION_ID;
  }

  /**
   * 格式化超时时间
   * 规则：< 60s → "{n}s"；≥ 60s → "{n}min"
   * @param seconds 超时秒数
   * @return 格式化字符串
   */
  static formatTimeout(seconds: number): string {
    if (seconds < ONE_MINUTE_SECONDS) {
      return `${seconds}s`;
    }
    return `${Math.round(seconds / ONE_MINUTE_SECONDS)}min`;
  }

  /**
   * 格式化步骤计数
   * 规则：0 → '无执行记录'；其他 → '{n} 步'
   * @param stepsCount 步骤数
   * @return 格式化字符串
   */
  static formatStepsCount(stepsCount: number): string {
    if (stepsCount === 0) return '无执行记录';
    return `${stepsCount} 步`;
  }

  /**
   * 格式化 ISO 时间戳为 YYYY-MM-DD HH:mm
   * 规则：无值/无效 → '—'
   * @param timestamp ISO 时间戳字符串
   * @return 格式化时间或 '—'
   */
  static formatTimestamp(timestamp: string): string {
    if (!timestamp || timestamp.length === 0) return '—';
    const d = new Date(timestamp);
    if (isNaN(d.getTime())) return '—';
    const yyyy = d.getFullYear();
    const MM = (d.getMonth() + 1).toString().padStart(2, '0');
    const dd = d.getDate().toString().padStart(2, '0');
    const HH = d.getHours().toString().padStart(2, '0');
    const mm = d.getMinutes().toString().padStart(2, '0');
    return `${yyyy}-${MM}-${dd} ${HH}:${mm}`;
  }
}

/** 状态筛选 Tab 配置 */
interface StatusFilterOption {
  value: string;
  label: string;
}

/** 状态筛选 Tab 列表（后端 status 值域） */
const STATUS_FILTERS: StatusFilterOption[] = [
  { value: 'all', label: '全部' },
  { value: 'running', label: '运行中' },
  { value: 'failed', label: '失败' },
  { value: 'timeout', label: '超时' },
  { value: 'committed', label: '已提交' },
];

@Component
export struct SandboxPage {
  // 沙盒列表（api.sandbox.list() 真实数据）
  @State sandboxes: SandboxViewDto[] = [];
  // 加载态
  @State loading: boolean = true;
  // 当前激活的状态筛选
  @State activeStatus: string = 'all';
  // 选中执行命令的沙盒 id（'' = 无）
  @State selectedSandboxId: string = '';
  // 执行面板命令输入
  @State execCommand: string = '';
  // 最近一次执行输出（stdout/stderr 合流 + exit code）
  @State execOutput: string = '';
  // 写操作进行中（防重复点击）
  @State operatingId: string = '';

  // 统一库单例
  private api = ApiFacade.getInstance();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private msg = MessageManager.getInstance();

  aboutToAppear() {
    this.loadSandboxes();
  }

  /**
   * 加载沙盒列表（GET /v1/sandbox）
   */
  private async loadSandboxes(): Promise<void> {
    this.loading = true;
    try {
      const res = await this.api.sandbox.list();
      if (res.code === 0 && res.data) {
        this.sandboxes = res.data;
      } else {
        this.sandboxes = [];
        this.msg.error(res.message && res.message.length > 0 ? res.message : '加载沙盒列表失败');
      }
    } catch (e) {
      this.logger.error(TAG, '加载沙盒列表失败', e as Error);
      this.msg.error('加载沙盒列表失败');
      this.sandboxes = [];
    } finally {
      this.loading = false;
    }
  }

  /** 切换状态筛选 */
  private switchStatus(value: string): void {
    this.activeStatus = value;
  }

  /** 获取经状态筛选后的列表 */
  private getFilteredSandboxes(): SandboxViewDto[] {
    if (this.activeStatus === 'all') {
      return this.sandboxes;
    }
    return this.sandboxes.filter((s: SandboxViewDto) => s.status === this.activeStatus);
  }

  /** 选中/取消选中执行目标 */
  private toggleSelect(sandbox: SandboxViewDto): void {
    if (this.selectedSandboxId === sandbox.id) {
      this.selectedSandboxId = '';
    } else {
      // 调用点已排除思维沙箱（id 可能为 null），类型面再收一道
      if (sandbox.id !== null) {
        this.selectedSandboxId = sandbox.id;
        this.execOutput = '';
      }
    }
  }

  /**
   * 新建沙箱（POST /v1/sandbox/start，默认镜像/语言交给后端推断）
   * 镜像白名单外/timeout 越界 → 400 拒因透传
   */
  private async startSandbox(): Promise<void> {
    if (this.operatingId.length > 0) {
      return;
    }
    this.operatingId = 'start';
    try {
      const res = await this.api.sandbox.start({});
      if (res.code === 0 && res.data) {
        this.msg.success(`沙盒已开启: ${res.data.name}`);
        await this.loadSandboxes();
      } else {
        this.msg.error(res.message && res.message.length > 0 ? res.message : '开启沙盒失败');
      }
    } catch (e) {
      this.logger.error(TAG, '开启沙盒失败', e as Error);
      this.msg.error('开启沙盒失败');
    } finally {
      this.operatingId = '';
    }
  }

  /**
   * 在选中沙盒中执行命令（POST /v1/sandbox/{id}/execute）
   */
  private async executeCommand(): Promise<void> {
    const sandboxId = this.selectedSandboxId;
    if (sandboxId.length === 0 || this.execCommand.trim().length === 0) {
      this.msg.info('先选中一个运行中的沙盒并输入命令');
      return;
    }
    if (this.operatingId.length > 0) {
      return;
    }
    this.operatingId = sandboxId;
    try {
      const res = await this.api.sandbox.execute(sandboxId, this.execCommand.trim());
      if (res.code === 0 && res.data) {
        const out: SandboxExecDto = res.data;
        const exitText = `exit=${out.exit_code} (${out.duration_ms}ms, ${out.backend})`;
        this.execOutput = `${exitText}\n${out.output}`;
        this.msg.success('执行完成');
        await this.loadSandboxes();
      } else {
        this.msg.error(res.message && res.message.length > 0 ? res.message : '执行失败');
      }
    } catch (e) {
      this.logger.error(TAG, '执行命令失败', e as Error);
      this.msg.error('执行命令失败');
    } finally {
      this.operatingId = '';
    }
  }

  /**
   * 销毁前二次确认（思维沙箱不可销毁——后端 400，前端也不提供入口）
   */
  private confirmDestroy(sandbox: SandboxViewDto): void {
    if (SandboxViewHelper.isThoughtSandbox(sandbox.id)) {
      this.msg.info('思维沙箱是保留会话，不可销毁');
      return;
    }
    AlertDialog.show({
      title: '确认销毁',
      message: `确定要销毁沙盒"${sandbox.name}"吗？中间过程将被丢弃。`,
      autoCancel: true,
      alignment: DialogAlignment.Center,
      primaryButton: {
        value: '取消',
        action: () => {}
      },
      secondaryButton: {
        value: '销毁',
        fontColor: this.sm.getColor('error'),
        action: () => { this.destroySandbox(sandbox.id); }
      }
    });
  }

  /**
   * 执行销毁（DELETE /v1/sandbox/{id}）
   */
  private async destroySandbox(sandboxId: string): Promise<void> {
    if (this.operatingId.length > 0) {
      return;
    }
    this.operatingId = sandboxId;
    try {
      const res = await this.api.sandbox.destroy(sandboxId);
      if (res.code === 0) {
        this.msg.success('已销毁');
        if (this.selectedSandboxId === sandboxId) {
          this.selectedSandboxId = '';
          this.execOutput = '';
        }
        await this.loadSandboxes();
      } else {
        this.msg.error(res.message && res.message.length > 0 ? res.message : '销毁失败');
      }
    } catch (e) {
      this.logger.error(TAG, '销毁沙盒失败', e as Error);
      this.msg.error('销毁沙盒失败');
    } finally {
      this.operatingId = '';
    }
  }

  build() {
    Column() {
      // 顶部导航栏：标题"沙盒环境" + 返回 + 新建
      TopNavMenu({
        title: '沙盒环境',
        showBack: true,
        showMenu: false,
        onBack: () => { this.router.back(); }
      }) {
        GlassButton({
          text: '新建',
          type: 'primary',
          btnSize: 'small',
          onTap: () => { this.startSandbox(); }
        })
      }

      // 状态筛选 Tab
      Scroll() {
        Row({ space: 8 }) {
          ForEach(STATUS_FILTERS, (opt: StatusFilterOption) => {
            Text(opt.label)
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.activeStatus === opt.value
                ? this.sm.getColor('text_on_primary')
                : this.sm.getColor('text_secondary'))
              .backgroundColor(this.activeStatus === opt.value
                ? this.sm.getColor('primary')
                : this.sm.getColor('surface'))
              .padding({ left: 12, right: 12, top: 6, bottom: 6 })
              .borderRadius(16)
              .onClick(() => { this.switchStatus(opt.value); })
          }, (opt: StatusFilterOption) => opt.value)
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
      } else if (this.getFilteredSandboxes().length === 0) {
        Column() {
          Text('暂无沙盒环境')
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontColor(this.sm.getColor('text_secondary'))
        }
        .width('100%')
        .layoutWeight(1)
        .justifyContent(FlexAlign.Center)
        .alignItems(HorizontalAlign.Center)
      } else {
        Column() {
          List({ space: 12 }) {
            ForEach(this.getFilteredSandboxes(), (sandbox: SandboxViewDto) => {
              ListItem() {
                this.buildSandboxCard(sandbox)
              }
            }, (sandbox: SandboxViewDto) => `${sandbox.id}`)
          }
          .layoutWeight(1)
          .width('100%')
          .scrollBar(BarState.Off)

          // 执行面板（选中 running 沙盒时展示；GlassCard 是自定义组件，
          // 外链属性挂包裹 Column——S8 台账坑）
          if (this.selectedSandboxId.length > 0) {
            Column() {
              this.buildExecPanel()
            }
            .width('100%')
            .margin({ top: this.sm.getSpacing('sm') })
          }
        }
        .layoutWeight(1)
        .width('100%')
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
  // 卡片与面板构建器
  // ===========================================================================

  /** 单条沙盒卡片：状态徽章 + 名称 + 镜像/语言 + 超时/步骤 + 归属 + 操作按钮 */
  @Builder
  buildSandboxCard(sandbox: SandboxViewDto) {
    GlassCard() {
      Column() {
        // 上部：状态徽章 + 更新时间
        Row() {
          Row() {
            Text(SandboxViewHelper.getStatusIcon(sandbox.status))
              .fontSize(14)
            Text(SandboxViewHelper.getStatusLabel(sandbox.status))
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_on_primary'))
              .margin({ left: 4 })
          }
          .padding({ left: 8, right: 8, top: 2, bottom: 2 })
          .borderRadius(this.sm.getRadius('sm'))
          .backgroundColor(this.sm.getColor(SandboxViewHelper.getStatusColor(sandbox.status)))

          Text(SandboxViewHelper.formatTimestamp(sandbox.updated_at))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_disabled'))
            .layoutWeight(1)
            .margin({ left: 8 })
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
            .textAlign(TextAlign.End)
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)

        // 名称 + 归属（agent/topic = 思维沙箱标记）
        Text(sandbox.name)
          .fontSize(this.sm.getFontSize('body'))
          .fontColor(this.sm.getColor('text_primary'))
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .margin({ top: 4 })
          .width('100%')
        if (sandbox.agent_id !== null && sandbox.topic !== null) {
          Text(`思维沙箱 · ${sandbox.agent_id} · ${sandbox.topic}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('info'))
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
            .margin({ top: 2 })
            .width('100%')
        }

        // 镜像/语言 + 超时/步骤
        Row() {
          Text(`镜像: ${sandbox.image}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .layoutWeight(1)
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
          Text(SandboxViewHelper.formatTimeout(sandbox.timeout))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_disabled'))
        }
        .width('100%')
        .margin({ top: 4 })
        .alignItems(VerticalAlign.Center)
        Row() {
          Text(`语言: ${sandbox.language}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .layoutWeight(1)
          Text(SandboxViewHelper.formatStepsCount(sandbox.steps_count))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_disabled'))
        }
        .width('100%')
        .margin({ top: 2 })
        .alignItems(VerticalAlign.Center)

        // 操作按钮：执行（仅 running 代码沙箱）+ 销毁
        Row() {
          if (sandbox.status === 'running' && !SandboxViewHelper.isThoughtSandbox(sandbox.id)) {
            GlassButton({
              text: this.selectedSandboxId === sandbox.id ? '收起执行' : '执行',
              type: this.selectedSandboxId === sandbox.id ? 'default' : 'primary',
              btnSize: 'small',
              onTap: () => { this.toggleSelect(sandbox); }
            })
              .margin({ right: this.sm.getSpacing('sm') })
          }
          if (!SandboxViewHelper.isThoughtSandbox(sandbox.id)) {
            GlassButton({
              text: '销毁',
              type: 'danger',
              btnSize: 'small',
              onTap: () => { this.confirmDestroy(sandbox); }
            })
          }
        }
        .width('100%')
        .justifyContent(FlexAlign.End)
        .margin({ top: this.sm.getSpacing('md') })
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
  }

  /** 执行面板：命令输入 + 执行按钮 + 最近输出 */
  @Builder
  buildExecPanel() {
    GlassCard() {
      Column() {
        Text('执行命令')
          .fontSize(this.sm.getFontSize('subtitle'))
          .fontWeight(FontWeight.Bold)
          .fontColor(this.sm.getColor('text_primary'))
          .width('100%')

        TextInput({ placeholder: '输入要执行的命令', text: this.execCommand })
          .fontSize(this.sm.getFontSize('body'))
          .fontColor(this.sm.getColor('text_primary'))
          .backgroundColor(this.sm.getColor('surface'))
          .borderRadius(this.sm.getRadius('sm'))
          .width('100%')
          .margin({ top: this.sm.getSpacing('xs') })
          .onChange((v: string) => { this.execCommand = v; })

        Row() {
          GlassButton({
            text: this.operatingId === this.selectedSandboxId ? '执行中' : '运行',
            type: 'primary',
            btnSize: 'small',
            onTap: () => { this.executeCommand(); }
          })
        }
        .width('100%')
        .justifyContent(FlexAlign.End)
        .margin({ top: this.sm.getSpacing('xs') })

        if (this.execOutput.length > 0) {
          Text(this.execOutput)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .padding({ top: 4, bottom: 4, left: 8, right: 8 })
            .backgroundColor(this.sm.getColor('surface'))
            .borderRadius(this.sm.getRadius('sm'))
            .width('100%')
            .margin({ top: this.sm.getSpacing('xs') })
            .maxLines(10)
        }
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
  }
}
