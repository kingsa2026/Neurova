/**
 * SandboxPage - 沙盒环境页（P3）
 *
 * 职责：展示沙盒环境列表，按 status 筛选，资源限制展示（CPU/内存/磁盘），
 *       暴露端口列表，启动/停止按钮，过期时间倒计时
 * 设计：
 *   - SandboxViewHelper（导出）：纯视图模型，封装状态颜色/图标/标签映射、
 *     CPU 限制格式化（'N 核'）、内存限制格式化（MB/GB 转换）、
 *     端口列表格式化（最多 3 个 + '...'）、过期时间格式化（已过期/小时/天），
 *     无 UI 依赖，可独立单元测试；
 *   - SandboxPage（@Component）：Stack[Column[TopNavMenu(标题"沙盒环境"+返回)]
 *     + [status 筛选 Tab（全部/created/running/stopped/error/expired）]
 *     + [加载态/空态/列表]]；
 *     列表项 GlassCard：状态徽章、名称、镜像、CPU/内存/磁盘、暴露端口、过期时间、
 *     操作按钮（启动/停止）；
 *     颜色统一走 StyleManager（返回 token 名），路由走 Router，
 *     API 暂无沙盒专用模块 → aboutToAppear 加载 mock 静态数据 + TODO M6 标注。
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassCard、GlassButton、GlassInput、GlassPanel
 *   - ../libs/api/ApiFacade：统一 API 门面（仅占位，未实际调用）
 *   - ../routing/Router：统一路由跳转
 *   - ../libs/style/StyleManager：统一样式 token
 *   - ../libs/logger/Logger：统一日志
 *   - ../libs/message/MessageManager：统一消息提示
 *   - ../libs/types：Sandbox、SandboxStatus
 *
 * 用法：
 *   由 Router.push(RouteNames.SANDBOX) 跳转进入；
 *   aboutToAppear 加载 mock 沙盒列表（TODO M6 接入真实 API）；
 *   status 筛选 Tab 切换 → 本地按 status 过滤；
 *   启动/停止按钮 → TODO M6 接入 api.sandbox.start / api.sandbox.stop
 *
 * TDD：SandboxViewHelper 各方法按红绿灯垂直切片逐步实现，详见 SandboxPage.test.ets
 */

import { TopNavMenu, GlassCard, GlassButton, GlassInput, GlassPanel } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { Sandbox, SandboxStatus } from '../libs/types';

/** 日志标签 */
const TAG = 'SandboxPage';

/** 端口列表最多显示数量 */
const MAX_PORTS_DISPLAY = 3;

/** 内存 GB 阈值 */
const MEMORY_GB_THRESHOLD = 1024;

/** 一小时毫秒数 */
const ONE_HOUR_MS = 3600 * 1000;

/** 一天毫秒数 */
const ONE_DAY_MS = 86400 * 1000;

// ===========================================================================
// SandboxViewHelper - 沙盒环境视图模型（纯函数，无 UI 依赖，可独立单元测试）
// ===========================================================================

export class SandboxViewHelper {
  /**
   * 获取沙盒状态对应的颜色 token 名
   * 映射：created→info、running→success、stopped→text_secondary、error→error、expired→warning
   * @param status 沙盒状态
   * @return StyleManager 颜色 token 名
   */
  static getStatusColor(status: SandboxStatus): string {
    if (status === 'created') return 'info';
    if (status === 'running') return 'success';
    if (status === 'stopped') return 'text_secondary';
    if (status === 'error') return 'error';
    if (status === 'expired') return 'warning';
    throw new Error(`getStatusColor 未实现: ${status}`);
  }

  /**
   * 获取沙盒状态对应的图标 emoji
   * 映射：created→📦、running▶️、stopped→⏸️、error→⚠️、expired→⌛
   * @param status 沙盒状态
   * @return emoji 字符串
   */
  static getStatusIcon(status: SandboxStatus): string {
    if (status === 'created') return '📦';
    if (status === 'running') return '▶️';
    if (status === 'stopped') return '⏸️';
    if (status === 'error') return '⚠️';
    if (status === 'expired') return '⌛';
    throw new Error(`getStatusIcon 未实现: ${status}`);
  }

  /**
   * 获取沙盒状态对应的中文标签
   * 映射：created→已创建、running→运行中、stopped→已停止、error→错误、expired→已过期
   * @param status 沙盒状态
   * @return 中文标签
   */
  static getStatusLabel(status: SandboxStatus): string {
    if (status === 'created') return '已创建';
    if (status === 'running') return '运行中';
    if (status === 'stopped') return '已停止';
    if (status === 'error') return '错误';
    if (status === 'expired') return '已过期';
    throw new Error(`getStatusLabel 未实现: ${status}`);
  }

  /**
   * 格式化 CPU 限制
   * 规则：保留 1 位小数 + ' 核'
   * @param cpu CPU 核数
   * @return 'N.N 核' 格式字符串
   */
  static formatCpuLimit(cpu: number): string {
    return `${cpu.toFixed(1)} 核`;
  }

  /**
   * 格式化内存限制
   * 规则：
   *   - < 1024 MB → 'NMB'（原值）
   *   - ≥ 1024 MB → 'X.XGB'（GB，保留 1 位小数）
   * @param mb 内存 MB 数
   * @return 'NMB' 或 'X.XGB' 格式字符串
   */
  static formatMemoryLimit(mb: number): string {
    if (mb < MEMORY_GB_THRESHOLD) {
      return `${mb}MB`;
    }
    const gb = mb / MEMORY_GB_THRESHOLD;
    return `${gb.toFixed(1)}GB`;
  }

  /**
   * 格式化端口列表
   * 规则：
   *   - 空数组 → '无'
   *   - 长度 ≤ 3 → 端口以 ', ' 连接
   *   - 长度 > 3 → 前 3 个 + '...'
   * @param ports 端口数组
   * @return 格式化端口字符串
   */
  static formatPorts(ports: number[]): string {
    if (!ports || ports.length === 0) return '无';
    if (ports.length <= MAX_PORTS_DISPLAY) {
      return ports.join(', ');
    }
    const head = ports.slice(0, MAX_PORTS_DISPLAY).join(', ');
    return `${head}...`;
  }

  /**
   * 格式化过期时间
   * 规则：
   *   - 无效时间 → '—'
   *   - 已过期 → '已过期'
   *   - 未来 < 24 小时 → 'X 小时后过期'
   *   - 未来 ≥ 24 小时 → 'X 天后过期'
   * @param expiresAt 过期时间 ISO 字符串
   * @return 过期倒计时字符串
   */
  static formatExpiry(expiresAt: string): string {
    const target = new Date(expiresAt).getTime();
    if (isNaN(target)) return '—';
    const now = Date.now();
    const diff = target - now;
    if (diff <= 0) return '已过期';
    if (diff < ONE_DAY_MS) {
      const hours = Math.floor(diff / ONE_HOUR_MS);
      return `${hours} 小时后过期`;
    }
    const days = Math.floor(diff / ONE_DAY_MS);
    return `${days} 天后过期`;
  }
}

/** 状态筛选 Tab 配置 */
interface StatusFilterOption {
  value: string;
  label: string;
}

/** 状态筛选 Tab 列表 */
const STATUS_FILTERS: StatusFilterOption[] = [
  { value: 'all', label: '全部' },
  { value: 'created', label: '已创建' },
  { value: 'running', label: '运行中' },
  { value: 'stopped', label: '已停止' },
  { value: 'error', label: '错误' },
  { value: 'expired', label: '已过期' },
];

/**
 * Mock 沙盒环境数据
 * TODO M6 阶段：替换为 api.sandbox.list() 真实 API
 */
const MOCK_SANDBOXES: Sandbox[] = [
  {
    id: 'sandbox_1',
    name: 'dev-env-1',
    image: 'node:18-alpine',
    status: 'running',
    cpuLimit: 2,
    memoryLimitMb: 2048,
    diskLimitMb: 10240,
    exposedPorts: [3000, 8080],
    envVars: { NODE_ENV: 'development' },
    createdAt: '2025-03-01T09:00:00Z',
    expiresAt: new Date(Date.now() + 2 * 86400 * 1000).toISOString(),
    lastStartedAt: '2025-03-01T09:00:00Z',
  },
  {
    id: 'sandbox_2',
    name: 'python-test',
    image: 'python:3.11-slim',
    status: 'created',
    cpuLimit: 1,
    memoryLimitMb: 512,
    diskLimitMb: 5120,
    exposedPorts: [5000],
    envVars: { PYTHON_ENV: 'test' },
    createdAt: '2025-03-01T10:00:00Z',
    expiresAt: new Date(Date.now() + 5 * 3600 * 1000).toISOString(),
  },
  {
    id: 'sandbox_3',
    name: 'rust-build',
    image: 'rust:1.75',
    status: 'stopped',
    cpuLimit: 4,
    memoryLimitMb: 8192,
    diskLimitMb: 20480,
    exposedPorts: [],
    envVars: {},
    createdAt: '2025-03-01T08:00:00Z',
    expiresAt: new Date(Date.now() + 3600 * 1000).toISOString(),
    lastStartedAt: '2025-03-01T08:30:00Z',
  },
  {
    id: 'sandbox_4',
    name: 'gpu-ml',
    image: 'tensorflow/tensorflow:latest-gpu',
    status: 'error',
    cpuLimit: 8,
    memoryLimitMb: 16384,
    diskLimitMb: 51200,
    exposedPorts: [8888, 6006, 22, 80],
    envVars: { CUDA_VISIBLE_DEVICES: '0' },
    createdAt: '2025-03-01T07:00:00Z',
    expiresAt: '2020-01-01T00:00:00Z',
    errorMessage: 'GPU 不可用',
  },
  {
    id: 'sandbox_5',
    name: 'expired-demo',
    image: 'alpine:3.18',
    status: 'expired',
    cpuLimit: 0.5,
    memoryLimitMb: 256,
    diskLimitMb: 1024,
    exposedPorts: [80],
    envVars: {},
    createdAt: '2025-02-01T00:00:00Z',
    expiresAt: '2020-01-01T00:00:00Z',
  },
];

@Component
export struct SandboxPage {
  // 沙盒列表
  @State sandboxes: Sandbox[] = [];
  // 加载态
  @State loading: boolean = true;
  // 当前激活的状态筛选
  @State activeStatus: string = 'all';

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
   * 加载沙盒列表
   * TODO M6 阶段：替换为真实 API（api.sandbox.list）
   */
  private async loadSandboxes(): Promise<void> {
    this.loading = true;
    try {
      // TODO M6: 接入真实 API（api.sandbox.*）
      // const res = await this.api.sandbox.list();
      // if (res.code === 0 && res.data) { this.sandboxes = res.data.items; }
      this.sandboxes = MOCK_SANDBOXES.slice();
    } catch (e) {
      this.logger.error(TAG, '加载沙盒列表失败', e as Error);
      this.msg.error('加载沙盒列表失败');
    } finally {
      this.loading = false;
    }
  }

  /** 切换状态筛选 */
  private switchStatus(value: string): void {
    this.activeStatus = value;
  }

  /** 获取经状态筛选后的列表 */
  private getFilteredSandboxes(): Sandbox[] {
    if (this.activeStatus === 'all') {
      return this.sandboxes;
    }
    return this.sandboxes.filter((s: Sandbox) => s.status === this.activeStatus);
  }

  /**
   * 启动沙盒
   * TODO M6 阶段：调用真实 API（api.sandbox.start）
   */
  private async startSandbox(sandbox: Sandbox): Promise<void> {
    try {
      // TODO M6: const res = await this.api.sandbox.start(sandbox.id);
      this.msg.success(`已启动: ${sandbox.name}`);
    } catch (e) {
      this.logger.error(TAG, '启动沙盒失败', e as Error);
      this.msg.error('启动沙盒失败');
    }
  }

  /**
   * 停止沙盒
   * TODO M6 阶段：调用真实 API（api.sandbox.stop）
   */
  private async stopSandbox(sandbox: Sandbox): Promise<void> {
    try {
      // TODO M6: const res = await this.api.sandbox.stop(sandbox.id);
      this.msg.success(`已停止: ${sandbox.name}`);
    } catch (e) {
      this.logger.error(TAG, '停止沙盒失败', e as Error);
      this.msg.error('停止沙盒失败');
    }
  }

  build() {
    Stack() {
      Column() {
        // 顶部导航栏：标题"沙盒环境" + 返回
        TopNavMenu({
          title: '沙盒环境',
          showBack: true,
          showMenu: false,
          onBack: () => { this.router.back(); }
        })

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
          List({ space: 12 }) {
            ForEach(this.getFilteredSandboxes(), (sandbox: Sandbox) => {
              ListItem() {
                this.buildSandboxCard(sandbox)
              }
            }, (sandbox: Sandbox) => sandbox.id)
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
    .width('100%')
    .height('100%')
  }

  // ===========================================================================
  // 沙盒卡片构建器
  // ===========================================================================

  /** 单条沙盒卡片：状态徽章 + 名称 + 镜像 + 资源限制 + 端口 + 过期时间 + 操作按钮 */
  @Builder
  buildSandboxCard(sandbox: Sandbox) {
    GlassCard() {
      Column() {
        // 上部：状态徽章 + 过期时间
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

          Text(SandboxViewHelper.formatExpiry(sandbox.expiresAt))
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

        // 名称 + 镜像
        Text(sandbox.name)
          .fontSize(this.sm.getFontSize('body'))
          .fontColor(this.sm.getColor('text_primary'))
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .margin({ top: 4 })
          .width('100%')
        Text(`镜像: ${sandbox.image}`)
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('text_secondary'))
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .margin({ top: 2 })
          .width('100%')

        // 资源限制：CPU + 内存 + 磁盘
        Row() {
          Text(`CPU: ${SandboxViewHelper.formatCpuLimit(sandbox.cpuLimit)}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .layoutWeight(1)
          Text(`内存: ${SandboxViewHelper.formatMemoryLimit(sandbox.memoryLimitMb)}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .layoutWeight(1)
        }
        .width('100%')
        .margin({ top: 4 })
        .alignItems(VerticalAlign.Center)
        Text(`磁盘: ${SandboxViewHelper.formatMemoryLimit(sandbox.diskLimitMb)}`)
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('text_secondary'))
          .margin({ top: 2 })

        // 暴露端口
        Text(`端口: ${SandboxViewHelper.formatPorts(sandbox.exposedPorts)}`)
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('text_secondary'))
          .margin({ top: 4 })

        // 错误信息（error 状态时显示）
        if (sandbox.status === 'error' && sandbox.errorMessage) {
          Text(`错误: ${sandbox.errorMessage}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('error'))
            .maxLines(2)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
            .margin({ top: 4 })
            .width('100%')
        }

        // 操作按钮：启动 / 停止
        Row() {
          if (sandbox.status === 'running') {
            GlassButton({
              text: '停止',
              type: 'danger',
              size: 'small',
              onClick: () => { this.stopSandbox(sandbox); }
            })
          } else if (sandbox.status === 'stopped' || sandbox.status === 'created') {
            GlassButton({
              text: '启动',
              type: 'primary',
              size: 'small',
              onClick: () => { this.startSandbox(sandbox); }
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
    .width('100%')
  }
}
