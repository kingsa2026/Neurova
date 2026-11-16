// envelope 单元测试 - 移动端信封归一单一事实源（S4 P1-28/29）
// 后端三种返回形状（裸数组/裸对象/{success,data}）必须在 API 模块边界归一为 {code,data}。
import { describe, it, expect } from '@ohos/hypium';
import { asEnvelope, asEnvelopeList, asEnvelopeSuccessData, isBareShape } from '../../../main/ets/libs/api/envelope';
import { ApiResponse } from '../../../main/ets/libs/types';

/** 探针契约（模拟后端裸对象） */
interface ProbeDto {
  id: string;
  name: string;
}

export default function envelopeTest() {
  describe('Envelope', () => {
    it('isBareShape_rejects_envelope_and_requires_probes', 0, () => {
      const bare: Record<string, Object> = { 'id': '1', 'name': 'x' };
      expect(isBareShape(bare, ['id', 'name'])).assertTrue();
      const enveloped: Record<string, Object> = { 'code': 0, 'data': bare };
      expect(isBareShape(enveloped, ['id', 'name'])).assertFalse();
      const partial: Record<string, Object> = { 'id': '1' };
      expect(isBareShape(partial, ['id', 'name'])).assertFalse();
    });

    it('asEnvelope_wraps_bare_object', 0, () => {
      const dto: ProbeDto = { id: 'r1', name: '规则一' };
      const bare = dto as Object as ApiResponse<ProbeDto>;
      const res = asEnvelope<ProbeDto>(bare, ['id', 'name']);
      expect(res.code).assertEqual(0);
      expect(res.data!.id).assertEqual('r1');
      expect(res.data!.name).assertEqual('规则一');
    });

    it('asEnvelope_passes_envelope_through', 0, () => {
      const dto: ProbeDto = { id: 'r2', name: '规则二' };
      const env: ApiResponse<ProbeDto> = { code: 0, message: 'ok', data: dto };
      const res = asEnvelope<ProbeDto>(env, ['id', 'name']);
      expect(res.code).assertEqual(0);
      expect(res.data!.name).assertEqual('规则二');
    });

    it('asEnvelopeList_wraps_bare_array', 0, () => {
      const arr: ProbeDto[] = [{ id: 'a', name: 'x' }, { id: 'b', name: 'y' }];
      const bare = arr as Object as ApiResponse<ProbeDto[]>;
      const res = asEnvelopeList<ProbeDto>(bare);
      expect(res.code).assertEqual(0);
      expect(res.data!.length).assertEqual(2);
      expect(res.data![1].id).assertEqual('b');
    });

    it('asEnvelopeSuccessData_unwraps_success_dict', 0, () => {
      const payload: ProbeDto = { id: 'n1', name: '神经元' };
      const dict: Record<string, Object> = { 'success': true, 'data': payload, 'total': 1 };
      const bare = dict as Object as ApiResponse<ProbeDto>;
      const res = asEnvelopeSuccessData<ProbeDto>(bare);
      expect(res.code).assertEqual(0);
      expect(res.data!.name).assertEqual('神经元');
    });

    it('asEnvelopeSuccessData_maps_failure_to_code_1', 0, () => {
      const empty: Record<string, Object> = {};
      const dict: Record<string, Object> = { 'success': false, 'data': empty };
      const bare = dict as Object as ApiResponse<ProbeDto>;
      const res = asEnvelopeSuccessData<ProbeDto>(bare);
      expect(res.code).assertEqual(1);
    });
  });
}
