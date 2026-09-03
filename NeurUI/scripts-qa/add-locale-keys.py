# -*- coding: utf-8 -*-
"""为 11 个语言包补充前端巡检发现的缺失键（与 zh-CN 键集严格对齐）。"""
import io, os, re

LOCALES_DIR = os.path.join('src', 'i18n', 'locales')

ZH = {
    'chat': {
        'retrievalUnified': '统一检索',
        'retrievalMoE': 'MoE 专家路由',
        'retrievalCache': '缓存检索',
        'retrievalFallback': '兜底检索',
        'retrievalStatus': '记忆检索中（{name}）…',
        'retrievalDone': '{name} 完成：命中 {count} 条 ({ms}ms)',
        'retrievalError': '{name} 检索异常，降级下一通道…',
        'retrievalExpert': 'MoE 专家路由：激活 {n} 个专家',
        'retrievalSemanticFallback': '全库语义兜底：命中 {count} 条',
        'retrievalExpertDone': '专家检索完成：{count} 条',
    },
    'memory': {
        'categoryEpisodic': '情景记忆',
        'categorySemantic': '语义记忆',
        'hot': '🔥 热点',
        'crystallized': '💎 结晶',
        'shortTerm': '短期记忆',
        'jsonData': 'JSON 数据',
        'mergeMode': '合并模式',
        'mergeSkip': '跳过',
        'mergeOverwrite': '覆盖',
        'mergeMerge': '合并',
    },
    'experience': {
        'taskType': '任务类型',
        'outcomeSuccess': '成功',
        'outcomeFailure': '失败',
        'outcomePartial': '部分成功',
        'addLessons': '添加经验教训',
    },
    'common': {
        'markAllRead': '全部标记已读',
        'markRead': '标记已读',
    },
    'channel': {
        'disconnected': '已断开',
    },
    'canvas': {
        'aiDesign': 'AI 画布设计',
        'workflowIdLabel': '目标工作流 ID',
        'inputMappingLabel': '入参映射（JSON）',
        'designFailed': '设计失败，请尝试换一种描述',
        'generateSuccess': '已生成 {nodes} 个节点、{edges} 条连线（{name}），已应用到画布，可保存后执行。',
        'generateFailed': '生成失败: {error}',
        'nodeConfigError': '节点配置异常，已停止执行',
        'unknownError': '未知错误',
    },
    'collab': {
        'webhooks': 'Webhook 集成',
        'sessionsync': '会话同步',
        'neuron': 'NEURON 图谱',
    },
    'health': {
        'lastChecked': '上次检查: ',
        'response': '响应: ',
        'recover': '恢复',
        'allOperational': '全部系统运行正常',
        'someDegraded': '部分系统降级',
        'systemIssues': '检测到系统问题',
        'checksSummary': '{checks} 项检查 · {healthy} 项健康 · {issues} 项问题',
    },
}

EN = {
    'chat': {
        'retrievalUnified': 'Unified Retrieval',
        'retrievalMoE': 'MoE Router',
        'retrievalCache': 'Cache Retrieval',
        'retrievalFallback': 'Fallback Retrieval',
        'retrievalStatus': 'Retrieving memories ({name})…',
        'retrievalDone': '{name} done: {count} hit ({ms}ms)',
        'retrievalError': '{name} failed, falling back…',
        'retrievalExpert': 'MoE routing: {n} experts active',
        'retrievalSemanticFallback': 'Semantic fallback: {count} hit',
        'retrievalExpertDone': 'Expert retrieval done: {count} hit',
    },
    'memory': {
        'categoryEpisodic': 'Episodic',
        'categorySemantic': 'Semantic',
        'hot': '🔥 Hot',
        'crystallized': '💎 Crystallized',
        'shortTerm': 'Short Term',
        'jsonData': 'JSON Data',
        'mergeMode': 'Merge Mode',
        'mergeSkip': 'Skip',
        'mergeOverwrite': 'Overwrite',
        'mergeMerge': 'Merge',
    },
    'experience': {
        'taskType': 'Task type',
        'outcomeSuccess': 'Success',
        'outcomeFailure': 'Failure',
        'outcomePartial': 'Partial',
        'addLessons': 'Add lessons learned',
    },
    'common': {
        'markAllRead': 'Mark all read',
        'markRead': 'Mark read',
    },
    'channel': {
        'disconnected': 'Disconnected',
    },
    'canvas': {
        'aiDesign': 'AI Canvas Designer',
        'workflowIdLabel': 'Target workflow ID',
        'inputMappingLabel': 'Input mapping (JSON)',
        'designFailed': 'Design failed, try a different description',
        'generateSuccess': 'Generated {nodes} nodes, {edges} edges ({name}); applied to canvas — save and run when ready.',
        'generateFailed': 'Generation failed: {error}',
        'nodeConfigError': 'Node config error, execution stopped',
        'unknownError': 'Unknown error',
    },
    'collab': {
        'webhooks': 'Webhooks',
        'sessionsync': 'Session Sync',
        'neuron': 'NEURON Graph',
    },
    'health': {
        'lastChecked': 'Last checked: ',
        'response': 'Response: ',
        'recover': 'Recover',
        'allOperational': 'All Systems Operational',
        'someDegraded': 'Some Systems Degraded',
        'systemIssues': 'System Issues Detected',
        'checksSummary': '{checks} checks · {healthy} healthy · {issues} issues',
    },
}

def find_ns_open(lines, ns):
    pat = re.compile(r'^  %s: \{$' % ns)
    return [i for i, l in enumerate(lines) if pat.match(l)]

def find_ns_end(lines, open_idx):
    """返回命名空间内容结束行（下一个顶层 '  x: {' 或文件尾）。"""
    for i in range(open_idx + 1, len(lines)):
        m = re.match(r'^  (\w+): \{', lines[i])
        if m:
            return i
    return len(lines)

files = [f for f in os.listdir(LOCALES_DIR) if not f.startswith('_') and f.endswith('.ts')]
for fname in sorted(files):
    path = os.path.join(LOCALES_DIR, fname)
    with io.open(path, encoding='utf-8') as fh:
        text = fh.read()
    lang = fname[:-3]
    values = EN if lang == 'en-US' else ZH
    lines = text.split('\n')
    # keep track of edited lines (insertions shift indices)
    for ns, keys in values.items():
        found = find_ns_open(lines, ns)
        if not found:
            print('WARN: ns %s missing in %s' % (ns, fname))
            continue
        idx = found[-1] + 1
        ns_end = find_ns_end(lines, found[-1])
        insert = []
        for k, v in keys.items():
            # skip if key already exists inside that ns (dupe safety)
            if any(line.strip().startswith(k + ':') for line in lines[idx:ns_end]):
                continue
            insert.append("    %s: '%s'," % (k, v))
        if insert:
            lines[idx:idx] = insert
    with io.open(path, 'w', encoding='utf-8', newline='') as fh:
        fh.write('\n'.join(lines) + '\n')
    print('patched', fname)
print('done')
