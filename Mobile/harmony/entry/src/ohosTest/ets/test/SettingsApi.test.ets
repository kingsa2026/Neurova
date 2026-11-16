// SettingsApi 单元测试 - 真实契约版（P1-30/P1-31 端点核对 + 信封归一）
// 后端事实源：settings.py @ /v1/settings（baseUrl 已含 /api/v1，路径不重复写 /v1）：
//   GET /settings → SettingsResponse{settings: Dict, updated_at}（裸对象，边界归一）；
//   GET/PUT /settings/{key} → {key,value} 载荷；
//   后端无 /settings/reset：reset 诚实 throw 且不发任何请求。
import { describe, it, expect, beforeEach } from '@ohos/hypium';
import { HttpClient, HttpBackend, HttpBackendResponse } from '../../../main/ets/libs/api/HttpClient';
import { ApiResponse } from '../../../main/ets/libs/types';
import { SettingsApi } from '../../../main/ets/libs/api/modules/SettingsApi';

/** MockBackend 录制的请求（显式接口，替代内联对象字面量类型） */
interface RecordedRequest {
  method: string;
  url: string;
  body: Object | null;
}

class MockBackend implements HttpBackend {
  public requests: RecordedRequest[] = [];
  /** 响应体（可为信封/裸数组/裸 dict——模拟后端真实形状） */
  public responseBody: Object = new Object();

  async request(
    method: string, url: string, body: Object | null,
    _headers: Record<string, string>,
  ): Promise<HttpBackendResponse> {
    const recorded: RecordedRequest = { method: method, url: url, body: body };
    this.requests.push(recorded);
    const resp: HttpBackendResponse = { status: 200, data: this.responseBody as Object as ApiResponse<Object> };
    return resp;
  }
}

/** SettingsResponse 裸 dict（settings.py 形状） */
function settingsDict(settings: Record<string, Object>): Record<string, Object> {
  const dict: Record<string, Object> = { 'settings': settings, 'updated_at': '' };
  return dict;
}

/** 单键载荷裸 dict（{key,value}） */
function keyValueDict(key: string, value: Object): Record<string, Object> {
  const dict: Record<string, Object> = { 'key': key, 'value': value };
  return dict;
}

export default function settingsApiTest() {
  describe('SettingsApi', () => {
    let client: HttpClient;
    let backend: MockBackend;
    let api: SettingsApi;

    beforeEach(() => {
      backend = new MockBackend();
      client = HttpClient.getInstanceWithBackend(backend);
      client.setBaseUrl('https://api.example.com');
      api = new SettingsApi(client);
    });

    // ========== list ==========
    it('list_gets_settings_endpoint', 0, () => {
      const empty: Record<string, Object> = {};
      backend.responseBody = settingsDict(empty);
      api.list();
      expect(backend.requests[0].method).assertEqual('GET');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/settings');
    });

    it('list_returns_setting_groups', 0, async () => {
      // 后端 {settings: Dict} 裸对象——平铺键归入 general 组
      const settings: Record<string, Object> = { 'theme': 'dark' };
      backend.responseBody = settingsDict(settings);
      const res = await api.list();
      expect(res.code).assertEqual(0);
      expect(res.data.length).assertEqual(1);
      expect(res.data[0].key).assertEqual('general');
      expect(res.data[0].items[0].key).assertEqual('theme');
    });

    // ========== get ==========
    it('get_gets_setting_by_key', 0, () => {
      backend.responseBody = keyValueDict('theme', 'dark');
      api.get('theme');
      expect(backend.requests[0].method).assertEqual('GET');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/settings/theme');
    });

    // ========== update ==========
    it('update_puts_value_to_key_url', 0, () => {
      backend.responseBody = keyValueDict('theme', 'dark');
      api.update('theme', 'dark');
      expect(backend.requests[0].method).assertEqual('PUT');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/settings/theme');
      expect(backend.requests[0].body).assertEqual({ value: 'dark' });
    });

    // ========== reset（后端无此端点：诚实 throw，不发任何请求）==========
    it('reset_throws_and_fires_no_request', 0, async () => {
      let thrown = '';
      try {
        await api.reset();
      } catch (e) {
        thrown = (e as Error).message;
      }
      expect(thrown.includes('/v1/settings/reset')).assertTrue();
      expect(backend.requests.length).assertEqual(0);
    });

    it('reset_with_group_throws_and_fires_no_request', 0, async () => {
      let thrown = '';
      try {
        await api.reset('appearance');
      } catch (e) {
        thrown = (e as Error).message;
      }
      expect(thrown.length > 0).assertTrue();
      expect(backend.requests.length).assertEqual(0);
    });
  });
}
