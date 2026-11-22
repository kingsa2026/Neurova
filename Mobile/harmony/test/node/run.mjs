// run - ArkTS 纯逻辑单测的 Node 直跑入口
//
// 用法（仓内无需任何 npm 依赖）：
//   node Mobile/harmony/test/node/run.mjs
// 流程：注册 .ets 模块钩子 → 逐个 import 本目录 *.test.ets → 汇总红绿退出码。
// 断言工具在 Harness.ets（同样走 .ets 钩子，被测代码零改动）。

import { register } from 'node:module';
import { readdirSync } from 'node:fs';
import { join } from 'node:path';
import { pathToFileURL, fileURLToPath } from 'node:url';

register('./ets-loader-hooks.mjs', import.meta.url);

const here = fileURLToPath(new URL('./', import.meta.url));
const testFiles = readdirSync(here).filter((f) => f.endsWith('.test.ets')).sort();

for (const file of testFiles) {
  await import(pathToFileURL(join(here, file)).href);
}

const { failures, passed } = await import(pathToFileURL(join(here, 'Harness.ets')).href);
console.log(`\n=== ${passed} passed, ${failures.length} failed ===`);
process.exit(failures.length === 0 ? 0 : 1);
