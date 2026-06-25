// ModuleManager 单元测试 - TDD 垂直切片
// 通过 ModuleInterface 公共接口验证 ModuleManager 行为，不耦合实现细节
import { describe, it, expect, beforeEach } from '@ohos/hypium';
import { ModuleManager } from '../../../../main/ets/libs/module/ModuleManager';
import { ModuleInterface } from '../../../../main/ets/libs/module/ModuleInterface';

// 测试模块：实现 ModuleInterface，按需注入回调
// 使用类（而非对象字面量）以保证 ArkTS 类型严格兼容
class TestModule implements ModuleInterface {
  readonly name: string;
  readonly version: string;
  private readonly loadCb?: () => Promise<void>;
  private readonly unloadCb?: () => Promise<void>;
  private readonly eventCb?: (e: string, d: Object) => void;

  constructor(name: string, opts?: {
    onLoad?: () => Promise<void>;
    onUnload?: () => Promise<void>;
    onEvent?: (e: string, d: Object) => void;
  }) {
    this.name = name;
    this.version = '1.0.0';
    if (opts) {
      this.loadCb = opts.onLoad;
      this.unloadCb = opts.onUnload;
      this.eventCb = opts.onEvent;
    }
  }

  async onLoad(): Promise<void> {
    if (this.loadCb) {
      await this.loadCb();
    }
  }

  async onUnload(): Promise<void> {
    if (this.unloadCb) {
      await this.unloadCb();
    }
  }

  onEvent(event: string, data: Object): void {
    if (this.eventCb) {
      this.eventCb(event, data);
    }
  }
}

// Helper: 构造测试模块（保持与设计文档一致的调用形态）
function makeModule(name: string, opts?: {
  onLoad?: () => Promise<void>;
  onUnload?: () => Promise<void>;
  onEvent?: (e: string, d: Object) => void;
}): ModuleInterface {
  return new TestModule(name, opts);
}

export default function moduleManagerTest() {
  describe('ModuleManager', () => {
    let mm: ModuleManager;

    beforeEach(() => {
      mm = ModuleManager.getInstance();
      // 清空所有已注册模块（保证用例间隔离）
      for (const name of mm.list()) {
        mm.unregister(name);
      }
    });

    // ========== Tracer Bullet: 单例 ==========

    // 1. getInstance 返回单例
    it('getInstance_returns_singleton', 0, () => {
      expect(ModuleManager.getInstance()).assertEqual(ModuleManager.getInstance());
    });

    // ========== 行为 1: 注册 / 查询 ==========

    // 2. register 后 isRegistered 返回 true
    it('register_then_isRegistered_true', 0, () => {
      mm.register(makeModule('M1'));
      expect(mm.isRegistered('M1')).assertTrue();
    });

    // 3. register 后 list 包含模块名
    it('register_then_list_contains_name', 0, () => {
      mm.register(makeModule('M2'));
      const names = mm.list();
      expect(names.indexOf('M2') >= 0).assertTrue();
    });

    // 4. unregister 后 isRegistered 返回 false
    it('unregister_then_isRegistered_false', 0, () => {
      mm.register(makeModule('M3'));
      mm.unregister('M3');
      expect(mm.isRegistered('M3')).assertFalse();
    });

    // 5. 未注册的模块 isRegistered 返回 false
    it('isRegistered_false_for_unregistered', 0, () => {
      expect(mm.isRegistered('NeverRegistered')).assertFalse();
    });

    // ========== 行为 2: 加载 / 卸载 ==========

    // 6. load 后 isLoaded 返回 true
    it('load_then_isLoaded_true', 0, async () => {
      mm.register(makeModule('M4'));
      await mm.load('M4');
      expect(mm.isLoaded('M4')).assertTrue();
    });

    // 7. load 调用模块的 onLoad
    it('load_invokes_onLoad', 0, async () => {
      let called = false;
      mm.register(makeModule('M5', { onLoad: async () => { called = true; } }));
      await mm.load('M5');
      expect(called).assertTrue();
    });

    // 8. unload 后 isLoaded 返回 false
    it('unload_then_isLoaded_false', 0, async () => {
      mm.register(makeModule('M6'));
      await mm.load('M6');
      await mm.unload('M6');
      expect(mm.isLoaded('M6')).assertFalse();
    });

    // 9. unload 调用模块的 onUnload
    it('unload_invokes_onUnload', 0, async () => {
      let called = false;
      mm.register(makeModule('M7', { onUnload: async () => { called = true; } }));
      await mm.load('M7');
      await mm.unload('M7');
      expect(called).assertTrue();
    });

    // ========== 行为 3: 事件广播 ==========

    // 10. emit 调用所有已加载模块的 onEvent
    it('emit_invokes_onEvent_on_loaded_modules', 0, async () => {
      let receivedA: string | null = null;
      let receivedB: string | null = null;
      mm.register(makeModule('A', { onEvent: (e) => { receivedA = e; } }));
      mm.register(makeModule('B', { onEvent: (e) => { receivedB = e; } }));
      await mm.load('A');
      await mm.load('B');
      mm.emit('test:event', { value: 1 });
      expect(receivedA).assertEqual('test:event');
      expect(receivedB).assertEqual('test:event');
    });

    // 11. unload 已加载模块时同时调用 onUnload（与用例 9 互补：覆盖已加载分支）
    it('unload_loaded_module_invokes_onUnload', 0, async () => {
      let called = false;
      mm.register(makeModule('M8', { onUnload: async () => { called = true; } }));
      await mm.load('M8');
      expect(mm.isLoaded('M8')).assertTrue();
      await mm.unload('M8');
      expect(called).assertTrue();
      expect(mm.isLoaded('M8')).assertFalse();
    });

    // ========== 行为 4: 异常路径 ==========

    // 12. register 重复同名模块抛出错误
    it('register_duplicate_throws', 0, () => {
      mm.register(makeModule('Dup'));
      let threw = false;
      try {
        mm.register(makeModule('Dup'));
      } catch (e) {
        threw = true;
      }
      expect(threw).assertTrue();
    });

    // 13. load 未注册模块抛出错误
    it('load_unregistered_throws', 0, async () => {
      let threw = false;
      try {
        await mm.load('Nonexistent');
      } catch (e) {
        threw = true;
      }
      expect(threw).assertTrue();
    });
  });
}
