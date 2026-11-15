// PersonalityApi 单元测试 - TDD 垂直切片
// 通过 HttpBackend 接口注入 mock，验证 PersonalityApi 调用契约（method/url/body/返回值）
// 不真实发起网络请求，符合"不直接调用后端接口"规则
import { describe, it, expect, beforeEach } from '@ohos/hypium';
import { HttpClient, HttpBackend } from '../../../../main/ets/libs/api/HttpClient';
import { ApiResponse, Emotion, Personality, PageResult, PageParams } from '../../../../main/ets/libs/types';
import { PersonalityApi } from '../../../../main/ets/libs/api/modules/PersonalityApi';

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

export default function personalityApiTest() {
  describe('PersonalityApi', () => {
    let client: HttpClient;
    let backend: MockBackend;
    let api: PersonalityApi;

    beforeEach(() => {
      backend = new MockBackend();
      client = HttpClient.getInstanceWithBackend(backend);
      client.setBaseUrl('https://api.example.com');
      api = new PersonalityApi(client);
    });

    // ========== Emotion 行为 1: listEmotions - GET /v1/personality/emotions ==========
    it('listEmotions_calls_get_emotions_url', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { items: [], total: 0, page: 1, size: 20 } };
      api.listEmotions('agent-1');
      expect(backend.requests[0].method).assertEqual('GET');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/personality/emotions?agentId=agent-1');
    });

    it('listEmotions_passes_page_params', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { items: [], total: 0, page: 1, size: 20 } };
      const params: PageParams = { page: 2, size: 10 };
      api.listEmotions('agent-1', params);
      const url = backend.requests[0].url;
      expect(url.includes('agentId=agent-1')).assertTrue();
      expect(url.includes('page=2')).assertTrue();
      expect(url.includes('size=10')).assertTrue();
    });

    it('listEmotions_returns_page_result', 0, () => {
      const page: PageResult<Emotion> = {
        items: [{ id: 'e1', agentId: 'a1', type: 'happy', intensity: 0.8, createdAt: '' }],
        total: 1, page: 1, size: 20,
      };
      backend.response = { code: 0, message: 'ok', data: page };
      let resolved: ApiResponse<PageResult<Emotion>> | null = null;
      api.listEmotions('a1').then(r => { resolved = r; });
      setTimeout(() => {
        expect(resolved!.code).assertEqual(0);
        expect(resolved!.data.total).assertEqual(1);
        expect(resolved!.data.items[0].id).assertEqual('e1');
      }, 10);
    });

    // ========== Emotion 行为 2: getEmotion - GET /v1/personality/emotions/{id} ==========
    it('getEmotion_calls_get_with_id_in_url', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { id: 'e1', agentId: 'a1', type: 'happy', intensity: 0.8, createdAt: '' } };
      api.getEmotion('e1');
      expect(backend.requests[0].method).assertEqual('GET');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/personality/emotions/e1');
    });

    // ========== Emotion 行为 3: createEmotion - POST /v1/personality/emotions ==========
    it('createEmotion_calls_post_with_body', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { id: 'e1', agentId: 'a1', type: 'happy', intensity: 0.8, createdAt: '' } };
      const data: Partial<Emotion> = { agentId: 'a1', type: 'happy', intensity: 0.8, trigger: 'greeting' };
      api.createEmotion(data);
      expect(backend.requests[0].method).assertEqual('POST');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/personality/emotions');
      expect(backend.requests[0].body).assertEqual(data);
    });

    // ========== Emotion 行为 4: removeEmotion - DELETE /v1/personality/emotions/{id} ==========
    it('removeEmotion_calls_delete_with_id', 0, () => {
      backend.response = { code: 0, message: 'ok', data: {} };
      api.removeEmotion('e1');
      expect(backend.requests[0].method).assertEqual('DELETE');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/personality/emotions/e1');
    });

    // ========== Emotion 行为 5: getCurrentEmotion - GET /v1/personality/emotions/current?agentId=xx ==========
    it('getCurrentEmotion_calls_get_current_with_agentId_query', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { id: 'e1', agentId: 'a1', type: 'happy', intensity: 0.8, createdAt: '' } };
      api.getCurrentEmotion('a1');
      expect(backend.requests[0].method).assertEqual('GET');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/personality/emotions/current?agentId=a1');
    });

    // ========== Personality 行为 6: getPersonality - GET /v1/personality?agentId=xx ==========
    it('getPersonality_calls_get_with_agentId_query', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { agentId: 'a1', openness: 0.5, conscientiousness: 0.6, extraversion: 0.7, agreeableness: 0.8, neuroticism: 0.4, updatedAt: '' } };
      api.getPersonality('a1');
      expect(backend.requests[0].method).assertEqual('GET');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/personality?agentId=a1');
    });

    // ========== Personality 行为 7: updatePersonality - PUT /v1/personality ==========
    it('updatePersonality_calls_put_with_agentId_in_body', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { agentId: 'a1', openness: 0.5, conscientiousness: 0.6, extraversion: 0.7, agreeableness: 0.8, neuroticism: 0.4, updatedAt: '' } };
      const data: Partial<Personality> = { openness: 0.9, neuroticism: 0.3 };
      api.updatePersonality('a1', data);
      expect(backend.requests[0].method).assertEqual('PUT');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/personality');
      // body 必须包含 agentId
      const body = backend.requests[0].body as Object;
      expect(body['agentId']).assertEqual('a1');
      expect(body['openness']).assertEqual(0.9);
    });

    // ========== Personality 行为 8: resetPersonality - POST /v1/personality/reset ==========
    it('resetPersonality_calls_post_with_agentId_body', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { agentId: 'a1', openness: 0, conscientiousness: 0, extraversion: 0, agreeableness: 0, neuroticism: 0, updatedAt: '' } };
      api.resetPersonality('a1');
      expect(backend.requests[0].method).assertEqual('POST');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/personality/reset');
      expect(backend.requests[0].body).assertEqual({ agentId: 'a1' });
    });
  });
}
