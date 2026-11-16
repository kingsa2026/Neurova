// AgentsApi 契约测试（R2 移交·用户拍板 2026-11-17 接手在途改动）
// 审计 R2：AgentsApi.toAgent 把 group_id 充当 createdAt（语义错位）——后端
// AgentInfo 有 created_at（agent.py:221，可空），createdAt 必须来自它；
// group_id 是分组标识（AdminGroups 域），不得再冒充时间戳。
// 可空字段（description/created_at/group_id 后端实测回 null）在 toAgent 里 ?? 兜底。
import { describe, it, expect, beforeEach } from '@ohos/hypium';
import { HttpClient, HttpBackend, HttpBackendResponse } from '../../../main/ets/libs/api/HttpClient';
import { ApiResponse } from '../../../main/ets/libs/types';
import { AgentsApi } from '../../../main/ets/libs/api/modules/AgentsApi';

interface RecordedRequest {
  method: string;
  url: string;
  body: Object | null;
}

class MockBackend implements HttpBackend {
  public requests: RecordedRequest[] = [];
  public responseBody: Object = new Object();

  async request(
    method: string,
    url: string,
    body: Object | null,
    _headers: Record<string, string>,
  ): Promise<HttpBackendResponse> {
    const recorded: RecordedRequest = { method: method, url: url, body: body };
    this.requests.push(recorded);
    const resp: HttpBackendResponse = { status: 200, data: this.responseBody as Object as ApiResponse<Object> };
    return resp;
  }
}

/** 构造一行后端 AgentInfo（裸数组元素；group_id/created_at 按调用方给定） */
function agentRow(agentId: string, createdAt: string, groupId: string): Record<string, Object> {
  const r: Record<string, Object> = {};
  r['agent_id'] = agentId;
  r['name'] = 'N';
  r['description'] = '';
  r['model'] = 'm';
  r['provider'] = 'p';
  r['status'] = 'active';
  r['created_at'] = createdAt;
  r['group_id'] = groupId;
  return r;
}

function agentListBody(rows: Record<string, Object>[]): Object[] {
  const arr: Object[] = [];
  for (const r of rows) {
    arr.push(r);
  }
  return arr;
}

export default function agentsApiTest() {
  describe('AgentsApi', () => {
    let client: HttpClient;
    let backend: MockBackend;
    let api: AgentsApi;

    beforeEach(() => {
      backend = new MockBackend();
      client = HttpClient.getInstanceWithBackend(backend);
      client.setBaseUrl('https://api.example.com');
      api = new AgentsApi(client);
    });

    it('list_maps_createdAt_from_backend_created_at', 0, async () => {
      const arr: Object[] = [agentRow('a1', '2026-11-17T10:00:00', '')];
      backend.responseBody = arr as Object;
      const out = await api.list();
      expect(out.length).assertEqual(1);
      expect(out[0].createdAt).assertEqual('2026-11-17T10:00:00');
    });

    it('list_never_uses_group_id_as_timestamp', 0, async () => {
      const arr: Object[] = [agentRow('a2', '', 'g-9')];
      backend.responseBody = arr as Object;
      const out = await api.list();
      expect(out[0].createdAt).assertEqual('');
    });
  });
}
