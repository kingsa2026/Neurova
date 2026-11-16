/**
 * BenchmarkApi - 基准评测 API 模块（R6 新增，端点经后端源码核对 2026-11-17）
 *
 * 后端事实源（benchmark.py @ /v1/benchmark，全部信封 {code,message,data}）：
 *   GET  /benchmark/suites → data:{suites[BenchmarkSuite],total}
 *   POST /benchmark/run    ← {suite_id,agent_id?,tags?,config?} → data:运行记录
 *                            （P6 诚实化：评测执行器未接线，status='simulated'、
 *                            score/avg_latency_ms 恒 null——页面须如实展示）
 *   GET  /benchmark/runs   ← ?agent_id&suite_id&page&size → data:{items,total,page,size}
 *
 * 后端是 LLM 评测套件域（suite/run），不是移动端旧 mock 的 cpu/memory/disk
 * 系统基准——页面契约随本模块切换。
 */
import { HttpClient } from '../HttpClient';
import { asEnvelope } from '../envelope';
import { ApiResponse } from '../../types';

/** 评测套件（benchmark.py _SUITES 条目） */
export interface BenchmarkSuiteDto {
  id: string;
  name: string;
  description: string;
  tasks: number;
  difficulty: string;         // easy/medium/hard
  category: string;           // memory/creative/multimodal/...
}

/** 一次评测运行记录（benchmark.py run_data） */
export interface BenchmarkRunDto {
  run_id: string;
  suite_id: string;
  suite_name: string;
  agent_id: string | null;
  user_id: string;
  status: string;             // 'simulated'（执行器未接线期间的诚实标记）
  simulated: boolean;
  score: number | null;       // 未接线恒 null
  tasks_total: number;
  tasks_correct: number | null;
  avg_latency_ms: number | null;
  tags: string[];
  config: Record<string, Object>;
  started_at: string;
  completed_at: string;
}

/** /runs 信封 data */
export interface BenchmarkRunsPageDto {
  items: BenchmarkRunDto[];
  total: number;
  page: number;
  size: number;
}

/** 触发运行请求体（benchmark.py BenchmarkRunRequest） */
export interface BenchmarkRunBody {
  suite_id: string;
  agent_id?: string;
  tags?: string[];
  config?: Record<string, Object>;
}

export class BenchmarkApi {
  private client: HttpClient;

  constructor(client: HttpClient) {
    this.client = client;
  }

  /** 评测套件列表（GET /suites，信封 data.{suites,total} → 展开为套件数组） */
  async suites(): Promise<ApiResponse<BenchmarkSuiteDto[]>> {
    const res = await this.client.get<Record<string, Object>>('/benchmark/suites');
    const payload = (res.data ?? {}) as Record<string, Object>;
    const suites = (payload['suites'] ?? []) as Object[] as BenchmarkSuiteDto[];
    return { code: res.code, message: res.message, data: suites } as ApiResponse<BenchmarkSuiteDto[]>;
  }

  /** 触发运行（POST /run，信封原样——message 带"评测执行器未接线"诚实说明，页面透传） */
  async run(body: BenchmarkRunBody): Promise<ApiResponse<BenchmarkRunDto>> {
    const payload: Record<string, Object> = { 'suite_id': body.suite_id };
    if (body.agent_id !== undefined && body.agent_id.length > 0) {
      payload['agent_id'] = body.agent_id;
    }
    if (body.tags !== undefined) {
      payload['tags'] = body.tags;
    }
    if (body.config !== undefined) {
      payload['config'] = body.config;
    }
    const res = await this.client.post<BenchmarkRunDto>('/benchmark/run', payload);
    return asEnvelope<BenchmarkRunDto>(res, ['run_id', 'suite_id']) as ApiResponse<BenchmarkRunDto>;
  }

  /** 运行历史（GET /runs，信封 data.{items,total,page,size} 原样） */
  async runs(agentId?: string, suiteId?: string, page: number = 1, size: number = 20): Promise<ApiResponse<BenchmarkRunsPageDto>> {
    const query: Record<string, Object> = {
      'page': page,
      'size': size,
    };
    if (agentId !== undefined && agentId.length > 0) {
      query['agent_id'] = agentId;
    }
    if (suiteId !== undefined && suiteId.length > 0) {
      query['suite_id'] = suiteId;
    }
    return this.client.get<BenchmarkRunsPageDto>('/benchmark/runs', query);
  }
}
