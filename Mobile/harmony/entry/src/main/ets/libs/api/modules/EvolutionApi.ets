/**
 * EvolutionApi - 演化状态只读域 API 模块（P1-8，接 P1-5 世代治理端点）
 *
 * 后端事实源（governance.py @ /v1/governance，均 admin 门；数据源
 * GenerationLedger，经 agent.rsi_orchestrator.generationOrchestrator）：
 *   GET /governance/rsi/generations?limit=&status= → {code,data:{generations:[摘要],count}}
 *   GET /governance/rsi/generations/current        → {code,data:世代全档}（尚无部署 404）
 *   GET /governance/rsi/generations/{no}           → {code,data:世代全档}
 *   GET /governance/rsi/generations/{no}/lineage   → {code,data:{lineage:[...]}}
 *
 * 诚实纪律（教义第 2 条）：404/503 的 {detail} 错误体在边界归一为
 * {code:1,message:detail}，页面据此如实呈现"尚无基线代/未装配"，
 * 不折成空列表冒充正常。移动端只做只读呈现（P1-8 范围纪律）：
 * 审批/参数写面留在 PC 治理页。
 */

import { HttpClient } from '../HttpClient';
import { asEnvelope } from '../envelope';
import { ApiResponse } from '../../types';

/** 信号引用（generation_ledger.py SignalRef 投影：为什么改） */
export interface EvolutionSignalDto {
  kind: string;
  ref: string;
  summary: string;
}

/** 变更引用（ChangeRef 投影：改了什么） */
export interface EvolutionChangeDto {
  targetId: string;
  kind: string;
  ref: string;
  rationale: string;
}

/** 门禁三态结论（GateVerdict：passed / failed / unevidenced） */
export interface EvolutionVerdictDto {
  state: string;
  reason: string;
}

/** 裁决引用（DecisionRef：auto / approval(approver) / rejected(reason)） */
export interface EvolutionDecisionDto {
  kind: string;
  approver: string;
  reason: string;
}

/** 部署引用（DeploymentRef 投影） */
export interface EvolutionDeploymentDto {
  promotedAt: string;
  canaryConclusion: string;
  rolledBackTo: number | null;
  canaryStartedAt: string;
}

/** 世代全档（EvolutionGeneration.to_dict() 投影，详情面出街） */
export interface EvolutionGenerationDto {
  generationNo: number;
  parentNo: number | null;
  basisCommit: string;
  createdAt: string;
  signals: EvolutionSignalDto[];
  changes: EvolutionChangeDto[];
  verdicts: Record<string, EvolutionVerdictDto>;
  decision: EvolutionDecisionDto | null;
  deployment: EvolutionDeploymentDto | null;
  status: string;
}

/** 列表条目（governance.py _generationSummary：只出摘要字段） */
export interface EvolutionGenerationSummaryDto {
  generationNo: number;
  parentNo: number | null;
  status: string;
  decision: EvolutionDecisionDto | null;
  promotedAt: string;
}

/** 世代列表载荷 */
export interface EvolutionGenerationList {
  generations: EvolutionGenerationSummaryDto[];
  count: number;
}

/** 谱系链载荷 */
export interface EvolutionLineage {
  lineage: EvolutionGenerationDto[];
}

/** 门禁键规范序（G0-G4 摘要按此排序展示） */
export const EVOLUTION_VERDICT_KEYS: string[] = ['g0', 'g1', 'g2', 'g3', 'g4'];

export class EvolutionApi {
  private client: HttpClient;

  constructor(client: HttpClient) {
    this.client = client;
  }

  /** 世代列表（limit 截取最近 N 代；status 可选过滤；空账本 → 空列表） */
  async listGenerations(limit: number = 10, status: string = ''): Promise<ApiResponse<EvolutionGenerationList>> {
    const path = status.length > 0
      ? `/governance/rsi/generations?limit=${limit}&status=${encodeURIComponent(status)}`
      : `/governance/rsi/generations?limit=${limit}`;
    const res = await this.client.get<EvolutionGenerationList>(path);
    return asEnvelope<EvolutionGenerationList>(res, ['generations', 'count']);
  }

  /** 当前生产基线代（序号最大的 deployed 代；尚无部署后端 404 → {code:1,message:detail}） */
  async currentBaseline(): Promise<ApiResponse<EvolutionGenerationDto>> {
    const res = await this.client.get<EvolutionGenerationDto>('/governance/rsi/generations/current');
    return normalizeGenerationEnvelope<EvolutionGenerationDto>(res, ['generationNo', 'status']);
  }

  /** 单代详情（signals/changes/verdicts 全量/decision/deployment） */
  async generationDetail(generationNo: number): Promise<ApiResponse<EvolutionGenerationDto>> {
    const res = await this.client.get<EvolutionGenerationDto>(`/governance/rsi/generations/${generationNo}`);
    return normalizeGenerationEnvelope<EvolutionGenerationDto>(res, ['generationNo', 'status']);
  }

  /** 谱系回溯链（从指定代沿 parentNo 向上到根代，含自身） */
  async generationLineage(generationNo: number): Promise<ApiResponse<EvolutionLineage>> {
    const res = await this.client.get<EvolutionLineage>(`/governance/rsi/generations/${generationNo}/lineage`);
    // {code,data:{lineage:[...]}} 信封直返；裸 {lineage} 形态归一
    if (isDetailError(res as Object)) {
      return toErrorEnvelope<EvolutionLineage>(res as Object);
    }
    if (Array.isArray(res as Object)) {
      const wrapped: ApiResponse<EvolutionLineage> = {
        code: 0,
        message: 'ok',
        data: { lineage: res as Object as EvolutionGenerationDto[] },
      };
      return wrapped;
    }
    const rec = res as Object as Record<string, Object>;
    if (rec['data'] !== undefined && (rec['data'] as Object) !== null) {
      const inner = rec['data'] as Object as Record<string, Object>;
      if (inner['lineage'] !== undefined) {
        return res;
      }
      const wrapped: ApiResponse<EvolutionLineage> = {
        code: 0,
        message: 'ok',
        data: { lineage: inner as Object as EvolutionGenerationDto[] },
      };
      return wrapped;
    }
    return res;
  }
}

/** {detail} 错误体判定（FastAPI HTTPException 形态，无 code/data 键） */
function isDetailError(res: Object): boolean {
  const keys: string[] = Object.keys(res);
  return keys.indexOf('detail') !== -1 && keys.indexOf('code') === -1;
}

/** {detail} → {code:1,message:detail}（页面据此诚实呈现原因） */
function toErrorEnvelope<T>(res: Object): ApiResponse<T> {
  const rec = res as Object as Record<string, Object>;
  const detail = rec['detail'];
  const wrapped: ApiResponse<T> = {
    code: 1,
    message: typeof detail === 'string' ? detail : JSON.stringify(detail),
    data: undefined as T,
  };
  return wrapped;
}

/** 世代端点统一归一：{detail} 错误体 → 错误信封；裸世代对象 → 信封；信封直返 */
function normalizeGenerationEnvelope<T>(res: ApiResponse<T>, probeKeys: string[]): ApiResponse<T> {
  if (isDetailError(res as Object)) {
    return toErrorEnvelope<T>(res as Object);
  }
  return asEnvelope<T>(res, probeKeys);
}
