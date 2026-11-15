// SettingsApi 单元测试 - TDD 垂直切片
// 验证 SettingsApi 4 个方法的调用契约
import { describe, it, expect, beforeEach } from '@ohos/hypium';
import { HttpClient, HttpBackend } from '../../../../main/ets/libs/api/HttpClient';
import { ApiResponse, SettingItem, SettingGroup, SettingType } from '../../../../main/ets/libs/types';
import { SettingsApi } from '../../../../main/ets/libs/api/modules/SettingsApi';

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
      backend.response = { code: 0, message: 'ok', data: [] };
      api.list();
      expect(backend.requests[0].method).assertEqual('GET');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/settings');
    });

    it('list_returns_setting_groups', 0, () => {
      const groups: SettingGroup[] = [{
        key: 'general', title: '通用', items: [],
      }];
      backend.response = { code: 0, message: 'ok', data: groups };
      let resolved: ApiResponse<SettingGroup[]> | null = null;
      api.list().then(r => { resolved = r; });
      setTimeout(() => {
        expect(resolved!.data[0].key).assertEqual('general');
      }, 10);
    });

    // ========== get ==========
    it('get_gets_setting_by_key', 0, () => {
      const item: SettingItem = {
        key: 'theme', label: '主题', type: 'select' as SettingType,
        value: 'dark', defaultValue: 'light', group: 'appearance',
      };
      backend.response = { code: 0, message: 'ok', data: item };
      api.get('theme');
      expect(backend.requests[0].method).assertEqual('GET');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/settings/theme');
    });

    // ========== update ==========
    it('update_puts_value_to_key_url', 0, () => {
      const item: SettingItem = {
        key: 'theme', label: '主题', type: 'select' as SettingType,
        value: 'dark', defaultValue: 'light', group: 'appearance',
      };
      backend.response = { code: 0, message: 'ok', data: item };
      api.update('theme', 'dark');
      expect(backend.requests[0].method).assertEqual('PUT');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/settings/theme');
      expect(backend.requests[0].body).assertEqual({ value: 'dark' });
    });

    // ========== reset ==========
    it('reset_posts_to_reset_endpoint_no_group', 0, () => {
      backend.response = { code: 0, message: 'ok', data: {} };
      api.reset();
      expect(backend.requests[0].method).assertEqual('POST');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/settings/reset');
      expect(backend.requests[0].body).assertEqual({});
    });

    it('reset_with_group_includes_group_in_body', 0, () => {
      backend.response = { code: 0, message: 'ok', data: {} };
      api.reset('appearance');
      expect(backend.requests[0].body).assertEqual({ group: 'appearance' });
    });
  });
}
