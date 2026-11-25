// AuthStore 单元测试 - P1-36 凭证持久化
// 验证：refresh_token/wsToken/wsUrl/pairingId/deviceSecret 写穿到 StorageAdapter 落盘，
// logout 清除持久化，restore 无凭证时安全回落（不抛错、isAuthenticated=false）。
// 运行环境：模拟器真机 preferences（每个用例先 init(context)，幂等）。
import { describe, it, expect, beforeEach } from '@ohos/hypium';
import { AuthStore } from '../../../main/ets/libs/state/stores/AuthStore';
import { StorageAdapter } from '../../../main/ets/libs/adapters/StorageAdapter';
import { TestContext } from '../testability/TestContext';
import { AuthTokens, User } from '../../../main/ets/libs/types';

/** 每用例初始化存储桥（TestRunner 已 startAbility 拉起 TestAbility，这里轮询等装配完成） */
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

/** 构造 token 对（显式类型，替代内联字面量） */
function makeTokens(access: string, refresh: string): AuthTokens {
  const t: AuthTokens = {
    access_token: access, refresh_token: refresh, token_type: 'Bearer', expires_in: 3600,
  };
  return t;
}

/** 构造已登录用户（显式类型） */
function makeUser(): User {
  const user: User = {
    id: 'u1', username: 'tester', email: 't@n.io', role: 'user', status: 'active',
  };
  return user;
}

export default function authStoreTest() {
  describe('AuthStore', () => {
    let store: AuthStore;

    beforeEach(async () => {
      store = new AuthStore();
      await initStorage();
      store.forgetServer('server-a');
      store.forgetServer('server-b');
    });

    async function activateA(): Promise<void> {
      await store.activateServer('server-a', 'https://a.example');
    }

    it('setTokens_persists_refresh_token_only', 0, async () => {
      const storage = await initStorage();
      await activateA();
      store.setTokens(makeTokens('at-x', 'rt-y'));
      expect(store.accessToken).assertEqual('at-x');
      expect(store.refreshToken).assertEqual('rt-y');
      // refresh_token 落盘；access_token 只在内存
      const persistedRefresh = await storage.get<string>('auth:server:server-a:refresh_token', '');
      expect(persistedRefresh).assertEqual('rt-y');
      expect(await storage.get<string>('auth:refresh_token', '')).assertEqual('');
      const persistedAccess = await storage.get<string>('auth:access_token', '');
      expect(persistedAccess).assertEqual('');
    });

    it('setDeviceIdentity_persists_pairing_credentials', 0, async () => {
      const storage = await initStorage();
      await activateA();
      store.setDeviceIdentity('pair-1', 'secret-1');
      expect(store.pairingId).assertEqual('pair-1');
      expect(store.deviceSecret).assertEqual('secret-1');
      const pairingId = await storage.get<string>('auth:server:server-a:pairing_id', '');
      const secret = await storage.get<string>('auth:server:server-a:device_secret', '');
      expect(pairingId).assertEqual('pair-1');
      expect(secret).assertEqual('secret-1');
    });

    it('setWsPairing_persists_ws_credentials', 0, async () => {
      const storage = await initStorage();
      await activateA();
      store.setWsPairing('wst-1', 'ws://s.example.com/ws');
      expect(store.isPaired).assertTrue();
      const wsToken = await storage.get<string>('auth:server:server-a:ws_token', '');
      const wsUrl = await storage.get<string>('auth:server:server-a:ws_url', '');
      expect(wsToken).assertEqual('wst-1');
      expect(wsUrl).assertEqual('ws://s.example.com/ws');
    });

    it('logout_clears_memory_and_persisted_credentials', 0, async () => {
      const storage = await initStorage();
      await activateA();
      store.setTokens(makeTokens('at-1', 'rt-1'));
      store.setDeviceIdentity('p1', 's1');
      store.logout();
      expect(store.isAuthenticated).assertFalse();
      expect(store.refreshToken).assertEqual('');
      const persistedRefresh = await storage.get<string>('auth:server:server-a:refresh_token', '');
      const persistedPairing = await storage.get<string>('auth:server:server-a:pairing_id', '');
      expect(persistedRefresh).assertEqual('');
      expect(persistedPairing).assertEqual('');
    });

    it('restore_without_credentials_stays_logged_out', 0, async () => {
      await initStorage();
      await activateA();
      await store.restore();
      expect(store.isAuthenticated).assertFalse();
      expect(store.isPaired).assertFalse();
    });

    it('restore_with_memory_access_token_skips_refresh', 0, async () => {
      await initStorage();
      await activateA();
      store.setTokens(makeTokens('at-warm', 'rt-warm'));
      store.setUser(makeUser());
      // access_token 在内存：restore 直接返回，不发起续签（无网络也平安）
      await store.restore();
      expect(store.accessToken).assertEqual('at-warm');
    });
  });
}
