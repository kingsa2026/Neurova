/**
 * AigcApi - AIGC 生成域 API 模块（M5a，对齐 Web generation.ts 契约）
 *
 * 职责：文本/图像/音频/视频生成 + 视频状态轮询 + 任务账本 + 音色 + 用量。
 * 设计：通过 HttpClient 委托请求，统一返回 Promise<ApiResponse<T>>；
 *       路径与字段与 NeurUI/src/api/modules/generation.ts 单源语义一致
 *       （auto=服务端 LLMRouter 能力路由；provider_id 指定服务商凭据）。
 *
 * 用法：
 *   const api = ApiFacade.getInstance().aigc;
 *   const res = await api.listTasks('image');
 *   await api.submitVideo({ prompt: '...', image_url: '/api/v1/generation/files/x.png' });
 *
 * TDD：AigcApi.test.ets（MockBackend 记录请求断言 URL/body 形状）。
 */
import { HttpClient } from '../HttpClient';
import {
  ApiResponse,
  AigcTextPayload,
  AigcImagePayload,
  AigcAudioPayload,
  AigcVideoPayload,
  AigcTextResult,
  AigcImageResult,
  AigcVideoSubmitResult,
  AigcVideoStatusResult,
  AigcGenerationTask,
  AigcVoiceOption,
  AigcUsageSummary,
} from '../../types';

const BASE = '/v1/generation';

export class AigcApi {
  constructor(private client: HttpClient) {}

  /** 文本生成（同步返回全文；model 缺省/auto=服务端路由） */
  async generateText(data: AigcTextPayload): Promise<ApiResponse<AigcTextResult>> {
    return this.client.post<AigcTextResult>(`${BASE}/text`, data);
  }

  /** 图像生成（同步返回 urls；成败均落账本） */
  async generateImage(data: AigcImagePayload): Promise<ApiResponse<AigcImageResult>> {
    return this.client.post<AigcImageResult>(`${BASE}/image`, data);
  }

  /** 语音合成（返回音频产物 url） */
  async generateAudio(data: AigcAudioPayload): Promise<ApiResponse<AigcImageResult>> {
    return this.client.post<AigcImageResult>(`${BASE}/audio`, data);
  }

  /** 视频任务提交（异步，返回 task_id 供轮询） */
  async submitVideo(data: AigcVideoPayload): Promise<ApiResponse<AigcVideoSubmitResult>> {
    return this.client.post<AigcVideoSubmitResult>(`${BASE}/video`, data);
  }

  /** 视频任务轮询（账本 + 远程协议收口） */
  async videoStatus(taskId: string): Promise<ApiResponse<AigcVideoStatusResult>> {
    return this.client.get<AigcVideoStatusResult>(`${BASE}/video/status/${taskId}`);
  }

  /** 任务账本列表（可按 kind/status 过滤；仅本人任务） */
  async listTasks(kind?: string, status?: string): Promise<ApiResponse<AigcGenerationTask[]>> {
    const query: Record<string, Object> = {};
    if (kind) {
      query['kind'] = kind;
    }
    if (status) {
      query['status'] = status;
    }
    const res = await this.client.get<Object>(`${BASE}/tasks`, query);
    // 服务端返回 {tasks: [...]}（Web 端 getTasks 同形态），拆信封
    const wrapped = res.data as Record<string, Object> | null;
    const tasks: AigcGenerationTask[] =
      wrapped && Array.isArray(wrapped['tasks']) ? (wrapped['tasks'] as AigcGenerationTask[]) : [];
    return { code: res.code, message: res.message, data: tasks };
  }

  /** 可用音色（引擎真实枚举；空列表=诚实无音色） */
  async listVoices(): Promise<ApiResponse<AigcVoiceOption[]>> {
    const res = await this.client.get<Object>(`${BASE}/voices`);
    const wrapped = res.data as Record<string, Object> | null;
    const voices: AigcVoiceOption[] =
      wrapped && Array.isArray(wrapped['voices']) ? (wrapped['voices'] as AigcVoiceOption[]) : [];
    return { code: res.code, message: res.message, data: voices };
  }

  /** 生成用量统计（近 days 天） */
  async usage(days: number = 30): Promise<ApiResponse<AigcUsageSummary>> {
    const query: Record<string, Object> = { 'days': days };
    return this.client.get<AigcUsageSummary>(`${BASE}/usage`, query);
  }

  /**
   * 产物资源 URL（<img>/<video> src 用）。
   * 服务端 url 为相对路径（/api/v1/generation/files/x.png）且资源标签无法带
   * Authorization 头 → 统一走 ?access_token= 查询凭证回退（BearerOrQuery 契约）。
   * 已是绝对 http(s)（远端临时 URL）原样返回。
   */
  fileUrl(url: string): string {
    if (!url) {
      return '';
    }
    if (url.startsWith('http://') || url.startsWith('https://')) {
      return url;
    }
    const base = this.client.getBaseUrl();
    const token = this.client.getAuthToken();
    const joined = `${base}${url}`;
    if (!token) {
      return joined;
    }
    return `${joined}${joined.includes('?') ? '&' : '?'}access_token=${encodeURIComponent(token)}`;
  }
}
