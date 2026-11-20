/**
 * AudioApi - 音频域 API 模块（录音纪要链 B4-8）
 *
 * 后端事实源（audio.py @ /v1/audio，JWT 面）：
 *   POST /audio/minutes          → multipart file；{queued, job_id}（队列满 429+input_gap 证据）
 *   GET  /audio/minutes/{job_id} → {status, transcript, summary, kind, task_id, task_title, error}
 *
 * 链路：录音 → 转写 → 一次 LLM 同出纪要与问题/办事判定 → 办事落任务看板。
 */
import { HttpClient } from '../HttpClient';
import { ApiResponse } from '../../types';

export class AudioApi {
  private client: HttpClient;

  constructor(client: HttpClient) {
    this.client = client;
  }

  /**
   * 上传录音入队（有界队列；满时后端 429 + input_gap 证据，不静默丢）。
   * multipart 单文件上传（与 knowledge/import 同一 HttpClient 通道）。
   */
  async createMinutes(fileName: string, fileBytes: ArrayBuffer, fileMime: string): Promise<ApiResponse<Object>> {
    return this.client.postMultipart<Object>('/audio/minutes', fileName, fileBytes, fileMime);
  }

  /** 轮询纪要作业状态/结果。 */
  async getMinutesStatus(jobId: string): Promise<ApiResponse<Object>> {
    return this.client.get<Object>(`/audio/minutes/${jobId}`);
  }
}
