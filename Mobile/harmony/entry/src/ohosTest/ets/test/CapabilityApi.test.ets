// CapabilityApi 单元测试 - 真实契约版
// 通过 HttpBackend 接口注入 mock，验证 CapabilityApi 调用契约（method/url/body/返回值）
// 端点词汇与后端挂载同源：/v1/rules、/v1/files、/v1/media；
// 文件/媒体上传后端为 multipart——createFile/createMedia 显式失败不发请求。
import { describe, it, expect, beforeEach } from '@ohos/hypium';
import { HttpClient, HttpBackend } from '../../../../main/ets/libs/api/HttpClient';
import { ApiResponse } from '../../../../main/ets/libs/types';
import { CapabilityApi } from '../../../../main/ets/libs/api/modules/CapabilityApi';

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

export default function capabilityApiTest() {
  describe('CapabilityApi', () => {
    let client: HttpClient;
    let backend: MockBackend;
    let api: CapabilityApi;

    beforeEach(() => {
      backend = new MockBackend();
      client = HttpClient.getInstanceWithBackend(backend);
      client.setBaseUrl('https://api.example.com');
      api = new CapabilityApi(client);
    });

    // ========== Rules：列表/创建/更新/删除 ==========

    it('listRules_calls_get_rules_with_project_filter', 0, () => {
      backend.response = { code: 0, message: 'ok', data: [] };
      api.listRules('agent-1', { page: 1, size: 20 });
      expect(backend.requests[0].method).assertEqual('GET');
      const url = backend.requests[0].url;
      expect(url.includes('/rules')).assertTrue();
      expect(url.includes('project_id=agent-1')).assertTrue();
    });

    it('createRule_posts_rulecreate_contract', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { id: 'r1' } };
      api.createRule({ agentId: 'agent-1', name: '禁用外链', condition: 'url', action: 'block', priority: 1 });
      expect(backend.requests[0].method).assertEqual('POST');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/rules');
      const body = backend.requests[0].body as Record<string, Object>;
      expect(body['name']).assertEqual('禁用外链');
      expect(body['priority']).assertEqual('high');
      expect(body['project_id']).assertEqual('agent-1');
    });

    it('updateRule_puts_optional_fields', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { id: 'r1' } };
      api.updateRule('r1', { name: '新名字' });
      expect(backend.requests[0].method).assertEqual('PUT');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/rules/r1');
      const body = backend.requests[0].body as Record<string, Object>;
      expect(body['name']).assertEqual('新名字');
    });

    it('removeRule_calls_delete', 0, () => {
      backend.response = { code: 0, message: 'ok', data: {} };
      api.removeRule('r1');
      expect(backend.requests[0].method).assertEqual('DELETE');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/rules/r1');
    });

    // ========== Files：列表/更新/删除；create 显式失败 ==========

    it('listFiles_calls_get_files_without_capability_path', 0, () => {
      backend.response = { code: 0, message: 'ok', data: [] };
      api.listFiles('agent-1', { page: 1, size: 20 });
      expect(backend.requests[0].method).assertEqual('GET');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/files');
    });

    it('createFile_throws_without_request', 0, () => {
      let threw = false;
      try {
        api.createFile({ agentId: 'agent-1', name: 'a.txt' });
      } catch (e) {
        threw = true;
      }
      expect(threw).assertTrue();
      expect(backend.requests.length).assertEqual(0);
    });

    it('updateFile_puts_filename', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { file_id: 'f1' } };
      api.updateFile('f1', { name: 'b.txt' });
      expect(backend.requests[0].method).assertEqual('PUT');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/files/f1');
      const body = backend.requests[0].body as Record<string, Object>;
      expect(body['filename']).assertEqual('b.txt');
    });

    it('removeFile_calls_delete', 0, () => {
      backend.response = { code: 0, message: 'ok', data: {} };
      api.removeFile('f1');
      expect(backend.requests[0].method).assertEqual('DELETE');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/files/f1');
    });

    // ========== Media：列表/删除；create/update 显式失败 ==========

    it('listMedia_calls_get_media_list_with_agent', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { media: [], total: 0, offset: 0, limit: 100 } };
      api.listMedia('agent-1', { page: 1, size: 20 });
      expect(backend.requests[0].method).assertEqual('GET');
      const url = backend.requests[0].url;
      expect(url.includes('/media/list')).assertTrue();
      expect(url.includes('agent_id=agent-1')).assertTrue();
      expect(url.includes('limit=100')).assertTrue();
    });

    it('createMedia_throws_without_request', 0, () => {
      let threw = false;
      try {
        api.createMedia({ agentId: 'agent-1', name: 'pic.png' });
      } catch (e) {
        threw = true;
      }
      expect(threw).assertTrue();
      expect(backend.requests.length).assertEqual(0);
    });

    it('updateMedia_throws_without_request', 0, () => {
      let threw = false;
      try {
        api.updateMedia('m1', { name: 'x' });
      } catch (e) {
        threw = true;
      }
      expect(threw).assertTrue();
      expect(backend.requests.length).assertEqual(0);
    });

    it('removeMedia_calls_delete', 0, () => {
      backend.response = { code: 0, message: 'ok', data: {} };
      api.removeMedia('m1');
      expect(backend.requests[0].method).assertEqual('DELETE');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/media/m1');
    });
  });
}
