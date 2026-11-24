package top.neurova.mobile.feature.chat

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ExpandLess
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.launch
import top.neurova.mobile.R
import top.neurova.mobile.core.model.SwarmCandidate
import top.neurova.mobile.core.model.SwarmCandidateBoard
import top.neurova.mobile.core.model.SwarmGraphNode
import top.neurova.mobile.core.model.SwarmGraphProjection
import top.neurova.mobile.core.model.SwarmStatusTone
import top.neurova.mobile.core.model.SwarmTone
import top.neurova.mobile.ui.components.LocalAppRuntime
import top.neurova.mobile.ui.theme.LocalNeurovaColors
import top.neurova.mobile.ui.theme.NeurovaColors

/**
 * 蜂群协作过程视图（车道G，对齐 PC 端 SwarmFlowPanel.vue）。
 *
 * 数据源：GET /console/chat/runs/{parent_session_id}/graph 与 /candidates
 * （经 ChatRepository.getSwarmRunGraph/getSwarmRunCandidates，Bearer 走既有 HttpChannel）。
 * 服务端只出投影、端上只做渲染（P2-4）：状态着色词汇与 PC 同源
 * （RUN_STATUS_TONE / CANDIDATE_STATUS_TONE / APPROVAL_TONE，见 SwarmStatusTone）。
 *
 * v1 形态（诚实从简）：
 * - 折叠面板：进入（展开）即拉取，支持下拉刷新；不做 WS 增量；
 * - 简化分层拓扑：run 节点按 depth 分层，层间以竖向连线表达委派（spawn），
 *   依赖/委派来源以关系徽标附在节点卡上；审批卡/候选卡挂在源 run 所在层之后；
 * - 候选板独立小节：候选行带状态徽标与冲突计数；
 * - 空态/失败态诚实呈现（失败带重试按钮，不崩、不冒充空数据）。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SwarmFlowPanel(
    parentSessionId: String,
    modifier: Modifier = Modifier,
    /** 展开态由页面持有：浮动图标点击展开，面板头部收起钮回调折叠 */
    expanded: Boolean = false,
    /** 有无协作回告：驱动页面浮动图标显隐（无协作则入口一并不出现） */
    onHasCollabChange: (Boolean) -> Unit = {},
    /** 折叠回调：回到浮动图标形态（对齐鸿蒙端同款交互） */
    onCollapse: () -> Unit = {},
) {
    val runtime = LocalAppRuntime.current
    val palette = LocalNeurovaColors.current
    val scope = rememberCoroutineScope()

    var loading by remember { mutableStateOf(false) }
    var refreshing by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var graph by remember { mutableStateOf<SwarmGraphProjection?>(null) }
    var board by remember { mutableStateOf<SwarmCandidateBoard?>(null) }

    suspend fun load(isRefresh: Boolean) {
        if (parentSessionId.isBlank() || loading) return
        if (isRefresh) refreshing = true else loading = true
        error = null
        runCatching {
            val graphResult = runtime.chatRepo.getSwarmRunGraph(parentSessionId)
            // 候选板尽力而为：graph 成功而 candidates 失败时，图照常出、候选段如实缺席
            val boardResult = runCatching { runtime.chatRepo.getSwarmRunCandidates(parentSessionId) }.getOrNull()
            graphResult to boardResult
        }.onSuccess { (graphResult, boardResult) ->
            graph = graphResult
            board = boardResult
        }.onFailure { e ->
            error = e.message ?: "load failed"
        }
        loading = false
        refreshing = false
    }

    // 会话进入即拉取（不再等展开）：有无协作须先行回告，浮动图标才有的放矢；
    // 先清旧投影再拉（过期响应不写当前视图，对齐 PC 纪律）
    LaunchedEffect(parentSessionId) {
        graph = null
        board = null
        load(isRefresh = false)
    }

    val runCount = graph?.nodes?.count { it.nodeType == "run" } ?: 0
    val cardCount = graph?.nodes?.count { it.nodeType != "run" } ?: 0
    val edgeCount = graph?.edges?.size ?: 0
    val revision = graph?.meta?.revision ?: board?.revision ?: 0
    val hasCollab = swarmHasCollab(runCount, cardCount)
    LaunchedEffect(hasCollab) { onHasCollabChange(hasCollab) }

    // 无协作或折叠态：不绘制本体（浮动图标形态由页面呈现）；组件仍挂载保数据生命周期
    if (!hasCollab || !expanded) {
        return
    }

    Column(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = 14.dp, vertical = 2.dp),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .clip(RoundedCornerShape(12.dp))
                .background(palette.glass)
                .border(1.dp, palette.glassBorder, RoundedCornerShape(12.dp))
                .clickable { onCollapse() }
                .padding(horizontal = 10.dp, vertical = 4.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Box(
                modifier = Modifier
                    .size(7.dp)
                    .clip(CircleShape)
                    .background(palette.accent),
            )
            Spacer(modifier = Modifier.width(6.dp))
            Text(
                stringResource(R.string.swarm_flow_title),
                fontSize = 11.5.sp,
                fontWeight = FontWeight.SemiBold,
                color = palette.textMid,
            )
            Spacer(modifier = Modifier.width(8.dp))
            Box(modifier = Modifier.weight(1f)) {
                if (graph != null) {
                    Text(
                        stringResource(R.string.swarm_flow_summary, runCount, edgeCount, revision),
                        fontSize = 10.5.sp,
                        color = palette.textLow,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
            }
            IconButton(
                onClick = onCollapse,
                modifier = Modifier.size(24.dp),
            ) {
                Icon(
                    imageVector = Icons.Filled.ExpandLess,
                    contentDescription = stringResource(R.string.swarm_flow_toggle),
                    tint = palette.textMid,
                )
            }
        }
        if (expanded) {
            PullToRefreshBox(
                isRefreshing = refreshing,
                onRefresh = { scope.launch { load(isRefresh = true) } },
                modifier = Modifier.fillMaxWidth(),
            ) {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(top = 4.dp, start = 2.dp, end = 2.dp)
                        .heightIn(max = 360.dp)
                        .verticalScroll(rememberScrollState()),
                ) {
                    val currentGraph = graph
                    when {
                        error != null -> SwarmErrorState(
                            message = error.orEmpty(),
                            onRetry = { scope.launch { load(isRefresh = false) } },
                        )
                        loading && currentGraph == null -> Text(
                            stringResource(R.string.swarm_flow_loading),
                            fontSize = 11.sp,
                            color = palette.textLow,
                            modifier = Modifier.fillMaxWidth().padding(vertical = 12.dp),
                        )
                        currentGraph == null || currentGraph.nodes.isEmpty() -> Text(
                            stringResource(R.string.swarm_flow_empty),
                            fontSize = 11.sp,
                            color = palette.textLow,
                            modifier = Modifier.fillMaxWidth().padding(vertical = 12.dp),
                        )
                        else -> SwarmGraphContent(
                            graph = currentGraph,
                            board = board,
                            boardAvailable = board != null,
                            palette = palette,
                        )
                    }
                }
            }
        }
    }
}

// ---------------------------------------------------------------------------
// 图内容：诚实标注 → 图例 → 分层拓扑 → 候选板
// ---------------------------------------------------------------------------

@Composable
private fun SwarmGraphContent(
    graph: SwarmGraphProjection,
    board: SwarmCandidateBoard?,
    boardAvailable: Boolean,
    palette: NeurovaColors,
) {
    val nodes = graph.nodes
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        if (graph.meta.truncated) {
            SwarmHintRow(
                text = stringResource(R.string.swarm_flow_truncated_hint, graph.meta.counts["runNodes"] ?: nodes.size),
                color = palette.warn,
            )
        }
        if (graph.meta.candidatesIncomplete) {
            SwarmHintRow(
                text = stringResource(R.string.swarm_flow_incomplete_hint),
                color = palette.accent,
            )
        }
        SwarmLegendRow(palette)

        val nameById = nodes.associate { it.id to it.memberName }
        val runNodes = nodes.filter { it.nodeType == "run" }
        val cardNodes = nodes.filter { it.nodeType != "run" }
        val depthOfRun = runNodes.associate { it.id to it.depth }
        // child → parent（spawn）：层间连线与"由谁委派"徽标的共同数据源
        val spawnInto = graph.edges.filter { it.type == "spawn" }
            .associate { it.to to it.from }
        val depsInto = graph.edges.filter { it.type == "dependency" }
            .groupBy({ it.to }, { it.from })
        val layers = runNodes.groupBy { it.depth }.toSortedMap()
        val cardsByOwnerDepth = cardNodes.groupBy { card -> depthOfRun[card.runId] ?: 0 }

        var previousDepth: Int? = null
        for ((depth, layerNodes) in layers) {
            val hasSpawnFromPrevious = previousDepth != null && layerNodes.any { child ->
                val parent = spawnInto[child.id]
                parent != null && depthOfRun[parent] == previousDepth
            }
            SwarmLayerConnector(hasSpawnFromPrevious, palette)
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .horizontalScroll(rememberScrollState()),
                horizontalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                layerNodes
                    .sortedWith(compareBy({ it.startedAt }, { it.id }))
                    .forEach { node ->
                        SwarmRunNodeCard(node, spawnInto, depsInto, nameById, palette)
                    }
            }
            cardsByOwnerDepth[depth]?.takeIf { it.isNotEmpty() }?.let { cards ->
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .horizontalScroll(rememberScrollState()),
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    cards.forEach { card -> SwarmCardNode(card, palette) }
                }
            }
            previousDepth = depth
        }

        if (board != null) {
            SwarmCandidateBoardSection(board, palette)
        } else if (!boardAvailable) {
            Text(
                stringResource(R.string.swarm_flow_candidates_unavailable),
                fontSize = 10.sp,
                color = palette.textLow,
                modifier = Modifier.padding(top = 2.dp),
            )
        }
    }
}

// ---------------------------------------------------------------------------
// 节点卡与关系表达
// ---------------------------------------------------------------------------

@Composable
private fun SwarmRunNodeCard(
    node: SwarmGraphNode,
    spawnInto: Map<String, String>,
    depsInto: Map<String, List<String>>,
    nameById: Map<String, String>,
    palette: NeurovaColors,
) {
    val toneColor = swarmToneColor(SwarmStatusTone.fromRunStatus(node.status), palette)
    val parentName = spawnInto[node.id]?.let { nameById[it] }
    val depNames = (depsInto[node.id] ?: emptyList()).mapNotNull { nameById[it] }
    Column(
        modifier = Modifier
            .width(148.dp)
            .clip(RoundedCornerShape(12.dp))
            .background(palette.glassStrong)
            .border(1.dp, toneColor.copy(alpha = 0.55f), RoundedCornerShape(12.dp))
            .padding(horizontal = 9.dp, vertical = 7.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                node.memberName,
                fontSize = 11.5.sp,
                fontWeight = FontWeight.SemiBold,
                color = palette.textHi,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.weight(1f, fill = false),
            )
            if (node.kind == "external") {
                Spacer(modifier = Modifier.width(4.dp))
                SwarmBadge(stringResource(R.string.swarm_flow_external_badge), palette.accent)
            }
        }
        Spacer(modifier = Modifier.height(3.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(
                modifier = Modifier
                    .size(6.dp)
                    .clip(CircleShape)
                    .background(toneColor),
            )
            Spacer(modifier = Modifier.width(4.dp))
            Text(
                node.status,
                fontSize = 10.sp,
                color = toneColor,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Spacer(modifier = Modifier.width(6.dp))
            Text(
                stringResource(R.string.swarm_flow_depth_badge, node.depth),
                fontSize = 9.5.sp,
                color = palette.textLow,
            )
        }
        if (parentName != null) {
            Text(
                stringResource(R.string.swarm_flow_spawned_from, parentName),
                fontSize = 9.5.sp,
                color = palette.textLow,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.padding(top = 2.dp),
            )
        }
        if (depNames.isNotEmpty()) {
            Text(
                stringResource(R.string.swarm_flow_depends_on, depNames.joinToString("、")),
                fontSize = 9.5.sp,
                color = palette.textLow,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.padding(top = 2.dp),
            )
        }
        if (node.errorType.isNotBlank()) {
            Text(
                node.errorType,
                fontSize = 9.5.sp,
                color = palette.danger,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.padding(top = 2.dp),
            )
        }
    }
}

/** 审批卡 / 候选卡（nodeType != run）：状态徽标 + 摘要 + 说明。 */
@Composable
private fun SwarmCardNode(node: SwarmGraphNode, palette: NeurovaColors) {
    val isApproval = node.nodeType == "approval"
    val tone = if (isApproval) {
        SwarmStatusTone.fromApprovalStatus(node.status)
    } else {
        SwarmStatusTone.fromCandidateStatus(node.status)
    }
    val toneColor = swarmToneColor(tone, palette)
    Column(
        modifier = Modifier
            .width(148.dp)
            .clip(RoundedCornerShape(12.dp))
            .background(palette.glass)
            .border(1.dp, toneColor.copy(alpha = 0.55f), RoundedCornerShape(12.dp))
            .padding(horizontal = 9.dp, vertical = 7.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                if (isApproval) {
                    stringResource(R.string.swarm_flow_approval_badge, node.level.ifBlank { "-" })
                } else {
                    stringResource(R.string.swarm_flow_candidate_badge)
                },
                fontSize = 10.sp,
                fontWeight = FontWeight.SemiBold,
                color = palette.textMid,
            )
            Spacer(modifier = Modifier.width(6.dp))
            Text(
                node.status.ifBlank { "pending" },
                fontSize = 9.5.sp,
                color = toneColor,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.weight(1f, fill = false),
            )
        }
        Text(
            node.memberName,
            fontSize = 10.5.sp,
            color = palette.textHi,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.padding(top = 2.dp),
        )
        if (node.note.isNotBlank()) {
            Text(
                node.note,
                fontSize = 9.sp,
                color = palette.textLow,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.padding(top = 2.dp),
            )
        }
    }
}

// ---------------------------------------------------------------------------
// 候选板小节
// ---------------------------------------------------------------------------

@Composable
private fun SwarmCandidateBoardSection(board: SwarmCandidateBoard, palette: NeurovaColors) {
    if (board.candidates.isEmpty() && board.conflicts.isEmpty()) return
    Column(modifier = Modifier.fillMaxWidth().padding(top = 4.dp)) {
        Text(
            stringResource(R.string.swarm_flow_candidates_title, board.revision),
            fontSize = 10.5.sp,
            fontWeight = FontWeight.SemiBold,
            color = palette.textMid,
        )
        board.candidates.forEach { candidate ->
            SwarmCandidateRow(candidate, palette, highlight = false)
        }
        board.conflicts.forEach { conflict ->
            SwarmCandidateRow(conflict, palette, highlight = true)
        }
    }
}

@Composable
private fun SwarmCandidateRow(candidate: SwarmCandidate, palette: NeurovaColors, highlight: Boolean) {
    val toneColor = swarmToneColor(SwarmStatusTone.fromCandidateStatus(candidate.status), palette)
    val label = candidate.artifactKeys.joinToString("、").ifBlank {
        candidate.note.ifBlank { candidate.candidateId }
    }
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(top = 3.dp)
            .clip(RoundedCornerShape(9.dp))
            .background(if (highlight) palette.danger.copy(alpha = 0.08f) else palette.glass)
            .padding(horizontal = 8.dp, vertical = 5.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            modifier = Modifier
                .size(6.dp)
                .clip(CircleShape)
                .background(toneColor),
        )
        Spacer(modifier = Modifier.width(6.dp))
        Text(
            label,
            fontSize = 10.5.sp,
            color = palette.textHi,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.weight(1f, fill = false),
        )
        if (candidate.conflictWith.isNotEmpty()) {
            Spacer(modifier = Modifier.width(6.dp))
            Text(
                stringResource(R.string.swarm_flow_conflict_with, candidate.conflictWith.size),
                fontSize = 9.5.sp,
                color = palette.danger,
            )
        }
        Spacer(modifier = Modifier.width(6.dp))
        SwarmBadge(candidate.status, toneColor)
    }
}

// ---------------------------------------------------------------------------
// 小件：图例 / 连线 / 徽标 / 提示 / 失败态
// ---------------------------------------------------------------------------

@Composable
private fun SwarmLegendRow(palette: NeurovaColors) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        SwarmLegendItem(stringResource(R.string.swarm_flow_legend_spawn), palette.textMid, dashed = false, palette = palette)
        SwarmLegendItem(stringResource(R.string.swarm_flow_legend_dependency), palette.textMid, dashed = true, palette = palette)
        SwarmLegendItem(stringResource(R.string.swarm_flow_legend_approval), palette.warn, dashed = false, palette = palette)
        SwarmLegendItem(stringResource(R.string.swarm_flow_legend_candidate), palette.accent, dashed = false, palette = palette)
    }
}

@Composable
private fun SwarmLegendItem(label: String, color: Color, dashed: Boolean, palette: NeurovaColors) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Canvas(modifier = Modifier.width(16.dp).height(2.dp)) {
            if (dashed) {
                val dash = 3.dp.toPx()
                var x = 0f
                while (x < size.width) {
                    drawLine(
                        color = color,
                        start = Offset(x, 0f),
                        end = Offset(minOf(x + dash, size.width), 0f),
                        strokeWidth = size.height,
                    )
                    x += dash * 2
                }
            } else {
                drawLine(color = color, start = Offset.Zero, end = Offset(size.width, 0f), strokeWidth = size.height)
            }
        }
        Spacer(modifier = Modifier.width(4.dp))
        Text(label, fontSize = 9.5.sp, color = palette.textLow)
    }
}

/** 层间连线：存在跨层 spawn 边时以居中竖线表达委派方向（上层 → 下层）。 */
@Composable
private fun SwarmLayerConnector(hasSpawn: Boolean, palette: NeurovaColors) {
    Box(
        modifier = Modifier.fillMaxWidth().height(12.dp),
        contentAlignment = Alignment.Center,
    ) {
        if (hasSpawn) {
            Box(
                modifier = Modifier
                    .width(2.dp)
                    .height(12.dp)
                    .background(palette.textLow.copy(alpha = 0.45f)),
            )
        }
    }
}

@Composable
private fun SwarmBadge(text: String, color: Color) {
    Text(
        text,
        fontSize = 9.sp,
        color = color,
        maxLines = 1,
        overflow = TextOverflow.Ellipsis,
        modifier = Modifier
            .clip(RoundedCornerShape(8.dp))
            .border(1.dp, color.copy(alpha = 0.6f), RoundedCornerShape(8.dp))
            .padding(horizontal = 5.dp, vertical = 1.dp),
    )
}

@Composable
private fun SwarmHintRow(text: String, color: Color) {
    Text(
        text,
        fontSize = 10.sp,
        color = color,
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(8.dp))
            .background(color.copy(alpha = 0.10f))
            .padding(horizontal = 8.dp, vertical = 4.dp),
    )
}

@Composable
private fun SwarmErrorState(message: String, onRetry: () -> Unit) {
    val palette = LocalNeurovaColors.current
    Column(
        modifier = Modifier.fillMaxWidth().padding(vertical = 10.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text(
            stringResource(R.string.swarm_flow_error),
            fontSize = 11.5.sp,
            color = palette.danger,
        )
        Text(
            message,
            fontSize = 10.sp,
            color = palette.textLow,
            maxLines = 2,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.padding(top = 2.dp),
        )
        TextButton(onClick = onRetry) {
            Text(stringResource(R.string.swarm_flow_retry), fontSize = 12.sp)
        }
    }
}

/** 基调 → 调色板令牌（全站禁硬编码色值，统一走 NeurovaColors）。 */
private fun swarmToneColor(tone: SwarmTone, palette: NeurovaColors): Color = when (tone) {
    SwarmTone.RUNNING -> palette.warn
    SwarmTone.COMPLETED -> palette.success
    SwarmTone.FAILED -> palette.danger
    SwarmTone.WARNING -> palette.warn
}
