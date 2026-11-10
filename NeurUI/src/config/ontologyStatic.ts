/**
 * 本体静态目录（仅剩展示用结构图）。
 *
 * - **CQ 追溯矩阵不在本文件**：2026-11-10 撤表，改由读数面供数——
 *   元数据照 specs 票面、status 为服务端探针现值
 *   （`GET /knowledge/ontology/cq-matrix`，名册 `neurova/knowledge/ontology/cq_matrix.py`）。
 *   此前抄的静态表与 specs 票面有转写漂移（testId 丢 ::类名段、query 丢标点），
 *   抄表形态退役；反向守卫见 KnowledgeEvalPage.ontology.test.ts。
 * - **D 组默认关矩阵不在本文件**：项名与现值一律取
 *   `GET /knowledge/observability/default-off`（服务端名册 `neurova/knowledge/defaultOffFlags.py`）。
 *   这里曾抄过一张八行静态表，票面是九项——漏的那一项是 D-03，而抄表那侧的守卫用
 *   `rows.length` 相等自证，漏一行照样绿（2026-11-06 撤表，改由读数面供数）。
 */

/** upper-lite 静态树（与 neurova/knowledge/ontology/upper_lite.py 七类一致；仅展示用）。 */
export const UPPER_LITE_TREE = {
  root: 'Entity',
  children: [
    { label: 'Continuant', children: ['Agent', 'Document', 'Concept'] },
    { label: 'Occurrent', children: ['Event'] },
  ],
}
