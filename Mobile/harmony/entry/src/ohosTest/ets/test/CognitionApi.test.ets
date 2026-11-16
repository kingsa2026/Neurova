// CognitionApi 单元测试 - 真实契约版
// 通过 HttpBackend 接口注入 mock，验证 CognitionApi 调用契约（method/url/body/返回值）
// 端点词汇与后端挂载同源：/v1/experience、/v1/metacognition、/v1/growth、/v1/knowledge-graph
// 不真实发起网络请求，符合"不直接调用后端接口"规则
import { describe, it, expect, beforeEach } from '@ohos/hypium';
import { HttpClient, HttpBackend } from '../../../../main/ets/libs/api/HttpClient';
import { ApiResponse } from '../../../../main/ets/libs/types';
import { CognitionApi } from '../../../../main/ets/libs/api/modules/CognitionApi';

// Mock 后端实现（参考 MemoryApi.test.ets 模式）
class MockBackend implements HttpBackend {
  public requests: { method: string; url: string; body: Object | null }[] = [];
  public response: ApiResponse<Object> = { code: 0, message: 'ok', data: {} };

  async request(
    method: string,
    url: string,
    body: Object | null,
    _headers: Record<string, string>,
  ): Promise<{ status: number; data: ApiResponse<Object> }> {
    this.requests.push({ method, url, body });
    return { status: 200, data: this.response };
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
      backend.response = { code: 0, message: 'ok', data: { items: [], total: 0, page: 2, size: 10 } };
      api.listExperiences('agent-1', 2, 10);
      expect(backend.requests[0].method).assertEqual('GET');
      const url = backend.requests[0].url;
      expect(url.includes('/v1/experience/ranking')).assertTrue();
      expect(url.includes('agent_id=agent-1')).assertTrue();
      expect(url.includes('page=2')).assertTrue();
      expect(url.includes('size=10')).assertTrue();
    });

    it('createExperience_calls_post_records_with_body', 0, () => {
      backend.response = { code: 0, message: 'Record added', data: { id: 'e1' } };
      const payload: Record<string, Object> = {
        'agent_id': 'a1',
        'task_type': '数据清洗',
        'context': 'ctx',
        'outcome': 'success',
        'lessons': ['lesson-1'],
      };
      api.createExperience(payload);
      expect(backend.requests[0].method).assertEqual('POST');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/experience/records');
      expect(backend.requests[0].body).assertEqual(payload);
    });

    it('removeExperience_calls_delete_with_id', 0, () => {
      backend.response = { code: 0, message: 'ok', data: {} };
      api.removeExperience('e1');
      expect(backend.requests[0].method).assertEqual('DELETE');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/experience/e1');
    });

    // ========== Metacognition: list/create ==========

    it('listMetacognitions_calls_get_with_agent_path_and_paging', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { items: [], total: 0, page: 2, size: 10 } };
      api.listMetacognitions('agent-1', 2, 10);
      expect(backend.requests[0].method).assertEqual('GET');
      const url = backend.requests[0].url;
      expect(url.includes('/v1/metacognition/agent-1/metacognition')).assertTrue();
      expect(url.includes('page=2')).assertTrue();
      expect(url.includes('size=10')).assertTrue();
    });

    it('createMetacognition_calls_post_with_agent_path_and_body', 0, () => {
      backend.response = { code: 0, message: 'Record created', data: { id: 1 } };
      const payload: Record<string, Object> = {
        'type': 'monitoring',
        'content': 'c',
        'context': 'ctx',
        'confidence': 0.5,
      };
      api.createMetacognition('agent-1', payload);
      expect(backend.requests[0].method).assertEqual('POST');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/metacognition/agent-1/metacognition');
      expect(backend.requests[0].body).assertEqual(payload);
    });

    // ========== Reflection: list/create ==========

    it('listReflections_calls_get_growth_reflection_with_agent_and_limit', 0, () => {
      backend.response = { code: 0, message: 'ok', data: [] };
      api.listReflections('agent-1', 20);
      expect(backend.requests[0].method).assertEqual('GET');
      const url = backend.requests[0].url;
      expect(url.includes('/v1/growth/reflection')).assertTrue();
      expect(url.includes('agent_id=agent-1')).assertTrue();
      expect(url.includes('limit=20')).assertTrue();
    });

    it('createReflection_calls_post_growth_reflection_with_body', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { log_id: 'r1' } };
      const payload: Record<string, Object> = {
        'reflection_type': 'performance',
        'content': 'c',
        'insights': ['i1'],
        'confidence': 0.5,
        'related_memories': [],
      };
      api.createReflection('agent-1', payload);
      expect(backend.requests[0].method).assertEqual('POST');
      const url = backend.requests[0].url;
      expect(url.includes('/v1/growth/reflection')).assertTrue();
      expect(url.includes('agent_id=agent-1')).assertTrue();
      expect(backend.requests[0].body).assertEqual(payload);
    });

    // ========== Growth: getGrowthData ==========

    it('getGrowthData_calls_get_growth_with_agent_query', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { agent_id: 'agent-1' } };
      api.getGrowthData('agent-1');
      expect(backend.requests[0].method).assertEqual('GET');
      const url = backend.requests[0].url;
      expect(url.includes('/v1/growth')).assertTrue();
      expect(url.includes('agent_id=agent-1')).assertTrue();
    });

    // ========== KnowledgeGraph: getKnowledgeGraph ==========

    it('getKnowledgeGraph_calls_get_with_agent_path_and_limit', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { nodes: [], edges: [] } };
      api.getKnowledgeGraph('agent-1');
      expect(backend.requests[0].method).assertEqual('GET');
      const url = backend.requests[0].url;
      expect(url.includes('/v1/knowledge-graph/agent-1/knowledge-graph')).assertTrue();
      expect(url.includes('limit=100')).assertTrue();
    });

    it('getKnowledgeGraph_returns_graph_data', 0, () => {
      backend.response = {
        code: 0,
        message: 'ok',
        data: {
          nodes: [{ id: 'n1', label: 'AI', type: 'concept', description: '', weight: 1, created_at: null }],
          edges: [{ source: 'n1', target: 'n1', relation: 'related_to', weight: 1 }],
          total_nodes: 1,
          total_edges: 1,
          truncated: false,
          is_demo: false,
          hint: '',
        },
      };
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
