/**
 * AIGCPage - AIGC 任务页
 *
 * 职责：展示 AIGC 任务列表，按 status 筛选，新建任务，查看结果
 * 设计：
 *   - AIGCViewHelper（导出）：纯视图模型，封装任务类型颜色/图标/文案、状态颜色/图标/文案、
 *     prompt 截断（默认 100）、时长格式化（秒/分秒），无 UI 依赖，可独立单元测试；
 *   - AIGCPage（@Component）：Stack [主内容列] + [新建任务 CustomDialog]
 *     主内容列：TopNavMenu(标题"AIGC 任务"+返回+新建) + [status 筛选 Tab（全部/queued/processing/
 *     succeeded/failed）] + [加载态/空态/列表]；
 *     列表项 GlassCard：type 徽章、prompt 摘要、status 徽章、resultUrl 链接（succeeded 时）、
 *     errorMessage（failed 时）、createdAt、finishedAt、操作（查看详情/取消/重试）；
 *   - 新建 CustomDialog：type 选择（text/image/audio/video/music）、prompt 文本域、
 *     music 类型追加时长（秒）输入（缺省 30，1-600）；
 *   - music（M1 多模态追平）：提交 POST /generation/music 拿 task_id，落服务端账本
 *     后由列表 5s 轮询推进状态（与 video 同范式）；succeeded 卡片展示音频播放钮
 *     （AVPlayer）+ 产物链接；提交失败诚实透出服务端 detail（如未配置音乐服务商）。
 *   - 颜色统一走 StyleManager，路由走 Router，API 暂无 AIGC 专用模块 →
 *     aboutToAppear 经 api.aigc.listTasks 拉真实账本；processing 存在时 5s 自动刷新。
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassCard、GlassButton、GlassInput、GlassPanel
 *   - ../libs/api/ApiFacade：统一 API 门面（M5a 已接 aigc 域真实 API）
 *   - ../routing/Router：统一路由跳转
 *   - ../libs/style/StyleManager：统一样式 token
 *   - ../libs/logger/Logger：统一日志
 *   - ../libs/message/MessageManager：统一消息提示
 *   - ../libs/types：AIGCTask、AIGCTaskStatus
 *
 * 用法：
 *   由 Router.push(RouteNames.AIGC) 跳转进入；
 *   aboutToAppear 经 api.aigc.listTasks() 加载真实任务列表；
 *   status 筛选 Tab 切换 → 本地按 status 过滤；
 *   新建 → 弹窗选择 type + 填 prompt（music 另填时长）→ 提交 →
 *   api.aigc.generateText/Image/Audio/submitVideo/submitMusic；
 *   查看详情 → AlertDialog 展示完整 prompt + 元数据；
 *   取消（queued/processing）→ 服务端账本无取消端点，诚实提示不支持（Web 端契约同）；
 *   重试（failed）→ 以同 prompt 重新提交（新任务，服务端账本保留失败历史）。
 *
 * TDD：AIGCViewHelper 各方法按红绿灯垂直切片逐步实现，详见 AIGCPage.test.ets
 */

import { TopNavMenu, GlassCard, GlassButton, GlassInput, GlassPanel } from '../components/glass';
import { media } from '@kit.MediaKit';
import { BusinessError } from '@ohos.base';
import { ApiFacade } from '../libs/api/ApiFacade';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { AIGCTask, AIGCTaskStatus, AigcGenerationTask } from '../libs/types';

/** 日志标签 */
const TAG = 'AIGCPage';

/** prompt 截断默认最大长度 */
const DEFAULT_PROMPT_MAX_LEN = 100;

/** 秒级阈值：超过 60 秒切换为 M:SS 格式 */
const SECONDS_THRESHOLD = 60;

/** 音乐时长缺省（秒）——后端 MusicGenerationRequest.duration 缺省同值 */
const MUSIC_DURATION_DEFAULT = 30;

/** 音乐时长下限（秒） */
const MUSIC_DURATION_MIN = 1;

/** 音乐时长上限（秒）——与 Web 端 MusicGenPage 同口径 */
const MUSIC_DURATION_MAX = 600;

// ===========================================================================
// AIGCViewHelper - AIGC 任务视图模型（纯函数，无 UI 依赖，可独立单元测试）
// ===========================================================================

export class AIGCViewHelper {
  /**
   * 获取任务类型对应的颜色 token 名
   * 映射：text→info，image→primary，audio→warning，video→error，music→success
   */
  static getTypeColor(type: AIGCTaskKind): string {
    if (type === 'text') return 'info';
    if (type === 'image') return 'primary';
    if (type === 'audio') return 'warning';
    if (type === 'video') return 'error';
    if (type === 'music') return 'success';
    throw new Error(`getTypeColor 未实现: ${type}`);
  }

  /**
   * 获取任务类型对应的图标 emoji
   * 映射：text→📝，image→🖼️，audio→🎵，video→🎬，music→🎼
   */
  static getTypeIcon(type: AIGCTaskKind): string {
    if (type === 'text') return '📝';
    if (type === 'image') return '🖼️';
    if (type === 'audio') return '🎵';
    if (type === 'video') return '🎬';
    if (type === 'music') return '🎼';
    throw new Error(`getTypeIcon 未实现: ${type}`);
  }

  /**
   * 获取任务类型对应的中文标签
   * 映射：text→文本，image→图像，audio→音频，video→视频，music→音乐
   */
  static getTypeLabel(type: AIGCTaskKind): string {
    if (type === 'text') return '文本';
    if (type === 'image') return '图像';
    if (type === 'audio') return '音频';
    if (type === 'video') return '视频';
    if (type === 'music') return '音乐';
    throw new Error(`getTypeLabel 未实现: ${type}`);
  }

  /**
   * 获取任务状态对应的颜色 token 名
   * 映射：queued→warning，processing→info，succeeded→success，failed→error
   */
  static getStatusColor(status: AIGCTaskStatus): string {
    if (status === 'queued') return 'warning';
    if (status === 'processing') return 'info';
    if (status === 'succeeded') return 'success';
    if (status === 'failed') return 'error';
    throw new Error(`getStatusColor 未实现: ${status}`);
  }

  /**
   * 获取任务状态对应的图标 emoji
   * 映射：queued→⏳，processing→⚡，succeeded→✅，failed→❌
   */
  static getStatusIcon(status: AIGCTaskStatus): string {
    if (status === 'queued') return '⏳';
    if (status === 'processing') return '⚡';
    if (status === 'succeeded') return '✅';
    if (status === 'failed') return '❌';
    throw new Error(`getStatusIcon 未实现: ${status}`);
  }

  /**
   * 获取任务状态对应的中文标签
   * 映射：queued→排队中，processing→处理中，succeeded→已完成，failed→失败
   */
  static getStatusLabel(status: AIGCTaskStatus): string {
    if (status === 'queued') return '排队中';
    if (status === 'processing') return '处理中';
    if (status === 'succeeded') return '已完成';
    if (status === 'failed') return '失败';
    throw new Error(`getStatusLabel 未实现: ${status}`);
  }

  /**
   * 截断 prompt，超长时截取 maxLen 字符并追加省略号
   * @param prompt 原始 prompt
   * @param maxLen 最大字符数，默认 100
   * @return 截断后的 prompt；未超长则原样返回
   */
  static truncatePrompt(prompt: string, maxLen: number = DEFAULT_PROMPT_MAX_LEN): string {
    if (prompt.length <= maxLen) return prompt;
    return prompt.substring(0, maxLen) + '...';
  }

  /**
   * 格式化任务耗时
   * 规则：
   *   - 无 finishedAt → "—"
   *   - 差值 < 60 秒 → "n.nn s"（保留 2 位小数）
   *   - 差值 ≥ 60 秒 → "M:SS"（分:秒，秒数补 0）
   * @param startedAt 开始时间 ISO 字符串
   * @param finishedAt 结束时间 ISO 字符串（可选）
   * @return 耗时展示字符串
   */
  static formatDuration(startedAt: string, finishedAt?: string): string {
    if (!finishedAt) return '—';
    const start = new Date(startedAt).getTime();
    const end = new Date(finishedAt).getTime();
    if (isNaN(start) || isNaN(end)) return '—';
    const diffMs = end - start;
    if (diffMs < 0) return '—';
    const diffSec = diffMs / 1000;
    if (diffSec < SECONDS_THRESHOLD) {
      return `${diffSec.toFixed(2)} s`;
    }
    const minutes = Math.floor(diffSec / 60);
    const seconds = Math.floor(diffSec % 60);
    return `${minutes}:${seconds.toString().padStart(2, '0')}`;
  }
}

/** 状态筛选 Tab 配置 */
interface StatusFilterOption {
  value: string;     // 'all' 或 AIGCTaskStatus
  label: string;
}

/** 状态筛选 Tab 列表 */
const STATUS_FILTERS: StatusFilterOption[] = [
  { value: 'all', label: '全部' },
  { value: 'queued', label: '排队中' },
  { value: 'processing', label: '处理中' },
  { value: 'succeeded', label: '已完成' },
  { value: 'failed', label: '失败' },
];

/** 任务类型（AIGCTask.type 的具名别名；ArkTS 不支持索引访问类型） */
type AIGCTaskKind = 'text' | 'image' | 'audio' | 'video' | 'music';

/** 类型选择项（ForEach 选项；ArkTS 禁内联对象类型与索引访问类型） */
interface AIGCTypeOption {
  type: AIGCTaskKind;
  label: string;
  icon: string;
}

/** 新建任务表单数据 */
interface AIGCTaskFormData {
  type: AIGCTaskKind;
  prompt: string;
  /** 音乐时长输入（秒；字符串承自输入框，提交前经 parseMusicDurationSeconds 校验） */
  duration: string;
}

/**
 * 解析音乐时长输入（秒）：空串→缺省 30；非正整数/越界（1-600）→ -1（调用方诚实报错）。
 * 后端 duration 为整数秒，小数会被 pydantic 拒绝，故在提交前拦下。
 */
export function parseMusicDurationSeconds(raw: string): number {
  const text = (raw || '').trim();
  if (!text) {
    return MUSIC_DURATION_DEFAULT;
  }
  const n = Number(text);
  if (!Number.isFinite(n)) {
    return -1;
  }
  const sec = Math.floor(n);
  if (sec !== n || sec < MUSIC_DURATION_MIN || sec > MUSIC_DURATION_MAX) {
    return -1;
  }
  return sec;
}

/**
 * 服务端错误消息归一：FastAPI HTTPException 落 {detail}（如「未配置音乐服务商凭据」），
 * 业务信封错误落 {message}——取其一诚实透出，避免失败被通用兜底文案吞掉。
 */
export function aigcErrorMessage(res: Object, fallback: string): string {
  const rec = res as Record<string, Object>;
  const detail = rec['detail'];
  if (typeof detail === 'string' && detail) {
    return detail;
  }
  const message = rec['message'];
  if (typeof message === 'string' && message) {
    return message;
  }
  return fallback;
}

/** 服务端账本行 → 本地 AIGCTask（纯函数，供 AIGCPage.test.ets 契约测试） */
export function aigcTaskFromServer(t: AigcGenerationTask, fileUrl: string): AIGCTask {
  const status: AIGCTaskStatus =
    t.status === 'succeeded' || t.status === 'done' ? 'succeeded'
      : t.status === 'failed' ? 'failed'
      : t.status === 'pending' ? 'queued' : 'processing';
  const task: AIGCTask = {
    id: t.task_id,
    agentId: '',
    type: (t.kind === 'text' ? 'text' : t.kind === 'audio' ? 'audio'
      : t.kind === 'video' ? 'video' : t.kind === 'music' ? 'music' : 'image') as AIGCTaskKind,
    prompt: t.prompt,
    status: status,
    resultUrl: t.file_missing ? undefined : (fileUrl || undefined),
    errorMessage: t.file_missing ? '产物已按保留策略清理'
      : (t.error || (status === 'succeeded' && !fileUrl ? '产物尚未落盘' : undefined)),
    createdAt: new Date(t.submitted_at * 1000).toISOString(),
    finishedAt: t.updated_at ? new Date(t.updated_at * 1000).toISOString() : undefined,
  };
  return task;
}

@Component
export struct AIGCPage {
  // AIGC 任务列表
  @State tasks: AIGCTask[] = [];
  // 加载态
  @State loading: boolean = true;
  // 当前激活的状态筛选
  @State activeStatus: string = 'all';
  // 新建弹窗显示状态
  @State showCreateDialog: boolean = false;
  // 新建表单数据（嵌套属性变更需整体重新赋值）
  @State formData: AIGCTaskFormData = { type: 'text', prompt: '', duration: '30' };

  // 正在播放的音乐任务 id（''=未播放）
  @State playingTaskId: string = '';

  // 音乐播放器（一次只挂一个；停止/切页即释放）
  private avPlayer: media.AVPlayer | null = null;

  // 统一库单例
  private api = ApiFacade.getInstance();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private msg = MessageManager.getInstance();

  // 未决任务自动刷新定时器句柄（-1=未启动）
  private pollTimer: number = -1;

  aboutToAppear() {
    this.loadTasks();
  }

  aboutToDisappear() {
    if (this.pollTimer >= 0) {
      clearInterval(this.pollTimer);
      this.pollTimer = -1;
    }
    this.stopMusicPlayback();
  }

  /**
   * 加载任务列表（api.aigc.listTasks → 服务端账本映射；processing 存在时 5s 轮询）
   */
  private async loadTasks(): Promise<void> {
    try {
      const res = await this.api.aigc.listTasks();
      if (res.code === 0 && res.data) {
        this.tasks = res.data.map((t: AigcGenerationTask) =>
          aigcTaskFromServer(t, this.api.aigc.fileUrl(t.url)));
        this.ensurePolling();
      } else {
        this.msg.error(res.message || '加载 AIGC 任务失败');
      }
    } catch (e) {
      this.logger.error(TAG, '加载任务失败', e as Error);
      this.msg.error('加载 AIGC 任务失败');
    } finally {
      this.loading = false;
    }
  }

  /** 存在 processing 任务 → 5s 自动刷新；全终态自停（Web AigcHistoryList 同语义） */
  private ensurePolling(): void {
    const running = this.tasks.some((t: AIGCTask) =>
      t.status === 'processing' || t.status === 'queued');
    if (running && this.pollTimer < 0) {
      this.pollTimer = setInterval(() => { this.loadTasks(); }, 5000);
    } else if (!running && this.pollTimer >= 0) {
      clearInterval(this.pollTimer);
      this.pollTimer = -1;
    }
  }

  /** 切换状态筛选 */
  private switchStatus(value: string): void {
    this.activeStatus = value;
  }

  /**
   * 获取经状态筛选后的列表
   */
  private getFilteredTasks(): AIGCTask[] {
    if (this.activeStatus === 'all') {
      return this.tasks;
    }
    return this.tasks.filter((t: AIGCTask) => t.status === this.activeStatus);
  }

  /** 打开新建弹窗，重置表单 */
  private openCreateDialog(): void {
    this.formData = { type: 'text', prompt: '', duration: MUSIC_DURATION_DEFAULT.toString() };
    this.showCreateDialog = true;
  }

  /**
   * 提交新建任务（按 type 分派真实端点；image/audio/text 同步出结果，
   * video/music 异步落账本后由列表轮询推进）
   */
  private async submitCreate(): Promise<void> {
    const prompt = this.formData.prompt.trim();
    if (!prompt) {
      this.msg.warning('请填写 prompt');
      return;
    }
    let musicDuration = MUSIC_DURATION_DEFAULT;
    if (this.formData.type === 'music') {
      musicDuration = parseMusicDurationSeconds(this.formData.duration);
      if (musicDuration < 0) {
        this.msg.warning(`请填写有效时长（${MUSIC_DURATION_MIN}-${MUSIC_DURATION_MAX} 秒整数）`);
        return;
      }
    }
    this.msg.info('任务已提交，生成中…');
    this.showCreateDialog = false;
    try {
      if (this.formData.type === 'text') {
        const res = await this.api.aigc.generateText({ prompt: prompt });
        if (res.code === 0 && res.data) {
          AlertDialog.show({ title: '生成结果', message: res.data.text.slice(0, 500),
            autoCancel: true, alignment: DialogAlignment.Center,
            primaryButton: { value: '关闭', action: () => {} } });
        } else {
          this.msg.error(res.message || '文本生成失败');
        }
      } else if (this.formData.type === 'image') {
        const res = await this.api.aigc.generateImage({ prompt: prompt });
        if (res.code !== 0) { this.msg.error(res.message || '图像生成失败'); }
      } else if (this.formData.type === 'audio') {
        const res = await this.api.aigc.generateAudio({ text: prompt });
        if (res.code !== 0) { this.msg.error(res.message || '语音合成失败'); }
      } else if (this.formData.type === 'music') {
        // 模型/服务商不随请求下发：服务端按能力路由到默认 fal 音乐模型；
        // 未配置音乐服务商时后端 400/502，detail 原文透出（不伪造成功）
        const res = await this.api.aigc.submitMusic({ prompt: prompt, duration: musicDuration });
        if (res.code !== 0) {
          this.msg.error(aigcErrorMessage(res, '音乐生成提交失败'));
        }
      } else {
        const res = await this.api.aigc.submitVideo({ prompt: prompt });
        if (res.code !== 0) { this.msg.error(res.message || '视频提交失败'); }
      }
    } catch (e) {
      this.logger.error(TAG, '创建任务失败', e as Error);
      this.msg.error('创建任务失败');
    } finally {
      // 账本刷新：image/audio/video/music 成败均已落账，列表直读服务端状态
      this.loadTasks();
    }
  }

  /** 选择 type（嵌套属性变更：整体重新赋值） */
  private selectType(type: AIGCTaskKind): void {
    this.formData = { type: type, prompt: this.formData.prompt, duration: this.formData.duration };
  }

  /** 输入 prompt（嵌套属性变更：整体重新赋值） */
  private inputPrompt(v: string): void {
    this.formData = { type: this.formData.type, prompt: v, duration: this.formData.duration };
  }

  /** 输入音乐时长（嵌套属性变更：整体重新赋值） */
  private inputDuration(v: string): void {
    this.formData = { type: this.formData.type, prompt: this.formData.prompt, duration: v };
  }

  /**
   * 查看详情
   * AlertDialog 展示完整 prompt + 元数据
   */
  private showDetail(task: AIGCTask): void {
    const message =
      `类型：${AIGCViewHelper.getTypeLabel(task.type)}\n\n` +
      `状态：${AIGCViewHelper.getStatusLabel(task.status)}\n\n` +
      `Prompt：\n${task.prompt}\n\n` +
      `创建时间：${this.formatTime(task.createdAt)}\n` +
      `完成时间：${this.formatTime(task.finishedAt)}`;
    AlertDialog.show({
      title: '任务详情',
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
   * 取消任务前二次确认（仅 queued/processing 状态可取消）
   */
  private confirmCancel(task: AIGCTask): void {
    AlertDialog.show({
      title: '确认取消',
      message: `确定要取消任务吗？`,
      autoCancel: true,
      alignment: DialogAlignment.Center,
      primaryButton: {
        value: '取消',
        action: () => {}
      },
      secondaryButton: {
        value: '确认',
        fontColor: this.sm.getColor('error'),
        action: () => { this.cancelTask(task.id); }
      }
    });
  }

  /**
   * 取消任务：服务端生成账本无取消端点（Web 契约同）——本地移除是假取消，
   * 任务仍会跑完计费，M5a 改诚实提示（任务将继续生成，可在结果中忽略）。
   */
  private async cancelTask(taskId: string): Promise<void> {
    this.msg.warning('生成任务不支持取消：远端将继续完成，可忽略结果');
  }

  /**
   * 重试失败任务：以同 prompt 重新提交（新账本任务；失败历史保留可追溯）
   */
  private async retryTask(task: AIGCTask): Promise<void> {
    try {
      if (task.type === 'image') {
        await this.api.aigc.generateImage({ prompt: task.prompt });
      } else if (task.type === 'video') {
        await this.api.aigc.submitVideo({ prompt: task.prompt });
      } else if (task.type === 'audio') {
        await this.api.aigc.generateAudio({ text: task.prompt });
      } else if (task.type === 'music') {
        // 服务端账本不保留时长参数：音乐重试按缺省 30 秒重新提交（同 prompt 可追溯）
        await this.api.aigc.submitMusic({ prompt: task.prompt, duration: MUSIC_DURATION_DEFAULT });
      } else {
        await this.api.aigc.generateText({ prompt: task.prompt });
      }
      this.msg.success('已重新提交');
      this.loadTasks();
    } catch (e) {
      this.logger.error(TAG, '重试任务失败', e as Error);
      this.msg.error('重试任务失败');
    }
  }

  /**
   * 播放/停止音乐产物（AVPlayer；一次只播一个，切页即停）。
   * 播放源为 resultUrl（fileUrl 已拼 access_token 查询凭证的绝对地址）。
   */
  private async toggleMusicPlayback(task: AIGCTask): Promise<void> {
    if (this.playingTaskId === task.id) {
      await this.stopMusicPlayback();
      return;
    }
    if (!task.resultUrl) {
      this.msg.warning('该任务暂无可播放的音频产物');
      return;
    }
    await this.stopMusicPlayback();
    try {
      const player = await media.createAVPlayer();
      const playUrl = task.resultUrl;
      this.avPlayer = player;
      this.playingTaskId = task.id;
      player.on('stateChange', (state: media.AVPlayerState) => {
        if (this.avPlayer !== player) {
          return; // 已被新的播放/停止释放：过期回调直接忽略
        }
        if (state === 'idle') {
          player.url = playUrl; // idle 态设源 → initialized
        } else if (state === 'initialized') {
          // 失败时 'error' 事件负责诚实提示；此处 catch 仅兜住未决拒绝
          player.prepare().catch(() => { this.stopMusicPlayback(); });
        } else if (state === 'prepared') {
          player.play().catch(() => { this.stopMusicPlayback(); });
        } else if (state === 'completed' || state === 'error') {
          this.stopMusicPlayback();
        }
      });
      player.on('error', (err: BusinessError) => {
        this.logger.error(TAG, '音频播放失败', new Error(err.message));
        if (this.avPlayer === player) {
          this.msg.error('音频播放失败');
          this.stopMusicPlayback();
        }
      });
    } catch (e) {
      this.logger.error(TAG, '音频播放初始化失败', e as Error);
      this.msg.error('音频播放初始化失败');
      this.avPlayer = null;
      this.playingTaskId = '';
    }
  }

  /** 停止并释放音乐播放器（未 prepare 的 player stop 会抛错，释放即可） */
  private async stopMusicPlayback(): Promise<void> {
    const player = this.avPlayer;
    this.avPlayer = null;
    this.playingTaskId = '';
    if (!player) {
      return;
    }
    try {
      await player.stop();
    } catch (e) {
      // idle/initialized 态 stop 非法：忽略，直接释放
    }
    try {
      await player.release();
    } catch (e) {
      // 已释放：忽略
    }
  }

  /** 格式化时间（YYYY-MM-DD HH:mm），无值回退 '未知' */
  private formatTime(time?: string): string {
    if (!time) return '未知';
    const d = new Date(time);
    if (isNaN(d.getTime())) return '未知';
    const yyyy = d.getFullYear();
    const MM = (d.getMonth() + 1).toString().padStart(2, '0');
    const dd = d.getDate().toString().padStart(2, '0');
    const hh = d.getHours().toString().padStart(2, '0');
    const mm = d.getMinutes().toString().padStart(2, '0');
    return `${yyyy}-${MM}-${dd} ${hh}:${mm}`;
  }

  build() {
    Stack() {
      Column() {
        // 顶部导航栏：标题"AIGC 任务" + 返回 + 新建
        TopNavMenu({
          title: 'AIGC 任务',
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
        } else if (this.getFilteredTasks().length === 0) {
          Column() {
            Text('暂无任务')
              .fontSize(this.sm.getFontSize('subtitle'))
              .fontColor(this.sm.getColor('text_secondary'))
          }
          .width('100%')
          .layoutWeight(1)
          .justifyContent(FlexAlign.Center)
          .alignItems(HorizontalAlign.Center)
        } else {
          List({ space: 12 }) {
            ForEach(this.getFilteredTasks(), (task: AIGCTask) => {
              ListItem() {
                this.buildTaskCard(task)
              }
            }, (task: AIGCTask) => task.id)
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

      // 新建任务弹窗
      if (this.showCreateDialog) {
        this.buildCreateDialog()
      }
    }
    .width('100%')
    .height('100%')
  }

  // ===========================================================================
  // 任务卡片构建器
  // ===========================================================================

  /** 单个任务卡片：类型徽章 + prompt 摘要 + 状态徽章 + resultUrl/errorMessage + 操作按钮 */
  @Builder
  buildTaskCard(task: AIGCTask) {
    GlassCard() {
      Column() {
        // 顶部行：类型图标 + 类型徽章 + 状态徽章
        Row() {
          Text(AIGCViewHelper.getTypeIcon(task.type))
            .fontSize(20)
          Text(AIGCViewHelper.getTypeLabel(task.type))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_on_primary'))
            .padding({ left: 6, right: 6, top: 2, bottom: 2 })
            .borderRadius(this.sm.getRadius('sm'))
            .backgroundColor(this.sm.getColor(AIGCViewHelper.getTypeColor(task.type)))
            .margin({ left: this.sm.getSpacing('xs') })
          Text(AIGCViewHelper.getStatusIcon(task.status))
            .fontSize(16)
            .margin({ left: this.sm.getSpacing('sm') })
          Text(AIGCViewHelper.getStatusLabel(task.status))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor(AIGCViewHelper.getStatusColor(task.status)))
            .margin({ left: 4 })
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)

        // prompt 摘要（默认 100 字符截断）
        Text(AIGCViewHelper.truncatePrompt(task.prompt))
          .fontSize(this.sm.getFontSize('body'))
          .fontColor(this.sm.getColor('text_primary'))
          .maxLines(2)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .margin({ top: this.sm.getSpacing('xs') })
          .width('100%')

        // resultUrl（succeeded 时显示）
        if (task.status === 'succeeded' && task.resultUrl) {
          Text(`结果: ${task.resultUrl}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('primary'))
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
            .margin({ top: 4 })
            .width('100%')
        }

        // 音乐产物播放钮（succeeded 且有产物；AVPlayer 播放，一次一个）
        if (task.type === 'music' && task.status === 'succeeded' && task.resultUrl) {
          Row() {
            GlassButton({
              text: this.playingTaskId === task.id ? '停止' : '播放',
              type: 'default',
              btnSize: 'small',
              onTap: () => { this.toggleMusicPlayback(task); }
            })
            Text('音频产物')
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_disabled'))
              .margin({ left: this.sm.getSpacing('sm') })
          }
          .width('100%')
          .alignItems(VerticalAlign.Center)
          .margin({ top: 4 })
        }

        // errorMessage（failed 时显示）
        if (task.status === 'failed' && task.errorMessage) {
          Text(`错误: ${task.errorMessage}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('error'))
            .maxLines(2)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
            .margin({ top: 4 })
            .width('100%')
        }

        // 时间行：创建 + 完成 + 耗时
        Row() {
          Text(`创建: ${this.formatTime(task.createdAt)}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_disabled'))
            .layoutWeight(1)
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
          Text(`耗时: ${AIGCViewHelper.formatDuration(task.createdAt, task.finishedAt)}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_disabled'))
        }
        .width('100%')
        .margin({ top: this.sm.getSpacing('xs') })
        .alignItems(VerticalAlign.Center)

        // 操作按钮：查看详情 + 取消（queued/processing）+ 重试（failed）
        Row() {
          GlassButton({
            text: '详情',
            type: 'default',
            btnSize: 'small',
            onTap: () => { this.showDetail(task); }
          })
          if (task.status === 'queued' || task.status === 'processing') {
            GlassButton({
              text: '取消',
              type: 'danger',
              btnSize: 'small',
              onTap: () => { this.confirmCancel(task); }
            })
              .margin({ left: this.sm.getSpacing('sm') })
          }
          if (task.status === 'failed') {
            GlassButton({
              text: '重试',
              type: 'primary',
              btnSize: 'small',
              onTap: () => { this.retryTask(task); }
            })
              .margin({ left: this.sm.getSpacing('sm') })
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

  // ===========================================================================
  // 新建任务弹窗构建器（Stack 内嵌条件渲染）
  // ===========================================================================

  /** 新建任务弹窗：type 选择 + prompt 文本域 */
  @Builder
  buildCreateDialog() {
    Stack({ alignContent: Alignment.Center }) {
      // 背景遮罩层：点击空白处关闭
      Column()
        .width('100%')
        .height('100%')
        .backgroundColor(this.sm.getColor('overlay_mask'))
        .onClick(() => { this.showCreateDialog = false; })

      // 面板层：居中展示（GlassPanel 为自定义组件，不能直接链 .width；90% 挂在外层 Column）
      Column() {
      GlassPanel({ variant: 'elevated', innerPadding: 20 }) {
        Column() {
          Text('新建 AIGC 任务')
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontWeight(FontWeight.Bold)
            .fontColor(this.sm.getColor('text_primary'))
            .width('100%')

          // 类型选择
          Text('任务类型')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .width('100%')
            .margin({ top: this.sm.getSpacing('sm') })
          // 类型下拉（按钮排布在窄屏会超出面板宽度产生错位——改系统下拉菜单）
          Select(this.createTypeSelectOptions())
            .selected(this.getCurrentTypeIndex())
            .value(this.getCurrentTypeLabel())
            .font({ size: this.sm.getFontSize('body_sm') })
            .fontColor(this.sm.getColor('text_primary'))
            .selectedOptionFont({ size: this.sm.getFontSize('body_sm') })
            .optionFont({ size: this.sm.getFontSize('body_sm') })
            .selectedOptionFontColor(this.sm.getColor('primary'))
            .width('100%')
            .margin({ top: this.sm.getSpacing('xs'), bottom: this.sm.getSpacing('sm') })
            .onSelect((index: number) => {
              const opts = this.getTypeOptions();
              if (index >= 0 && index < opts.length) {
                this.selectType(opts[index].type);
              }
            })

          // prompt 文本域（用 GlassInput 模拟多行输入）
          Text('Prompt')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .width('100%')
          GlassInput({
            placeholder: '请输入 prompt...',
            value: this.formData.prompt,
            type: 'text',
            onChange: (v: string) => { this.inputPrompt(v); },
          })
            .margin({ top: 4, bottom: this.sm.getSpacing('md') })

          // 音乐类型追加：时长（秒）输入 + 路由口径诚实提示（无预置模型列表，不硬编码假模型）
          if (this.formData.type === 'music') {
            Text('时长（秒）')
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .width('100%')
            GlassInput({
              placeholder: `缺省 ${MUSIC_DURATION_DEFAULT} 秒（${MUSIC_DURATION_MIN}-${MUSIC_DURATION_MAX}）`,
              value: this.formData.duration,
              type: 'number',
              onChange: (v: string) => { this.inputDuration(v); },
            })
              .margin({ top: 4, bottom: this.sm.getSpacing('xs') })
            Text('模型由服务端按能力路由；未配置音乐服务商时提交将失败并提示原因')
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_disabled'))
              .width('100%')
              .margin({ bottom: this.sm.getSpacing('sm') })
          }

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

  /** 获取任务类型选项列表 */
  private getTypeOptions(): AIGCTypeOption[] {
    const types: AIGCTaskKind[] = ['text', 'image', 'audio', 'video', 'music'];
    return types.map((t: AIGCTaskKind): AIGCTypeOption => ({
      type: t,
      label: AIGCViewHelper.getTypeLabel(t),
      icon: AIGCViewHelper.getTypeIcon(t),
    }));
  }

  /** 任务类型下拉选项（SelectOption 形） */
  private createTypeSelectOptions(): SelectOption[] {
    return this.getTypeOptions().map((opt: AIGCTypeOption) => {
      const so: SelectOption = { value: `${opt.icon} ${opt.label}` };
      return so;
    });
  }

  /** 当前选中类型的下标 */
  private getCurrentTypeIndex(): number {
    const opts = this.getTypeOptions();
    for (let i = 0; i < opts.length; i++) {
      if (opts[i].type === this.formData.type) {
        return i;
      }
    }
    return 0;
  }

  /** 当前选中类型的展示文案 */
  private getCurrentTypeLabel(): string {
    const opt = this.getTypeOptions()[this.getCurrentTypeIndex()];
    return `${opt.icon} ${opt.label}`;
  }
}
