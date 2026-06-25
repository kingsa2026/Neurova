// CognitionApi 单元测试 - TDD 垂直切片
// 通过 HttpBackend 接口注入 mock，验证 CognitionApi 调用契约（method/url/body/返回值）
// 不真实发起网络请求，符合"不直接调用后端接口"规则
import { describe, it, expect, beforeEach } from '@ohos/hypium';
import { HttpClient, HttpBackend } from '../../../../main/ets/libs/api/HttpClient';
import {
  ApiResponse,
  PageResult,
  Experience,
  KnowledgeGraph,
  MetacognitionRecord,
  ReflectionRecord,
  GrowthRecord,
} from '../../../../main/ets/libs/types';
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

    // ========== Experience: list/get/create/update/remove ==========
    it('listExperiences_calls_get_with_agentId_and_paging', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { items: [], total: 0, page: 1, size: 20 } };
      api.listExperiences('agent-1', { page: 2, size: 10 });
      expect(backend.requests[0].method).assertEqual('GET');
      const url = backend.requests[0].url;
      expect(url.includes('/v1/cognition/experiences')).assertTrue();
      expect(url.includes('agentId=agent-1')).assertTrue();
      expect(url.includes('page=2')).assertTrue();
      expect(url.includes('size=10')).assertTrue();
    });

    it('getExperience_calls_get_with_id_in_url', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { id: 'e1', agentId: 'a1', title: 't', content: 'c', category: 'work', importance: 0.5, createdAt: '', updatedAt: '', activationCount: 0 } };
      api.getExperience('e1');
      expect(backend.requests[0].method).assertEqual('GET');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/cognition/experiences/e1');
    });

    it('createExperience_calls_post_with_body', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { id: 'e1', agentId: 'a1', title: 't', content: 'c', category: 'work', importance: 0.5, createdAt: '', updatedAt: '', activationCount: 0 } };
      const data: Partial<Experience> = { agentId: 'a1', title: 't', content: 'c', category: 'work', importance: 0.5 };
      api.createExperience(data);
      expect(backend.requests[0].method).assertEqual('POST');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/cognition/experiences');
      expect(backend.requests[0].body).assertEqual(data);
    });

    it('updateExperience_calls_put_with_id_and_body', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { id: 'e1', agentId: 'a1', title: 't2', content: 'c', category: 'work', importance: 0.5, createdAt: '', updatedAt: '', activationCount: 0 } };
      const data: Partial<Experience> = { title: 't2' };
      api.updateExperience('e1', data);
      expect(backend.requests[0].method).assertEqual('PUT');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/cognition/experiences/e1');
      expect(backend.requests[0].body).assertEqual(data);
    });

    it('removeExperience_calls_delete_with_id', 0, () => {
      backend.response = { code: 0, message: 'ok', data: {} };
      api.removeExperience('e1');
      expect(backend.requests[0].method).assertEqual('DELETE');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/cognition/experiences/e1');
    });

    // ========== KnowledgeGraph: getKnowledgeGraph ==========
    it('getKnowledgeGraph_calls_get_with_agentId_query', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { nodes: [], edges: [] } };
      api.getKnowledgeGraph('agent-1');
      expect(backend.requests[0].method).assertEqual('GET');
      const url = backend.requests[0].url;
      expect(url.includes('/v1/cognition/knowledge-graph')).assertTrue();
      expect(url.includes('agentId=agent-1')).assertTrue();
    });

    it('getKnowledgeGraph_returns_graph_data', 0, () => {
      const graph: KnowledgeGraph = {
        nodes: [{ id: 'n1', agentId: 'a1', label: 'AI', type: 'concept' }],
        edges: [{ id: 'ed1', source: 'n1', target: 'n1', relation: 'self' }],
      };
      backend.response = { code: 0, message: 'ok', data: graph };
      let resolved: ApiResponse<KnowledgeGraph> | null = null;
      api.getKnowledgeGraph('a1').then(r => { resolved = r; });
      setTimeout(() => {
        expect(resolved!.code).assertEqual(0);
        expect(resolved!.data.nodes.length).assertEqual(1);
        expect(resolved!.data.edges.length).assertEqual(1);
      }, 10);
    });

    // ========== Metacognition: list/create ==========
    it('listMetacognitions_calls_get_with_agentId', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { items: [], total: 0, page: 1, size: 20 } };
      api.listMetacognitions('agent-1');
      expect(backend.requests[0].method).assertEqual('GET');
      expect(backend.requests[0].url.includes('/v1/cognition/metacognitions')).assertTrue();
      expect(backend.requests[0].url.includes('agentId=agent-1')).assertTrue();
    });

    it('createMetacognition_calls_post_with_body', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { id: 'm1', agentId: 'a1', thoughtId: 't1', type: 'monitoring', content: 'c', confidence: 0.8, createdAt: '' } };
      const data: Partial<MetacognitionRecord> = { agentId: 'a1', thoughtId: 't1', type: 'monitoring', content: 'c', confidence: 0.8 };
      api.createMetacognition(data);
      expect(backend.requests[0].method).assertEqual('POST');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/cognition/metacognitions');
      expect(backend.requests[0].body).assertEqual(data);
    });

    // ========== Reflection: list/create ==========
    it('listReflections_calls_get_with_agentId', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { items: [], total: 0, page: 1, size: 20 } };
      api.listReflections('agent-1');
      expect(backend.requests[0].method).assertEqual('GET');
      expect(backend.requests[0].url.includes('/v1/cognition/reflections')).assertTrue();
      expect(backend.requests[0].url.includes('agentId=agent-1')).assertTrue();
    });

    it('createReflection_calls_post_with_body', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { id: 'r1', agentId: 'a1', trigger: 'failure', content: 'c', insights: [], improvements: [], createdAt: '' } };
      const data: Partial<ReflectionRecord> = { agentId: 'a1', trigger: 'failure', content: 'c', insights: [], improvements: [] };
      api.createReflection(data);
      expect(backend.requests[0].method).assertEqual('POST');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/cognition/reflections');
      expect(backend.requests[0].body).assertEqual(data);
    });

    // ========== Growth: list/update ==========
    it('listGrowths_calls_get_with_agentId', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { items: [], total: 0, page: 1, size: 20 } };
      api.listGrowths('agent-1');
      expect(backend.requests[0].method).assertEqual('GET');
      expect(backend.requests[0].url.includes('/v1/cognition/growths')).assertTrue();
      expect(backend.requests[0].url.includes('agentId=agent-1')).assertTrue();
    });

    it('updateGrowth_calls_put_with_id_and_body', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { id: 'g1', agentId: 'a1', dimension: 'knowledge', level: 2, experience: 100, milestones: [], updatedAt: '' } };
      const data: Partial<GrowthRecord> = { level: 2 };
      api.updateGrowth('g1', data);
      expect(backend.requests[0].method).assertEqual('PUT');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/cognition/growths/g1');
      expect(backend.requests[0].body).assertEqual(data);
    });

    it('listExperiences_returns_page_result', 0, () => {
      const page: PageResult<Experience> = {
        items: [{ id: 'e1', agentId: 'a1', title: 't', content: 'c', category: 'work', importance: 0.5, createdAt: '', updatedAt: '', activationCount: 0 }],
        total: 1, page: 1, size: 20,
      };
      backend.response = { code: 0, message: 'ok', data: page };
      let resolved: ApiResponse<PageResult<Experience>> | null = null;
      api.listExperiences('a1').then(r => { resolved = r; });
      setTimeout(() => {
        expect(resolved!.code).assertEqual(0);
        expect(resolved!.data.total).assertEqual(1);
        expect(resolved!.data.items[0].id).assertEqual('e1');
      }, 10);
    });
  });
}
