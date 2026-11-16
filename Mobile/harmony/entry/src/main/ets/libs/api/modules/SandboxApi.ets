/**
 * SandboxApi - 沙盒 API 模块（R6 新增，端点经后端源码核对 2026-11-17）
 *
 * 后端事实源（sandbox.py @ /v1/sandbox，全部信封 {code,message,data}）：
 *   GET    /sandbox               → data:{sandboxes[_publicView],total}
 *   POST   /sandbox/start         ← SandboxStartRequest → data:_publicView
 *                                 （带 agent_id/topic → 思维沙箱；否则代码执行沙箱）
 *   GET    /sandbox/{id}          → data:_publicView
 *   POST   /sandbox/{id}/execute  ← {command,language?,timeout?} → data:执行结果
 *   DELETE /sandbox/{id}          → 销毁
 *
 * _publicView 字段：id/name/status/image/language/timeout/steps_count/
 * created_at/updated_at/agent_id/topic——status 值域 running/failed/timeout/
 * committed（开放集合，未知值兜默认展示）。后端无 CPU/内存限制与过期时间
 * 字段（移动端旧 mock 契约），不投影。
 */
import { HttpClient } from '../HttpClient';
import { asEnvelope } from '../envelope';
import { ApiResponse } from '../../types';

/** 沙盒视图（sandbox.py _publicView 投影，唯一形状） */
export interface SandboxViewDto {
  id: string | null;          // 思维沙箱保留 id 'null'
  name: string;
  status: string;
  image: string;
  language: string;
  timeout: number;            // 秒
  steps_count: number;
  created_at: string;
  updated_at: string;
  agent_id: string | null;
  topic: string | null;
}

/** 启动请求体（sandbox.py SandboxStartRequest） */
export interface SandboxStartBody {
  name?: string;
  image?: string;
  language?: string;
  timeout?: number;
  backend?: string;
  description?: string;
  maxSteps?: number;
  agentId?: string;
  topic?: string;
}

/** 代码执行结果（sandbox.py execute 的 data） */
export interface SandboxExecDto {
  sandbox_id: string;
  output: string;
  stdout: string;
  stderr: string;
  exit_code: number;
  backend: string;
  enforced: boolean;
  timed_out: boolean;
  duration_ms: number;
  steps_count: number;
}

/** 销毁信封 data（sandbox.py destroy_sandbox：{sandbox_id}） */
export interface SandboxDestroyResultDto {
  sandbox_id: string;
}

export class SandboxApi {
  private client: HttpClient;

  constructor(client: HttpClient) {
    this.client = client;
  }

  /** 沙盒列表（GET /sandbox，信封 data.{sandboxes,total} → 展开为数组） */
  async list(status?: string): Promise<ApiResponse<SandboxViewDto[]>> {
    const query: Record<string, Object> = {};
    if (status !== undefined && status.length > 0) {
      query['status'] = status;
    }
    const res = await this.client.get<Record<string, Object>>('/sandbox', query);
    const payload = (res.data ?? {}) as Record<string, Object>;
    const sandboxes = (payload['sandboxes'] ?? []) as Object[] as SandboxViewDto[];
    return { code: res.code, message: res.message, data: sandboxes } as ApiResponse<SandboxViewDto[]>;
  }

  /** 沙盒详情（GET /sandbox/{id}，信封原样） */
  async detail(sandboxId: string): Promise<ApiResponse<SandboxViewDto>> {
    const res = await this.client.get<SandboxViewDto>(`/sandbox/${sandboxId}`);
    return asEnvelope<SandboxViewDto>(res, ['id', 'name']) as ApiResponse<SandboxViewDto>;
  }

  /** 开启沙箱（POST /start，信封原样；镜像白名单外/语言不支持/timeout 越界 → 400 诚实暴露） */
  async start(body: SandboxStartBody): Promise<ApiResponse<SandboxViewDto>> {
    const payload: Record<string, Object> = {};
    if (body.name !== undefined && body.name.length > 0) {
      payload['name'] = body.name;
    }
    if (body.image !== undefined && body.image.length > 0) {
      payload['image'] = body.image;
    }
    if (body.language !== undefined && body.language.length > 0) {
      payload['language'] = body.language;
    }
    if (body.timeout !== undefined) {
      payload['timeout'] = body.timeout;
    }
    if (body.backend !== undefined && body.backend.length > 0) {
      payload['backend'] = body.backend;
    }
    if (body.description !== undefined && body.description.length > 0) {
      payload['description'] = body.description;
    }
    if (body.maxSteps !== undefined) {
      payload['max_steps'] = body.maxSteps;
    }
    if (body.agentId !== undefined && body.agentId.length > 0) {
      payload['agent_id'] = body.agentId;
    }
    if (body.topic !== undefined && body.topic.length > 0) {
      payload['topic'] = body.topic;
    }
    const res = await this.client.post<SandboxViewDto>('/sandbox/start', payload);
    return asEnvelope<SandboxViewDto>(res, ['id', 'name']) as ApiResponse<SandboxViewDto>;
  }

  /** 在沙箱中执行代码（POST /{id}/execute，信封原样；思维沙箱（id='null'）→ 400） */
  async execute(sandboxId: string, command: string, language?: string, timeout?: number): Promise<ApiResponse<SandboxExecDto>> {
    const payload: Record<string, Object> = { 'command': command };
    if (language !== undefined && language.length > 0) {
      payload['language'] = language;
    }
    if (timeout !== undefined) {
      payload['timeout'] = timeout;
    }
    const res = await this.client.post<SandboxExecDto>(`/sandbox/${sandboxId}/execute`, payload);
    return asEnvelope<SandboxExecDto>(res, ['sandbox_id', 'exit_code']) as ApiResponse<SandboxExecDto>;
  }

  /** 销毁沙箱（DELETE /{id}，信封原样） */
  async destroy(sandboxId: string): Promise<ApiResponse<SandboxDestroyResultDto>> {
    const res = await this.client.delete<SandboxDestroyResultDto>(`/sandbox/${sandboxId}`);
    return asEnvelope<SandboxDestroyResultDto>(res, ['sandbox_id']);
  }
}
