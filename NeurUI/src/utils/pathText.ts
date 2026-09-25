/**
 * 路径文案助手（单一事实源）。
 *
 * 「取路径末段文件名」在本仓此前有三份实现：`utils/artifacts.ts` 里的私有
 * `basename`、aigc 两页各自的 `refFileName`、以及 StudioProjectPage 的
 * `fileNameOf`。三者对非空路径给出同一结果，属同一意图的平行定义 ——
 * 任何一份改动（例如将来要处理 query 串）都会让同一路径在各处显示成不同文件名。
 */
export function basenameOf(path: string): string {
  return path.split(/[\\/]/).pop() || path
}
