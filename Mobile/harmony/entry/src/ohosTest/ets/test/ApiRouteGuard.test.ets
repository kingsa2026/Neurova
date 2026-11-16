// ApiRouteGuard - 「路径不重复写 /v1」模块守卫（S4 P1-30）
// baseUrl 已含 /api/v1（ServerProfiles.getActiveApiBase = {server}/api/v1），
// 任何 API 模块再写 /v1/ 字面量都会拼出 /api/v1/v1/... → 404。
// 本守卫用录制型后端逐一触发各模块的代表方法，断言：
//   1) 每条 URL 都以 baseUrl 开头；
//   2) 去掉 baseUrl 后的路径段不得以 /v1/ 开头（即全 URL 不含 /v1/v1）；
//   3) neuron 系列走 /api/neuron（后端自述前缀挂 /api 下，无 /v1）。
import { describe, it, expect, beforeEach } from '@ohos/hypium';
import { HttpClient, HttpBackend, HttpBackendResponse } from '../../../main/ets/libs/api/HttpClient';
import { ApiResponse } from '../../../main/ets/libs/types';
import { PushApi } from '../../../main/ets/libs/api/modules/PushApi';
import { HealthApi } from '../../../main/ets/libs/api/modules/HealthApi';
import { SettingsApi } from '../../../main/ets/libs/api/modules/SettingsApi';
import { SessionsApi } from '../../../main/ets/libs/api/modules/SessionsApi';
import { AgentChannelsApi, emptyExtra } from '../../../main/ets/libs/api/modules/AgentChannelsApi';
import { ChannelIntegrationApi } from '../../../main/ets/libs/api/modules/ChannelIntegrationApi';
import { SessionSyncApi } from '../../../main/ets/libs/api/modules/SessionSyncApi';
import { MonitorApi } from '../../../main/ets/libs/api/modules/MonitorApi';
import { CapabilityApi } from '../../../main/ets/libs/api/modules/CapabilityApi';
import { RuntimeApi } from '../../../main/ets/libs/api/modules/RuntimeApi';
import { CollaborationApi } from '../../../main/ets/libs/api/modules/CollaborationApi';
import { WebhookApi } from '../../../main/ets/libs/api/modules/WebhookApi';

/** 录制的请求 */
interface RecordedRequest {
  method: string;
  url: string;
  body: Object | null;
}

class RecordingBackend implements HttpBackend {
  public requests: RecordedRequest[] = [];

  async request(
    method: string,
    url: string,
    body: Object | null,
    _headers: Record<string, string>,
  ): Promise<HttpBackendResponse> {
    const recorded: RecordedRequest = { method: method, url: url, body: body };
    this.requests.push(recorded);
    const empty: Record<string, Object> = {};
    const resp: HttpBackendResponse = { status: 200, data: empty as Object as ApiResponse<Object> };
    return resp;
  }
}

const BASE = 'https://s.example.com/api/v1';

/** 触发一个请求并吞掉业务异常（守卫只关心 URL 形状） */
async function probe(fn: () => Promise<Object>): Promise<void> {
  try {
    await fn();
  } catch (e) {
    // 业务失败（如 data 缺失抛错）不影响路径守卫断言
  }
}

export default function apiRouteGuardTest() {
  describe('ApiRouteGuard', () => {
    let backend: RecordingBackend;
    let client: HttpClient;

    beforeEach(() => {
      backend = new RecordingBackend();
      client = HttpClient.getInstanceWithBackend(backend);
      client.setBaseUrl(BASE);
    });

    it('no_module_path_duplicates_v1_prefix', 0, async () => {
      const push = new PushApi(client);
      const health = new HealthApi(client);
      const settings = new SettingsApi(client);
      const sessions = new SessionsApi(client);
      const agentChannels = new AgentChannelsApi(client);
      const channelIntegration = new ChannelIntegrationApi(client);
      const sessionSync = new SessionSyncApi(client);
      const monitor = new MonitorApi(client);
      const capability = new CapabilityApi(client);
      const runtime = new RuntimeApi(client);
      const collaboration = new CollaborationApi(client);
      const webhook = new WebhookApi(client);

      await probe(() => push.upsert('harmony', 'token-x', 'device-1'));
      await probe(() => push.remove('device-1'));
      await probe(() => health.check());
      await probe(() => health.getService('db'));
      await probe(() => settings.list());
      await probe(() => settings.get('theme'));
      await probe(() => settings.update('theme', 'dark'));
      await probe(() => sessions.listAll(''));
      await probe(() => sessions.pin('s1', true));
      await probe(() => agentChannels.list('a1'));
      await probe(() => agentChannels.create('a1', {
        channel_type: 'feishu', enabled: true, app_id: '', app_secret: '',
        use_stream: true, webhook_url: '', webhook_token: '', encrypt_key: '',
        verification_token: '', extra: emptyExtra(),
      }));
      await probe(() => channelIntegration.list());
      await probe(() => channelIntegration.getConfig('a1', 'feishu'));
      await probe(() => sessionSync.list());
      await probe(() => monitor.getSystemStatus());
      await probe(() => monitor.getResources());
      await probe(() => monitor.listConnections());
      await probe(() => monitor.listAlerts());
      await probe(() => monitor.listLogs());
      await probe(() => monitor.clearLogs());
      await probe(() => monitor.listFiles());
      await probe(() => monitor.listNeurons());
      await probe(() => monitor.getNeuronStats());
      await probe(() => monitor.getNeuronHealth());
      await probe(() => capability.listRules(''));
      await probe(() => capability.listFiles(''));
      await probe(() => capability.listMedia(''));
      await probe(() => runtime.listScheduleTasks('a1'));
      await probe(() => runtime.listTraces('a1'));
      await probe(() => runtime.listFirewallRules('a1'));
      await probe(() => runtime.getSleepStatus('a1'));
      await probe(() => collaboration.listTemplates());
      await probe(() => collaboration.listHistory());
      await probe(() => collaboration.listSessions());
      await probe(() => collaboration.getStats());
      await probe(() => collaboration.listTasks());
      await probe(() => collaboration.listProjects());
      await probe(() => collaboration.listTeams());
      await probe(() => collaboration.listWorkflows());
      await probe(() => webhook.list());

      // 每条请求都必须可归位：普通端点以 baseUrl（…/api/v1）开头且 base 后不再有 /v1；
      // neuron 端点挂在 /api/neuron（无 /v1），以 源点/api/neuron/ 开头
      expect(backend.requests.length > 0).assertTrue();
      for (const r of backend.requests) {
        if (r.url.includes('/api/neuron/')) {
          expect(r.url.startsWith('https://s.example.com/api/neuron/')).assertTrue();
          expect(r.url.includes('/v1/neuron')).assertFalse();
          continue;
        }
        expect(r.url.startsWith(BASE)).assertTrue();
        const path = r.url.substring(BASE.length);
        expect(path.startsWith('/v1/')).assertFalse();
        expect(r.url.includes('/v1/v1')).assertFalse();
      }
    });

    it('neuron_paths_mount_at_api_neuron_without_v1', 0, async () => {
      const monitor = new MonitorApi(client);
      await probe(() => monitor.listNeurons());
      await probe(() => monitor.getNeuronStats());
      await probe(() => monitor.getNeuronHealth());
      expect(backend.requests.length >= 3).assertTrue();
      for (const r of backend.requests) {
        expect(r.url.includes('/api/neuron/')).assertTrue();
        expect(r.url.includes('/api/v1/neuron')).assertFalse();
      }
    });
  });
}
