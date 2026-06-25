// Hypium 单元测试入口
import { describe, it, expect } from '@ohos/hypium';

export default function abilityTest() {
  describe('EntryAbility', () => {
    it('app_starts_successfully', 0, () => {
      // M1.0 工程骨架冒烟测试
      expect(true).assertTrue();
    });
  });
}
