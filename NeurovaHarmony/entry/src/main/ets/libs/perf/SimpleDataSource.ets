/**
 * SimpleDataSource - 通用 IDataSource 实现，配合 LazyForEach 用于长列表惰性渲染
 *
 * 职责：实现 ArkUI IDataSource 接口，提供 setData/addItem/updateItem/removeItem 业务方法
 * 设计：
 *   - 内部维护 data 数组与 listeners 列表
 *   - 数据变更通过 notifyDataReload / notifyDatasetChange 通知所有 listener
 *   - register/unregister 支持幂等（重复 register 同一 listener 只保留一份）
 *   - 越界 update/remove 静默忽略（不抛错，便于业务层容错）
 *   - getData 越界抛 RangeError（开发者错误，应修复）
 *   - getAll 返回浅拷贝，避免外部修改污染内部数据
 *
 * 用法：
 *   private ds: SimpleDataSource<Agent> = new SimpleDataSource<Agent>();
 *   build() {
 *     LazyForEach(this.ds, (item: Agent) => { ListItem() { ... } }, (item: Agent) => item.id)
 *   }
 *   // 数据变更：
 *   this.ds.setData(agents);
 *   this.ds.addItem(newAgent);
 *   this.ds.updateItem(index, updated);
 *   this.ds.removeItem(index);
 *
 * TDD：SimpleDataSource.test.ets 按红绿灯垂直切片逐步实现
 */

/**
 * 数据变更操作类型（与 ArkUI DataOperationType 对应）
 * - ADD：在 index 处添加 count 个项
 * - DELETE：从 index 处删除 count 个项
 * - MODIFY：从 index 处修改 count 个项
 */
export type SimpleDataOpType = 'ADD' | 'DELETE' | 'MODIFY';

/** 数据变更操作 */
export interface SimpleDataOperation {
  type: SimpleDataOpType;
  index: number;
  count: number;
}

/**
 * 数据变更监听器（与 ArkUI DataChangeListener 鸭子类型兼容）
 * 在 LazyForEach 中由 ArkUI 自动注册实例，本类只调用其 onDataReloaded/onDatasetChange
 */
export interface SimpleDataChangeListener {
  onDataReloaded(): void;
  onDatasetChange?(operations: SimpleDataOperation[]): void;
}

export class SimpleDataSource<T> {
  /** 内部数据数组 */
  private data: T[] = [];
  /** 已注册的监听器（去重） */
  private listeners: SimpleDataChangeListener[] = [];

  /** 数据总量 */
  totalCount(): number {
    return this.data.length;
  }

  /** 获取指定索引项；越界抛 RangeError */
  getData(index: number): T {
    if (index < 0 || index >= this.data.length) {
      throw new RangeError(`SimpleDataSource.getData 索引越界：${index}，当前长度 ${this.data.length}`);
    }
    return this.data[index];
  }

  /** 注册监听器（幂等：重复注册同一实例只保留一份） */
  registerDataChangeListener(listener: SimpleDataChangeListener): void {
    if (this.listeners.indexOf(listener) < 0) {
      this.listeners.push(listener);
    }
  }

  /** 注销监听器（不存在时静默忽略） */
  unregisterDataChangeListener(listener: SimpleDataChangeListener): void {
    const pos = this.listeners.indexOf(listener);
    if (pos >= 0) {
      this.listeners.splice(pos, 1);
    }
  }

  /** 一次性替换全部数据并触发 onDataReloaded */
  setData(arr: T[]): void {
    this.data = arr.slice();
    this.notifyReload();
  }

  /** 末尾追加一个项并通知 ADD */
  addItem(item: T): void {
    this.data.push(item);
    this.notifyDatasetChange([{
      type: 'ADD',
      index: this.data.length - 1,
      count: 1,
    }]);
  }

  /** 修改指定索引项；越界静默忽略 */
  updateItem(index: number, item: T): void {
    if (index < 0 || index >= this.data.length) return;
    this.data[index] = item;
    this.notifyDatasetChange([{
      type: 'MODIFY',
      index,
      count: 1,
    }]);
  }

  /** 删除指定索引项；越界静默忽略 */
  removeItem(index: number): void {
    if (index < 0 || index >= this.data.length) return;
    this.data.splice(index, 1);
    this.notifyDatasetChange([{
      type: 'DELETE',
      index,
      count: 1,
    }]);
  }

  /** 返回内部数据的浅拷贝 */
  getAll(): T[] {
    return this.data.slice();
  }

  /** 手动触发 onDataReloaded 通知所有 listener */
  notifyReload(): void {
    this.listeners.forEach(l => l.onDataReloaded());
  }

  /** 手动触发 onDatasetChange 通知所有 listener */
  notifyDatasetChange(ops: SimpleDataOperation[]): void {
    this.listeners.forEach(l => {
      if (l.onDatasetChange) {
        l.onDatasetChange(ops);
      }
    });
  }
}
