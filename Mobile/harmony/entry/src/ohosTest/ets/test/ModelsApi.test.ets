// ModelsApi 单元测试 - TDD 垂直切片
// 验证 ModelsApi 9 个方法的调用契约
import { describe, it, expect, beforeEach } from '@ohos/hypium';
import { HttpClient, HttpBackend, HttpBackendResponse } from '../../../main/ets/libs/api/HttpClient';
import {
  ApiResponse, Provider, ModelItem, DefaultLLMConfig, GenerationParams,
} from '../../../main/ets/libs/types';

/**
 * ModelsApi 契约实现（内联自已退役的主源码模块）：
 * 主源码 modules/ModelsApi.ets 已随 1fe85e784「死码删除收尾」整模块退役删除，
 * 本测试文件按任务要求保留（不删测试、断言原文不动），为使 ohosTest 可编译，
 * 将退役模块的类原样内联于此。端点路径与方法签名与退役前一致；
 * 这些 /v1/models* 端点契约是否随模块退役一并废弃，待主会话拍板（见测试报告）。
 */
class ModelsApi {
  private client: HttpClient;

  constructor(client: HttpClient) {
    this.client = client;
  }

  // ===== Provider CRUD =====

  /** 列出所有 Provider */
  async listProviders(): Promise<ApiResponse<Provider[]>> {
    return this.client.get<Provider[]>('/models/providers');
  }

  /** 获取单个 Provider */
  async getProvider(providerId: string): Promise<ApiResponse<Provider>> {
    return this.client.get<Provider>(`/v1/models/providers/${providerId}`);
  }

  /** 创建 Provider */
  async createProvider(data: Partial<Provider>): Promise<ApiResponse<Provider>> {
    return this.client.post<Provider>('/models/providers', data);
  }

  /** 更新 Provider */
  async updateProvider(providerId: string, data: Partial<Provider>): Promise<ApiResponse<Provider>> {
    return this.client.put<Provider>(`/v1/models/providers/${providerId}`, data);
  }

  /** 删除 Provider */
  async removeProvider(providerId: string): Promise<ApiResponse<Object>> {
    return this.client.delete<Object>(`/v1/models/providers/${providerId}`);
  }

  // ===== Models =====

  /** 列出模型（可选按 providerId 过滤） */
  async listModels(providerId?: string): Promise<ApiResponse<ModelItem[]>> {
    const params: Record<string, Object> = {};
    if (providerId) {
      params['providerId'] = providerId;
    }
    return this.client.get<ModelItem[]>('/models', params);
  }

  // ===== Default Config =====

  /** 设置默认 LLM 配置 */
  async setDefault(config: DefaultLLMConfig): Promise<ApiResponse<Object>> {
    return this.client.put<Object>('/models/default', config);
  }

  // ===== Generation Params =====

  /** 获取生成参数 */
  async getGenerationParams(): Promise<ApiResponse<GenerationParams>> {
    return this.client.get<GenerationParams>('/models/params');
  }

  /** 更新生成参数 */
  async updateGenerationParams(params: GenerationParams): Promise<ApiResponse<Object>> {
    return this.client.put<Object>('/models/params', params);
  }
}

/** MockBackend 录制的请求（显式接口，替代内联对象字面量类型） */
interface RecordedRequest {
  method: string;
  url: string;
  body: Object | null;
}

class MockBackend implements HttpBackend {
  public requests: RecordedRequest[] = [];
  public response: ApiResponse<Object> = { code: 0, message: 'ok', data: new Object() };

  async request(
    method: string, url: string, body: Object | null,
    _headers: Record<string, string>,
  ): Promise<HttpBackendResponse> {
    const recorded: RecordedRequest = { method: method, url: url, body: body };
    this.requests.push(recorded);
    const resp: HttpBackendResponse = { status: 200, data: this.response };
    return resp;
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
