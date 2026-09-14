// AigcApi 单元测试（M5a）- TDD 契约切片
// 验证与 Web generation.ts 同源的端点契约（URL/方法/body）+ fileUrl 拼接 + 账本映射纯函数
import { describe, it, expect, beforeEach } from '@ohos/hypium';
import { HttpClient, HttpBackend } from '../../../../main/ets/libs/api/HttpClient';
import { AigcApi } from '../../../../main/ets/libs/api/modules/AigcApi';
import { aigcTaskFromServer } from '../../../../main/ets/pages/AIGCPage';
import { ApiResponse, AigcGenerationTask } from '../../../../main/ets/libs/types';

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

const makeTask = (over: Partial<AigcGenerationTask>): AigcGenerationTask => ({
  task_id: 'g1', kind: 'image', protocol: 'openai_compat', model: 'flux',
  status: 'succeeded', prompt: 'p', submitted_at: 1757700000, updated_at: 1757700005,
  local_path: 'data/generations/g1_0.png', url: '/api/v1/generation/files/g1_0.png',
  source: 'rest', error: '', ...over,
});

export default function aigcApiTest() {
  describe('AigcApi', () => {
    let client: HttpClient;
    let backend: MockBackend;
    let api: AigcApi;

    beforeEach(() => {
      backend = new MockBackend();
      client = HttpClient.getInstanceWithBackend(backend);
      client.setBaseUrl('https://api.example.com');
      client.setToken('tok123');
      api = new AigcApi(client);
    });

    it('generateText_posts_generation_text', 0, () => {
      api.generateText({ prompt: '写一首诗' });
      expect(backend.requests[0].method).assertEqual('POST');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/generation/text');
    });

    it('generateImage_posts_generation_image', 0, () => {
      api.generateImage({ prompt: '猫', width: 1024, height: 1024, provider_id: 'p1' });
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/generation/image');
    });

    it('submitVideo_posts_generation_video', 0, () => {
      api.submitVideo({ prompt: '奔跑', duration: 5 });
      expect(backend.requests[0].method).assertEqual('POST');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/generation/video');
    });

    it('videoStatus_gets_status_by_task_id', 0, () => {
      api.videoStatus('t9');
      expect(backend.requests[0].url).assertEqual(
        'https://api.example.com/v1/generation/video/status/t9');
    });

    it('listTasks_unwraps_tasks_envelope_with_kind', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { tasks: [makeTask({})] } };
      let got: AigcGenerationTask[] = [];
      api.listTasks('image').then(r => { got = r.data; });
      expect(backend.requests[0].url).assertContain('kind=image');
      setTimeout(() => { expect(got[0].task_id).assertEqual('g1'); }, 10);
    });

    it('listVoices_unwraps_voices_envelope', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { voices: [{ id: 'v1', name: '晨' }] } };
      let count = 0;
      api.listVoices().then(r => { count = r.data.length; });
      setTimeout(() => { expect(count).assertEqual(1); }, 10);
    });

    it('usage_gets_with_days_query', 0, () => {
      api.usage(7);
      expect(backend.requests[0].url).assertContain('/v1/generation/usage');
      expect(backend.requests[0].url).assertContain('days=7');
    });

    // ========== fileUrl ==========

    it('fileUrl_joins_base_and_access_token', 0, () => {
      const u = api.fileUrl('/api/v1/generation/files/a.png');
      expect(u).assertEqual(
        'https://api.example.com/api/v1/generation/files/a.png?access_token=tok123');
    });

    it('fileUrl_passes_absolute_urls_untouched', 0, () => {
      expect(api.fileUrl('https://cdn.x/v.mp4')).assertEqual('https://cdn.x/v.mp4');
      expect(api.fileUrl('')).assertEqual('');
    });

    // ========== aigcTaskFromServer 映射纯函数 ==========

    it('maps_succeeded_with_localized_url', 0, () => {
      const t = aigcTaskFromServer(makeTask({}), 'https://api.example.com/f/a.png?access_token=x');
      expect(t.status).assertEqual('succeeded');
      expect(t.resultUrl).assertEqual('https://api.example.com/f/a.png?access_token=x');
    });

    it('maps_failed_keeps_error_original', 0, () => {
      const t = aigcTaskFromServer(makeTask({ status: 'failed', error: '凭据缺失' }), '');
      expect(t.status).assertEqual('failed');
      expect(t.errorMessage).assertEqual('凭据缺失');
    });

    it('maps_file_missing_as_succeeded_without_url', 0, () => {
      const t = aigcTaskFromServer(
        makeTask({ file_missing: true, url: '' }), '');
      expect(t.status).assertEqual('succeeded');
      expect(t.resultUrl === undefined).assertTrue();
      expect(t.errorMessage).assertContain('保留策略');
    });

    it('maps_running_to_processing', 0, () => {
      expect(aigcTaskFromServer(makeTask({ status: 'running' }), '').status).assertEqual('processing');
      expect(aigcTaskFromServer(makeTask({ status: 'submitted' }), '').status).assertEqual('processing');
    });
  });
}
