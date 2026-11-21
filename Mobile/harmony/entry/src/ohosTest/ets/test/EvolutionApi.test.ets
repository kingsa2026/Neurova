// EvolutionApi 单元测试 - P1-8 演化状态只读域（接 P1-5 世代治理端点）
// 后端事实源：governance.py @ /v1/governance——世代四端点均返回 {code,data} 信封；
// 404（尚无基线代）/503（世代管线未装配）返回 {detail} 错误体，模块边界归一为
// {code:1,message:detail}，页面据此诚实呈现（不折成空列表冒充正常）。
import { describe, it, expect, beforeEach } from '@ohos/hypium';
import { HttpClient, HttpBackend, HttpBackendResponse } from '../../../main/ets/libs/api/HttpClient';
import { ApiResponse } from '../../../main/ets/libs/types';
import {
  EvolutionApi,
  EvolutionChangeDto,
  EvolutionDecisionDto,
  EvolutionDeploymentDto,
  EvolutionGenerationDto,
  EvolutionGenerationList,
  EvolutionGenerationSummaryDto,
  EvolutionLineage,
  EvolutionSignalDto,
  EvolutionVerdictDto,
} from '../../../main/ets/libs/api/modules/EvolutionApi';

/** MockBackend 录制的请求（显式接口，替代内联对象字面量类型） */
interface RecordedRequest {
  method: string;
  url: string;
  body: Object | null;
}

/** 后端 {detail} 错误体形状（FastAPI HTTPException） */
interface DetailError {
  detail: string;
}

class MockBackend implements HttpBackend {
  public requests: RecordedRequest[] = [];
  /** 响应体（信封/裸对象/{detail} 错误体——模拟后端真实形状） */
  public responseBody: Object = new Object();

  async request(
    method: string,
    url: string,
    body: Object | null,
    _headers: Record<string, string>,
  ): Promise<HttpBackendResponse> {
    const recorded: RecordedRequest = { method: method, url: url, body: body };
    this.requests.push(recorded);
    const resp: HttpBackendResponse = { status: 200, data: this.responseBody as Object as ApiResponse<Object> };
    return resp;
  }
}

/** 构造一条信号引用（SignalRef 形状，显式类型满足 arkts-no-untyped-obj-literals） */
function sampleSignal(): EvolutionSignalDto {
  const signal: EvolutionSignalDto = { kind: 'lesson', ref: 'lesson-7', summary: 'web_fetch 连续失败' };
  return signal;
}

/** 构造一条变更引用（ChangeRef 形状） */
function sampleChange(): EvolutionChangeDto {
  const change: EvolutionChangeDto = { targetId: 'rsi_escalation_sleep', kind: 'param', ref: 'c-3', rationale: '提升通过率' };
  return change;
}

/** 构造门禁三态表（g0 通过 / g2 未过——三态不折叠的映射样本） */
function sampleVerdicts(): Record<string, EvolutionVerdictDto> {
  const verdicts: Record<string, EvolutionVerdictDto> = {};
  const passed: EvolutionVerdictDto = { state: 'passed', reason: '' };
  const failed: EvolutionVerdictDto = { state: 'failed', reason: '决策档回退' };
  verdicts['g0'] = passed;
  verdicts['g2'] = failed;
  return verdicts;
}

/** 构造一条世代全档（generation_ledger.py EvolutionGeneration.to_dict() 形状） */
function sampleGeneration(no: number): EvolutionGenerationDto {
  const decision: EvolutionDecisionDto = { kind: 'approval', approver: 'admin', reason: '' };
  const deployment: EvolutionDeploymentDto = {
    promotedAt: '2026-11-21T10:00:00+00:00',
    canaryConclusion: 'rollback: 错误率越界',
    rolledBackTo: no - 1,
    canaryStartedAt: '2026-11-21T09:30:00+00:00',
  };
  const signals: EvolutionSignalDto[] = [sampleSignal()];
  const changes: EvolutionChangeDto[] = [sampleChange()];
  const gen: EvolutionGenerationDto = {
    generationNo: no,
    parentNo: no > 1 ? no - 1 : null,
    basisCommit: 'abc1234',
    createdAt: '2026-11-21T09:00:00+00:00',
    signals: signals,
    changes: changes,
    verdicts: sampleVerdicts(),
    decision: decision,
    deployment: deployment,
    status: 'rolledBack',
  };
  return gen;
}

/** 构造列表摘要条目（governance.py _generationSummary 形状） */
function sampleSummary(no: number): EvolutionGenerationSummaryDto {
  const decision: EvolutionDecisionDto = { kind: 'auto', approver: '', reason: '' };
  const summary: EvolutionGenerationSummaryDto = {
    generationNo: no,
    parentNo: no > 1 ? no - 1 : null,
    status: 'deployed',
    decision: decision,
    promotedAt: '2026-11-21T10:00:00+00:00',
  };
  return summary;
}

export default function evolutionApiTest() {
  describe('EvolutionApi', () => {
    let client: HttpClient;
    let backend: MockBackend;
    let api: EvolutionApi;

    beforeEach(() => {
      backend = new MockBackend();
      client = HttpClient.getInstanceWithBackend(backend);
      client.setBaseUrl('https://api.example.com');
      api = new EvolutionApi(client);
    });

    it('list_gets_generations_with_limit', 0, () => {
      api.listGenerations(10);
      const url = backend.requests[0].url;
      expect(backend.requests[0].method).assertEqual('GET');
      expect(url.includes('/governance/rsi/generations')).assertTrue();
      expect(url.includes('limit=10')).assertTrue();
    });

    it('list_appends_status_filter_when_given', 0, () => {
      api.listGenerations(5, 'deployed');
      const url = backend.requests[0].url;
      expect(url.includes('limit=5')).assertTrue();
      expect(url.includes('status=deployed')).assertTrue();
    });

    it('list_omits_status_filter_when_empty', 0, () => {
      api.listGenerations(10, '');
      const url = backend.requests[0].url;
      expect(url.includes('status=')).assertFalse();
    });

    it('list_normalizes_envelope_payload', 0, async () => {
      const generations: EvolutionGenerationSummaryDto[] = [sampleSummary(3), sampleSummary(2)];
      const list: EvolutionGenerationList = { generations: generations, count: 2 };
      const payload: ApiResponse<EvolutionGenerationList> = { code: 0, message: 'ok', data: list };
      backend.responseBody = payload;
      const res = await api.listGenerations(10);
      expect(res.code).assertEqual(0);
      const decoded = res.data as EvolutionGenerationList;
      expect(decoded.count).assertEqual(2);
      expect(decoded.generations.length).assertEqual(2);
      expect(decoded.generations[0].generationNo).assertEqual(3);
      expect(decoded.generations[0].status).assertEqual('deployed');
    });

    it('currentBaseline_decodes_full_generation', 0, async () => {
      const payload: ApiResponse<EvolutionGenerationDto> = { code: 0, message: 'ok', data: sampleGeneration(3) };
      backend.responseBody = payload;
      const res = await api.currentBaseline();
      expect(res.code).assertEqual(0);
      const gen = res.data as EvolutionGenerationDto;
      expect(gen.generationNo).assertEqual(3);
      expect(gen.parentNo).assertEqual(2);
      expect(gen.status).assertEqual('rolledBack');
      // 门禁三态逐门保真（不折叠）
      expect(gen.verdicts['g0'].state).assertEqual('passed');
      expect(gen.verdicts['g2'].state).assertEqual('failed');
      expect(gen.verdicts['g2'].reason).assertEqual('决策档回退');
      expect(gen.decision!.kind).assertEqual('approval');
      expect(gen.decision!.approver).assertEqual('admin');
      expect(gen.deployment!.rolledBackTo).assertEqual(2);
    });

    it('currentBaseline_normalizes_detail_error_body', 0, async () => {
      // 后端 404：{detail:"尚无已部署的生产基线世代…"}——归一为 {code:1,message:detail}
      const err: DetailError = { detail: '尚无已部署的生产基线世代（账本空或没有 deployed 代）' };
      backend.responseBody = err;
      const res = await api.currentBaseline();
      expect(res.code).assertEqual(1);
      expect(res.message!.includes('尚无已部署的生产基线世代')).assertTrue();
    });

    it('generationDetail_normalizes_detail_error_body', 0, async () => {
      // 后端 503：世代管线未装配——同样按 {code:1,message:detail} 诚实透传
      const err: DetailError = { detail: 'agent kai 上世代管线未装配：该 agent 的 RSI 未挂接世代编排器' };
      backend.responseBody = err;
      const res = await api.generationDetail(3);
      expect(res.code).assertEqual(1);
      expect(res.message!.includes('未装配')).assertTrue();
    });

    it('lineage_unwraps_nested_lineage_key', 0, async () => {
      const chain: EvolutionGenerationDto[] = [sampleGeneration(3), sampleGeneration(2), sampleGeneration(1)];
      const lineage: EvolutionLineage = { lineage: chain };
      const payload: ApiResponse<EvolutionLineage> = { code: 0, message: 'ok', data: lineage };
      backend.responseBody = payload;
      const res = await api.generationLineage(3);
      expect(res.code).assertEqual(0);
      const decoded = res.data as EvolutionLineage;
      expect(decoded.lineage.length).assertEqual(3);
      expect(decoded.lineage[0].generationNo).assertEqual(3);
      expect(decoded.lineage[2].parentNo).assertEqual(null);
    });
  });
}
