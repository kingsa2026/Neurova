// ModelsApi 单元测试 - TDD 垂直切片
// 验证 ModelsApi 9 个方法的调用契约
import { describe, it, expect, beforeEach } from '@ohos/hypium';
import { HttpClient, HttpBackend } from '../../../../main/ets/libs/api/HttpClient';
import {
  ApiResponse, Provider, ModelItem, DefaultLLMConfig, GenerationParams,
} from '../../../../main/ets/libs/types';
import { ModelsApi } from '../../../../main/ets/libs/api/modules/ModelsApi';

class MockBackend implements HttpBackend {
  public requests: { method: string; url: string; body: Object | null }[] = [];
  public response: ApiResponse<Object> = { code: 0, message: 'ok', data: {} };

  async request(
    method: string, url: string, body: Object | null,
    _headers: Record<string, string>,
  ): Promise<{ status: number; data: ApiResponse<Object> }> {
    this.requests.push({ method, url, body });
    return { status: 200, data: this.response };
  }
}

export default function modelsApiTest() {
  describe('ModelsApi', () => {
    let client: HttpClient;
    let backend: MockBackend;
    let api: ModelsApi;

    beforeEach(() => {
      backend = new MockBackend();
      client = HttpClient.getInstanceWithBackend(backend);
      client.setBaseUrl('https://api.example.com');
      api = new ModelsApi(client);
    });

    // ========== Providers ==========
    it('listProviders_gets_providers_endpoint', 0, () => {
      backend.response = { code: 0, message: 'ok', data: [] };
      api.listProviders();
      expect(backend.requests[0].method).assertEqual('GET');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/models/providers');
    });

    it('getProvider_gets_provider_by_id', 0, () => {
      api.getProvider('p1');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/models/providers/p1');
    });

    it('createProvider_posts_to_providers', 0, () => {
      const data: Partial<Provider> = { name: 'OpenAI' };
      api.createProvider(data);
      expect(backend.requests[0].method).assertEqual('POST');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/models/providers');
      expect(backend.requests[0].body).assertEqual(data);
    });

    it('updateProvider_puts_to_provider_id', 0, () => {
      const data: Partial<Provider> = { name: 'Updated' };
      api.updateProvider('p1', data);
      expect(backend.requests[0].method).assertEqual('PUT');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/models/providers/p1');
      expect(backend.requests[0].body).assertEqual(data);
    });

    it('removeProvider_deletes_provider', 0, () => {
      api.removeProvider('p1');
      expect(backend.requests[0].method).assertEqual('DELETE');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/models/providers/p1');
    });

    // ========== Models ==========
    it('listModels_gets_models_endpoint', 0, () => {
      backend.response = { code: 0, message: 'ok', data: [] };
      api.listModels();
      expect(backend.requests[0].method).assertEqual('GET');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/models');
    });

    it('listModels_passes_provider_id_query', 0, () => {
      api.listModels('p1');
      expect(backend.requests[0].url.includes('providerId=p1')).assertTrue();
    });

    it('listModels_returns_array', 0, () => {
      const items: ModelItem[] = [{
        id: 'm1', name: 'gpt-4', provider_id: 'p1', type: 'text',
        tags: [], enabled: true, capabilities: [], is_active: true,
      }];
      backend.response = { code: 0, message: 'ok', data: items };
      let resolved: ApiResponse<ModelItem[]> | null = null;
      api.listModels().then(r => { resolved = r; });
      setTimeout(() => {
        expect(resolved!.data[0].id).assertEqual('m1');
      }, 10);
    });

    // ========== Default + Params ==========
    it('setDefault_puts_default_config', 0, () => {
      const cfg: DefaultLLMConfig = { provider_id: 'p1', model_id: 'm1' };
      api.setDefault(cfg);
      expect(backend.requests[0].method).assertEqual('PUT');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/models/default');
      expect(backend.requests[0].body).assertEqual(cfg);
    });

    it('getGenerationParams_gets_params_endpoint', 0, () => {
      api.getGenerationParams();
      expect(backend.requests[0].method).assertEqual('GET');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/models/params');
    });

    it('updateGenerationParams_puts_params', 0, () => {
      const params: GenerationParams = { temperature: 0.7, max_tokens: 2048, stream_mode: true };
      api.updateGenerationParams(params);
      expect(backend.requests[0].method).assertEqual('PUT');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/models/params');
      expect(backend.requests[0].body).assertEqual(params);
    });
  });
}
