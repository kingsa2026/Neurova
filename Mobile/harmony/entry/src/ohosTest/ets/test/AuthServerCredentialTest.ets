// P0-07：鸿蒙认证按 serverId 分仓；HTTP bearer 只允许发往精确匹配的规范化 origin。
import { describe, it, expect, beforeEach } from '@ohos/hypium';
import { AuthStore } from '../../../main/ets/libs/state/stores/AuthStore';
import { StorageAdapter } from '../../../main/ets/libs/adapters/StorageAdapter';
import { HttpClient, HttpBackend, HttpBackendResponse } from '../../../main/ets/libs/api/HttpClient';
import { AuthTokens, ApiResponse } from '../../../main/ets/libs/types';
import { TestContext } from '../testability/TestContext';

class CredentialBackend implements HttpBackend {
  public lastHeaders: Record<string, string> = {};
  public lastUrl: string = '';
  public requestCount: number = 0;

  async request(method: string, url: string, body: Object | null, headers: Record<string, string>): Promise<HttpBackendResponse> {
    this.lastHeaders = headers;
    this.lastUrl = url;
    this.requestCount++;
    const response: ApiResponse<Object> = { code: 0, message: 'ok', data: {} };
    return { status: 200, data: response };
  }
}

function tokens(access: string, refresh: string): AuthTokens {
  return { access_token: access, refresh_token: refresh, token_type: 'Bearer', expires_in: 3600 };
}

async function initStorage(): Promise<StorageAdapter> {
  const storage = StorageAdapter.getInstance();
  let waited = 0;
  while (TestContext.tryGet() === null && waited < 8000) {
    await new Promise<void>((resolve) => { setTimeout(resolve, 100); });
    waited += 100;
  }
  await storage.init(TestContext.get());
  return storage;
}

export default function authServerCredentialTest() {
  describe('AuthStore server credential isolation', () => {
    let store: AuthStore;
    let client: HttpClient;
    let backend: CredentialBackend;

    beforeEach(async () => {
      await initStorage();
      backend = new CredentialBackend();
      client = HttpClient.getInstanceWithBackend(backend);
      store = new AuthStore();
      store.forgetServer('server-a');
      store.forgetServer('server-b');
    });

    it('switch_server_restores_only_that_servers_tokens', 0, async () => {
      await store.activateServer('server-a', 'https://a.example');
      client.setBaseUrl('https://a.example/api/v1');
      store.setTokens(tokens('access-a', 'refresh-a'));
      store.setDeviceIdentity('pair-a', 'secret-a');

      await store.activateServer('server-b', 'https://b.example');
      client.setBaseUrl('https://b.example/api/v1');
      expect(store.accessToken).assertEqual('');
      expect(store.refreshToken).assertEqual('');
      expect(store.pairingId).assertEqual('');
      await client.get('/me');
      expect(backend.lastHeaders['Authorization']).assertUndefined();

      store.setTokens(tokens('access-b', 'refresh-b'));
      await client.get('/me');
      expect(backend.lastHeaders['Authorization']).assertEqual('Bearer access-b');

      await store.activateServer('server-a', 'https://a.example');
      client.setBaseUrl('https://a.example/api/v1');
      await client.get('/me');
      expect(backend.lastHeaders['Authorization']).assertEqual('Bearer access-a');
      expect(store.pairingId).assertEqual('pair-a');
    });

    it('host_protocol_or_port_mismatch_removes_bearer', 0, async () => {
      await store.activateServer('server-a', 'https://api.example.com:443');
      client.setBaseUrl('https://api.example.com/api/v1');
      store.setTokens(tokens('access-a', 'refresh-a'));
      const origins: string[] = [
        'https://evil.example/api/v1',
        'http://api.example.com/api/v1',
        'https://api.example.com:444/api/v1',
      ];
      for (const origin of origins) {
        client.setBaseUrl(origin);
        await client.get('/me');
        expect(backend.lastHeaders['Authorization']).assertUndefined();
      }
    });

    it('same_server_origin_switch_window_never_exposes_previous_bearer', 0, async () => {
      await store.activateServer('server-a', 'https://a.example');
      client.setBaseUrl('https://a.example/api/v1');
      store.setTokens(tokens('access-a', 'refresh-a'));
      client.setBaseUrl('https://other.example/api/v1');

      const switching = store.activateServer('server-a', 'https://other.example');
      await client.get('/me');
      expect(backend.lastHeaders['Authorization']).assertUndefined();
      await switching;

      expect(store.accessToken).assertEqual('');
      expect(store.refreshToken).assertEqual('');
    });

    it('same_server_id_with_changed_origin_cannot_reuse_refresh', 0, async () => {
      const storage = await initStorage();
      await store.activateServer('server-a', 'https://a.example');
      store.setTokens(tokens('access-a', 'refresh-a'));
      await store.activateServer('server-a', 'https://other.example');
      client.setBaseUrl('https://other.example/api/v1');
      await store.restore();

      expect(store.refreshToken).assertEqual('');
      expect(backend.requestCount).assertEqual(0);
      expect(await storage.get<string>('auth:server:server-a:refresh_token', '')).assertEqual('');
    });

    it('forget_server_clears_only_that_server_vault', 0, async () => {
      const storage = await initStorage();
      await store.activateServer('server-a', 'https://a.example');
      store.setTokens(tokens('access-a', 'refresh-a'));
      store.setWsPairing('ws-a', 'wss://a.example/ws');
      await store.activateServer('server-b', 'https://b.example');
      store.setTokens(tokens('access-b', 'refresh-b'));

      store.forgetServer('server-a');
      expect(await storage.get<string>('auth:server:server-a:refresh_token', '')).assertEqual('');
      expect(await storage.get<string>('auth:server:server-a:ws_token', '')).assertEqual('');
      expect(await storage.get<string>('auth:server:server-b:refresh_token', '')).assertEqual('refresh-b');
      expect(store.accessToken).assertEqual('access-b');
    });
  });
}
