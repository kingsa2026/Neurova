// SimpleDataSource 单元测试 - TDD 红绿灯垂直切片
// 验证 LazyForEach 数据源契约（IDataSource 接口）+ 业务方法（setData/addItem/updateItem/removeItem）
// 纯逻辑无 UI 依赖，通过 mock DataChangeListener 验证通知行为
import { describe, it, expect, beforeEach } from '@ohos/hypium';
import { SimpleDataSource } from '../../../../main/ets/libs/perf/SimpleDataSource';

/** Mock 数据变更监听器（记录所有通知调用便于断言） */
class MockListener {
  public reloadCount: number = 0;
  public datasetOps: { type: string; index?: number; count?: number }[] = [];

  onDataReloaded(): void {
    this.reloadCount++;
  }

  onDatasetChange(ops: { type: string; index?: number; count?: number }[]): void {
    this.datasetOps = this.datasetOps.concat(ops);
  }

  reset(): void {
    this.reloadCount = 0;
    this.datasetOps = [];
  }
}

export default function simpleDataSourceTest() {
  describe('SimpleDataSource', () => {
    let ds: SimpleDataSource<string>;
    let listener: MockListener;

    beforeEach(() => {
      ds = new SimpleDataSource<string>();
      listener = new MockListener();
    });

    // ========== 行为 1: 初始 totalCount 为 0 ==========
    it('initial_totalCount_is_zero', 0, () => {
      expect(ds.totalCount()).assertEqual(0);
    });

    // ========== 行为 2: setData 后 totalCount 与 getData 正确 ==========
    it('setData_populates_data', 0, () => {
      ds.setData(['a', 'b', 'c']);
      expect(ds.totalCount()).assertEqual(3);
      expect(ds.getData(0)).assertEqual('a');
      expect(ds.getData(1)).assertEqual('b');
      expect(ds.getData(2)).assertEqual('c');
    });

    // ========== 行为 3: getData 越界抛 RangeError ==========
    it('getData_out_of_bounds_throws', 0, () => {
      ds.setData(['a']);
      let threw = false;
      try {
        ds.getData(5);
      } catch (e) {
        threw = true;
      }
      expect(threw).assertTrue();
    });

    // ========== 行为 4: registerDataChangeListener 记录监听器 ==========
    it('register_adds_listener', 0, () => {
      ds.registerDataChangeListener(listener as any);
      ds.setData(['a']);
      expect(listener.reloadCount).assertEqual(1);
    });

    // ========== 行为 5: unregisterDataChangeListener 移除监听器 ==========
    it('unregister_removes_listener', 0, () => {
      ds.registerDataChangeListener(listener as any);
      ds.unregisterDataChangeListener(listener as any);
      ds.setData(['a']);
      expect(listener.reloadCount).assertEqual(0);
    });

    // ========== 行为 6: 重复 register 同一 listener 只保留一份 ==========
    it('duplicate_register_keeps_one', 0, () => {
      ds.registerDataChangeListener(listener as any);
      ds.registerDataChangeListener(listener as any);
      ds.setData(['a']);
      expect(listener.reloadCount).assertEqual(1);
    });

    // ========== 行为 7: unregister 不存在的 listener 不抛错 ==========
    it('unregister_nonexistent_no_throw', 0, () => {
      let threw = false;
      try {
        ds.unregisterDataChangeListener(listener as any);
      } catch (e) {
        threw = true;
      }
      expect(threw).assertFalse();
    });

    // ========== 行为 8: setData 触发 onDataReloaded ==========
    it('setData_triggers_onDataReloaded', 0, () => {
      ds.registerDataChangeListener(listener as any);
      ds.setData(['a']);
      ds.setData(['b', 'c']);
      expect(listener.reloadCount).assertEqual(2);
    });

    // ========== 行为 9: addItem 末尾追加，触发 ADD op ==========
    it('addItem_appends_and_notifies_ADD', 0, () => {
      ds.registerDataChangeListener(listener as any);
      ds.setData(['a']);
      listener.reset();
      ds.addItem('b');
      expect(ds.totalCount()).assertEqual(2);
      expect(ds.getData(1)).assertEqual('b');
      expect(listener.datasetOps.length).assertEqual(1);
      expect(listener.datasetOps[0].type).assertEqual('ADD');
      expect(listener.datasetOps[0].index).assertEqual(1);
      expect(listener.datasetOps[0].count).assertEqual(1);
    });

    // ========== 行为 10: updateItem 修改，触发 MODIFY op ==========
    it('updateItem_modifies_and_notifies_MODIFY', 0, () => {
      ds.registerDataChangeListener(listener as any);
      ds.setData(['a', 'b']);
      listener.reset();
      ds.updateItem(0, 'x');
      expect(ds.getData(0)).assertEqual('x');
      expect(listener.datasetOps.length).assertEqual(1);
      expect(listener.datasetOps[0].type).assertEqual('MODIFY');
      expect(listener.datasetOps[0].index).assertEqual(0);
    });

    // ========== 行为 11: updateItem 越界不抛错也不通知 ==========
    it('updateItem_out_of_bounds_no_throw_no_notify', 0, () => {
      ds.registerDataChangeListener(listener as any);
      ds.setData(['a']);
      listener.reset();
      let threw = false;
      try {
        ds.updateItem(10, 'x');
      } catch (e) {
        threw = true;
      }
      expect(threw).assertFalse();
      expect(listener.datasetOps.length).assertEqual(0);
    });

    // ========== 行为 12: removeItem 删除，触发 DELETE op ==========
    it('removeItem_removes_and_notifies_DELETE', 0, () => {
      ds.registerDataChangeListener(listener as any);
      ds.setData(['a', 'b', 'c']);
      listener.reset();
      ds.removeItem(1);
      expect(ds.totalCount()).assertEqual(2);
      expect(ds.getData(0)).assertEqual('a');
      expect(ds.getData(1)).assertEqual('c');
      expect(listener.datasetOps.length).assertEqual(1);
      expect(listener.datasetOps[0].type).assertEqual('DELETE');
      expect(listener.datasetOps[0].index).assertEqual(1);
    });

    // ========== 行为 13: removeItem 越界不抛错 ==========
    it('removeItem_out_of_bounds_no_throw', 0, () => {
      ds.registerDataChangeListener(listener as any);
      ds.setData(['a']);
      listener.reset();
      let threw = false;
      try {
        ds.removeItem(10);
      } catch (e) {
        threw = true;
      }
      expect(threw).assertFalse();
      expect(listener.datasetOps.length).assertEqual(0);
    });

    // ========== 行为 14: getAll 返回浅拷贝（修改不影响内部） ==========
    it('getAll_returns_copy', 0, () => {
      ds.setData(['a', 'b']);
      const arr = ds.getAll();
      arr.push('c');
      // 修改返回值不应影响内部
      expect(ds.totalCount()).assertEqual(2);
    });

    // ========== 行为 15: 多个 listener 都收到通知 ==========
    it('multiple_listeners_all_notified', 0, () => {
      const l1 = new MockListener();
      const l2 = new MockListener();
      ds.registerDataChangeListener(l1 as any);
      ds.registerDataChangeListener(l2 as any);
      ds.setData(['a']);
      expect(l1.reloadCount).assertEqual(1);
      expect(l2.reloadCount).assertEqual(1);
    });

    // ========== 行为 16: notifyReload 手动触发 ==========
    it('notifyReload_triggers_onDataReloaded', 0, () => {
      ds.registerDataChangeListener(listener as any);
      ds.notifyReload();
      expect(listener.reloadCount).assertEqual(1);
    });

    // ========== 行为 17: 完整列表操作周期：setData→add→update→remove ==========
    it('full_list_operation_cycle', 0, () => {
      ds.registerDataChangeListener(listener as any);
      ds.setData(['a', 'b']);
      expect(ds.totalCount()).assertEqual(2);

      ds.addItem('c');
      expect(ds.totalCount()).assertEqual(3);
      expect(ds.getData(2)).assertEqual('c');

      ds.updateItem(1, 'B');
      expect(ds.getData(1)).assertEqual('B');

      ds.removeItem(0);
      expect(ds.totalCount()).assertEqual(2);
      expect(ds.getData(0)).assertEqual('B');
      expect(ds.getData(1)).assertEqual('c');
    });
  });
}
