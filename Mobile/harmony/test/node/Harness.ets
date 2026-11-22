/**
 * Harness - 极简红绿断言工具（Node 直跑 .ets 单测共用）
 *
 * 供各 *.test.ets import；check/eq 即时打印 PASS/FAIL，失败进 failures，
 * run.mjs 末尾汇总并决定退出码。刻意不引第三方测试框架——被测模块与测试
 * 都只依赖 Node 内置能力。
 */

export const failures: string[] = [];
export let passed: number = 0;

/** 断言布尔条件；detail 供失败定位（如实际值摘要） */
export function check(name: string, ok: boolean, detail: string = ''): void {
  if (ok) {
    passed = passed + 1;
    console.log(`[PASS] ${name}`);
  } else {
    failures.push(name);
    console.log(`[FAIL] ${name}${detail === '' ? '' : ' — ' + detail}`);
  }
}

/** 深比较断言（JSON 同形即等；对象键序不敏感由 JSON.stringify 的键序保证——构造时一致） */
export function eq(name: string, actual: Object, expected: Object): void {
  const a = JSON.stringify(actual);
  const b = JSON.stringify(expected);
  check(name, a === b, `actual=${a} expected=${b}`);
}

/** 字符串相等断言 */
export function eqStr(name: string, actual: string, expected: string): void {
  check(name, actual === expected, `actual=${actual} expected=${expected}`);
}

/** 标注用例来源（Issue/事故/评审），运行时只打印，便于对账 */
export function source(note: string): void {
  console.log(`--- 来源: ${note}`);
}
