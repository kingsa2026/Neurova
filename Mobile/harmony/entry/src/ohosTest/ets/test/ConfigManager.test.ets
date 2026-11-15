// ConfigManager 单元测试 - TDD
// 测试 ConfigManager 统一配置库的行为
import { describe, it, expect, beforeEach } from '@ohos/hypium';
import { ConfigManager } from '../../../../main/ets/libs/config/ConfigManager';

export default function configManagerTest() {
  describe('ConfigManager', () => {
    let cm: ConfigManager;

    beforeEach(() => {
      cm = ConfigManager.getInstance();
      cm.clear();
    });

    // ========== Tracer Bullet: 单例存在性 ==========

    it('getInstance_returns_singleton', 0, () => {
      const instance1 = ConfigManager.getInstance();
      const instance2 = ConfigManager.getInstance();
      expect(instance1).assertEqual(instance2);
    });

    // ========== 行为 1: get/set 基础读写 ==========

    it('set_then_get_returns_value', 0, () => {
      cm.set<string>('api_base_url', 'http://192.168.10.132:9527');
      const value = cm.get<string>('api_base_url', '');
      expect(value).assertEqual('http://192.168.10.132:9527');
    });

    it('get_returns_default_when_key_not_exists', 0, () => {
      const value = cm.get<string>('nonexistent_key', 'default_value');
      expect(value).assertEqual('default_value');
    });

    // ========== 行为 2: 类型支持 ==========

    it('supports_number_type', 0, () => {
      cm.set<number>('port', 9527);
      expect(cm.get<number>('port', 0)).assertEqual(9527);
    });

    it('supports_boolean_type', 0, () => {
      cm.set<boolean>('debug', true);
      expect(cm.get<boolean>('debug', false)).assertTrue();
    });

    it('supports_object_type', 0, () => {
      const config = { host: 'localhost', port: 9527 };
      cm.set<Object>('server', config);
      const result = cm.get<Object>('server', {});
      expect(result['host']).assertEqual('localhost');
      expect(result['port']).assertEqual(9527);
    });

    // ========== 行为 3: getAll 获取所有配置 ==========

    it('getAll_returns_all_configs', 0, () => {
      cm.set<string>('key1', 'value1');
      cm.set<number>('key2', 42);
      const all = cm.getAll();
      expect(all['key1']).assertEqual('value1');
      expect(all['key2']).assertEqual(42);
    });

    // ========== 行为 4: clear 清空配置 ==========

    it('clear_removes_all_configs', 0, () => {
      cm.set<string>('temp_key', 'temp_value');
      cm.clear();
      const all = cm.getAll();
      expect(Object.keys(all).length).assertEqual(0);
    });

    // ========== 行为 5: 覆盖已存在的值 ==========

    it('set_overwrites_existing_value', 0, () => {
      cm.set<string>('env', 'development');
      cm.set<string>('env', 'production');
      expect(cm.get<string>('env', '')).assertEqual('production');
    });

    // ========== 行为 6: 默认配置初始化 ==========

    it('init_defaults_sets_required_keys', 0, () => {
      cm.initDefaults();
      // 应包含 API 基础 URL
      const baseUrl = cm.get<string>('api_base_url', '');
      expect(baseUrl.length > 0).assertTrue();
      // 应包含 WS 基础 URL
      const wsUrl = cm.get<string>('ws_base_url', '');
      expect(wsUrl.length > 0).assertTrue();
      // 应包含默认超时
      const timeout = cm.get<number>('request_timeout', 0);
      expect(timeout > 0).assertTrue();
    });
  });
}
