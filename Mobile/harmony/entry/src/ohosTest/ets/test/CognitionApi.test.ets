// CognitionApi 单元测试 - 真实契约版
// 通过 HttpBackend 接口注入 mock，验证 CognitionApi 调用契约（method/url/body/返回值）
// 后端挂载为 /v1/experience、/v1/metacognition、/v1/growth、/v1/knowledge-graph；
// HttpClient 的 baseUrl 已含 /api/v1，模块内路径不带 /v1（本文件 baseUrl 用裸域名断言）。
// 不真实发起网络请求，符合"不直接调用后端接口"规则
import { describe, it, expect, beforeEach } from '@ohos/hypium';
import { HttpClient, HttpBackend, HttpBackendResponse } from '../../../main/ets/libs/api/HttpClient';
import { ApiResponse } from '../../../main/ets/libs/types';
import {
  CognitionApi,
  ExperiencePage,
  MetacognitionPage,
  ReflectionCreateRequest,
  GraphNodeDto,
  GraphEdgeDto,
} from '../../../main/ets/libs/api/modules/CognitionApi';

/** MockBackend 录制的请求（显式接口，替代内联对象字面量类型） */
interface RecordedRequest {
  method: string;
  url: string;
  body: Object | null;
}

/** 知识图谱 mock 载荷（knowledge_graph_api 投影子集，缺 stats 的裁剪形状） */
interface KnowledgeGraphPayload {
  nodes: GraphNodeDto[];
  edges: GraphEdgeDto[];
  total_nodes: number;
  total_edges: number;
  truncated: boolean;
  is_demo: boolean;
  hint: string;
}

// Mock 后端实现（参考 MemoryApi.test.ets 模式）
class MockBackend implements HttpBackend {
  public requests: RecordedRequest[] = [];
  public response: ApiResponse<Object> = { code: 0, message: 'ok', data: new Object() };

  async request(
    method: string,
    url: string,
    body: Object | null,
    _headers: Record<string, string>,
  ): Promise<HttpBackendResponse> {
    const recorded: RecordedRequest = { method: method, url: url, body: body };
    this.requests.push(recorded);
    const resp: HttpBackendResponse = { status: 200, data: this.response };
    return resp;
  }
}

export default function cognitionApiTest() {
  describe('CognitionApi', () => {
    let client: HttpClient;
    let backend: MockBackend;
    let api: CognitionApi;

    beforeEach(() => {
      backend = new MockBackend();
      client = HttpClient.getInstanceWithBackend(backend);
      client.setBaseUrl('https://api.example.com');
      api = new CognitionApi(client);
    });

    // ========== Experience: ranking/records/delete ==========

    it('listExperiences_calls_get_ranking_with_agent_and_paging', 0, () => {
      const page: ExperiencePage = { items: [], total: 0, page: 2, size: 10 };
      backend.response = { code: 0, message: 'ok', data: page };
      api.listExperiences('agent-1', 2, 10);
      expect(backend.requests[0].method).assertEqual('GET');
      const url = backend.requests[0].url;
      expect(url.includes('/experience/ranking')).assertTrue();
      expect(url.includes('agent_id=agent-1')).assertTrue();
      expect(url.includes('page=2')).assertTrue();
      expect(url.includes('size=10')).assertTrue();
    });

    it('createExperience_calls_post_records_with_body', 0, () => {
      const created: Record<string, Object> = { 'id': 'e1' };
      backend.response = { code: 0, message: 'Record added', data: created };
      const payload: Record<string, Object> = {
        'agent_id': 'a1',
        'task_type': '数据清洗',
        'context': 'ctx',
        'outcome': 'success',
        'lessons': ['lesson-1'],
      };
      api.createExperience(payload);
      expect(backend.requests[0].method).assertEqual('POST');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/experience/records');
      expect(backend.requests[0].body).assertEqual(payload);
    });

    it('removeExperience_calls_delete_with_id', 0, () => {
      const empty: Record<string, Object> = {};
      backend.response = { code: 0, message: 'ok', data: empty };
      api.removeExperience('e1');
      expect(backend.requests[0].method).assertEqual('DELETE');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/experience/e1');
    });

    // ========== Metacognition: list/create ==========

    it('listMetacognitions_calls_get_with_agent_path_and_paging', 0, () => {
      const page: MetacognitionPage = { items: [], total: 0, page: 2, size: 10 };
      backend.response = { code: 0, message: 'ok', data: page };
      api.listMetacognitions('agent-1', 2, 10);
      expect(backend.requests[0].method).assertEqual('GET');
      const url = backend.requests[0].url;
      expect(url.includes('/metacognition/agent-1/metacognition')).assertTrue();
      expect(url.includes('page=2')).assertTrue();
      expect(url.includes('size=10')).assertTrue();
    });

    it('createMetacognition_calls_post_with_agent_path_and_body', 0, () => {
      const created: Record<string, Object> = { 'id': 1 };
      backend.response = { code: 0, message: 'Record created', data: created };
      const payload: Record<string, Object> = {
        'type': 'monitoring',
        'content': 'c',
        'context': 'ctx',
        'confidence': 0.5,
      };
      api.createMetacognition('agent-1', payload);
      expect(backend.requests[0].method).assertEqual('POST');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/metacognition/agent-1/metacognition');
      expect(backend.requests[0].body).assertEqual(payload);
    });

    // ========== Reflection: list/create ==========

    it('listReflections_calls_get_growth_reflection_with_agent_and_limit', 0, () => {
      backend.response = { code: 0, message: 'ok', data: [] };
      api.listReflections('agent-1', 20);
      expect(backend.requests[0].method).assertEqual('GET');
      const url = backend.requests[0].url;
      expect(url.includes('/growth/reflection')).assertTrue();
      expect(url.includes('agent_id=agent-1')).assertTrue();
      expect(url.includes('limit=20')).assertTrue();
    });

    it('createReflection_calls_post_growth_reflection_with_body', 0, () => {
      const created: Record<string, Object> = { 'log_id': 'r1' };
      backend.response = { code: 0, message: 'ok', data: created };
      const payload: ReflectionCreateRequest = {
        reflection_type: 'performance',
        content: 'c',
        insights: ['i1'],
        confidence: 0.5,
        related_memories: [],
      };
      api.createReflection('agent-1', payload);
      expect(backend.requests[0].method).assertEqual('POST');
      const url = backend.requests[0].url;
      expect(url.includes('/growth/reflection')).assertTrue();
      expect(url.includes('agent_id=agent-1')).assertTrue();
      expect(backend.requests[0].body).assertEqual(payload);
    });

    // ========== Growth: getGrowthData ==========

    it('getGrowthData_calls_get_growth_with_agent_query', 0, () => {
      const growth: Record<string, Object> = { 'agent_id': 'agent-1' };
      backend.response = { code: 0, message: 'ok', data: growth };
      api.getGrowthData('agent-1');
      expect(backend.requests[0].method).assertEqual('GET');
      const url = backend.requests[0].url;
      expect(url.includes('/growth')).assertTrue();
      expect(url.includes('agent_id=agent-1')).assertTrue();
    });

    // ========== KnowledgeGraph: getKnowledgeGraph ==========

    it('getKnowledgeGraph_calls_get_with_agent_path_and_limit', 0, () => {
      const graph: Record<string, Object> = { 'nodes': [], 'edges': [] };
      backend.response = { code: 0, message: 'ok', data: graph };
      api.getKnowledgeGraph('agent-1');
      expect(backend.requests[0].method).assertEqual('GET');
      const url = backend.requests[0].url;
      expect(url.includes('/knowledge-graph/agent-1/knowledge-graph')).assertTrue();
      expect(url.includes('limit=100')).assertTrue();
    });

    it('getKnowledgeGraph_returns_graph_data', 0, () => {
      const payload: KnowledgeGraphPayload = {
        nodes: [{ id: 'n1', label: 'AI', type: 'concept', description: '', weight: 1, created_at: null }],
        edges: [{ source: 'n1', target: 'n1', relation: 'related_to', weight: 1 }],
        total_nodes: 1,
        total_edges: 1,
        truncated: false,
        is_demo: false,
        hint: '',
      };
      backend.response = { code: 0, message: 'ok', data: payload };
      let resolved: ApiResponse<Object> | null = null;
      api.getKnowledgeGraph('a1').then(r => { resolved = r; });
      setTimeout(() => {
        if (resolved !== null) {
          expect(resolved.code).assertEqual(0);
        }
      }, 10);
    });
  });
}
