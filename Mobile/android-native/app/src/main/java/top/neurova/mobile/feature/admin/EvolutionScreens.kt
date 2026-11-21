package top.neurova.mobile.feature.admin

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import top.neurova.mobile.core.model.EvolutionGeneration
import top.neurova.mobile.core.model.EvolutionGenerationSummary
import top.neurova.mobile.core.model.EvolutionVerdict
import top.neurova.mobile.core.net.ChannelHttpException
import top.neurova.mobile.ui.components.LocalAppRuntime
import top.neurova.mobile.ui.theme.LocalNeurovaColors
import top.neurova.mobile.ui.theme.NeurovaColors

/**
 * P1-8 演化状态只读页（管理员域；端点与 PC RsiGovernancePage 世代区块同源）：
 * - 当前基线代（#序号/状态/晋升时间/基线 commit；404 如实说"尚无"，不拿最大序号充数）；
 * - 最近世代列表（状态徽标，limit 10）；
 * - 最近一代门禁结果摘要（G0-G4 三态：通过/未过/无证据 分色分文不折叠 + 裁决 + 金丝雀结论/回滚落点）。
 * 范围纪律（P1-8）：移动端只读——审批/参数修改等写面留在 PC 治理页。
 * 诚实纪律（教义第 2 条）：503 未装配/404 无基线代按后端原因原文展示，不折成空列表冒充正常。
 */
@Composable
fun AdminEvolutionScreen(onBack: () -> Unit) = AdminGate(title = "演化状态", onBack = onBack) {
    val runtime = LocalAppRuntime.current
    val palette = LocalNeurovaColors.current
    var baseline by remember { mutableStateOf<EvolutionGeneration?>(null) }
    var baselineNote by remember { mutableStateOf("") }
    var generations by remember { mutableStateOf<List<EvolutionGenerationSummary>>(emptyList()) }
    var latestDetail by remember { mutableStateOf<EvolutionGeneration?>(null) }
    var errorText by remember { mutableStateOf<String?>(null) }
    var loading by remember { mutableStateOf(false) }

    LaunchedEffect(Unit) {
        loading = true
        runCatching { runtime.evolutionRepo.generations(10) }
            .onSuccess {
                generations = it.generations
                // 门禁结果摘要挂最近一代（列表首项 = 最新代）
                if (it.generations.isNotEmpty()) {
                    runCatching { runtime.evolutionRepo.generationDetail(it.generations.first().generationNo) }
                        .onSuccess { detail -> latestDetail = detail }
                }
            }
            .onFailure { errorText = it.message ?: "世代列表加载失败" }
        // 当前基线代：404 是诚实事实（尚无 deployed 代），单独呈现，不当错误横幅
        runCatching { runtime.evolutionRepo.currentBaseline() }
            .onSuccess { baseline = it }
            .onFailure {
                baseline = null
                baselineNote = (it as? ChannelHttpException)?.detail
                    ?: it.message
                    ?: "尚无已部署的生产基线代"
            }
        loading = false
    }

    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(horizontal = 20.dp, vertical = 4.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        item(key = "baseline-title") { SectionLabel("当前基线代") }
        item(key = "baseline") {
            GlassCard {
                if (baseline != null) {
                    val gen = baseline!!
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(
                            "#${gen.generationNo}",
                            fontSize = 20.sp,
                            fontWeight = FontWeight.Bold,
                            color = palette.textHi,
                        )
                        Spacer(modifier = Modifier.size(10.dp))
                        StatusBadge(text = statusLabel(gen.status), tone = statusColor(gen.status, palette))
                    }
                    if (gen.deployment?.promotedAt?.isNotBlank() == true) {
                        MetaLine("晋升时间：${gen.deployment.promotedAt}")
                    }
                    if (gen.basisCommit.isNotBlank()) {
                        MetaLine("基线 commit：${gen.basisCommit}")
                    }
                } else {
                    Text(
                        if (loading) "加载中…" else baselineNote.ifBlank { "尚无已部署的生产基线代" },
                        fontSize = 12.5.sp,
                        color = palette.textLow,
                    )
                }
            }
        }

        item(key = "gens-title") { SectionLabel("最近世代") }
        item(key = "gens") {
            GlassCard {
                when {
                    errorText != null -> Text(
                        "世代读面不可用：$errorText",
                        fontSize = 12.5.sp,
                        color = palette.danger,
                    )
                    generations.isEmpty() -> Text(
                        if (loading) "加载中…" else "没有世代记录（账本空；这与\"未装配\"是两回事）",
                        fontSize = 12.5.sp,
                        color = palette.textLow,
                    )
                    else -> Column {
                        generations.forEachIndexed { index, gen ->
                            Row(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(vertical = 9.dp),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Text(
                                    "#${gen.generationNo}" + (gen.parentNo?.let { " ← #$it" } ?: ""),
                                    fontSize = 13.sp,
                                    fontWeight = FontWeight.Medium,
                                    color = palette.textHi,
                                    modifier = Modifier.weight(1f),
                                )
                                StatusBadge(
                                    text = statusLabel(gen.status),
                                    tone = statusColor(gen.status, palette),
                                )
                                Spacer(modifier = Modifier.size(8.dp))
                                Text(
                                    gen.promotedAt.ifBlank { "—" },
                                    fontSize = 10.5.sp,
                                    color = palette.textLow,
                                    maxLines = 1,
                                )
                            }
                            if (index < generations.lastIndex) {
                                Box(
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .size(width = 0.dp, height = 1.dp)
                                        .background(palette.glassBorder),
                                )
                            }
                        }
                        Spacer(modifier = Modifier.size(6.dp))
                        Text(
                            "写面（审批/参数修改）在 PC 治理页完成，本页只读",
                            fontSize = 9.5.sp,
                            color = palette.textLow,
                        )
                    }
                }
            }
        }

        item(key = "verdicts-title") { SectionLabel("门禁结果摘要（最近一代）") }
        item(key = "verdicts") {
            GlassCard {
                val detail = latestDetail
                if (detail == null) {
                    Text(
                        if (errorText != null) "无最近一代可读" else if (loading) "加载中…" else "暂无门禁读数",
                        fontSize = 12.5.sp,
                        color = palette.textLow,
                    )
                } else {
                    Column {
                        orderedVerdictKeys(detail.verdicts).forEach { key ->
                            val verdict = detail.verdicts[key] ?: return@forEach
                            Row(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(vertical = 8.dp),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Text(key, fontSize = 12.5.sp, color = palette.textMid, modifier = Modifier.weight(1f))
                                if (verdict.reason.isNotBlank()) {
                                    Text(
                                        verdict.reason,
                                        fontSize = 10.5.sp,
                                        color = palette.textLow,
                                        maxLines = 1,
                                        modifier = Modifier.padding(end = 8.dp),
                                    )
                                }
                                StatusBadge(text = verdictLabel(verdict.state), tone = verdictColor(verdict.state, palette))
                            }
                        }
                        Spacer(modifier = Modifier.size(6.dp))
                        val decision = detail.decision
                        Text(
                            "裁决：" + when {
                                decision == null -> "未裁决"
                                decision.kind == "approval" ->
                                    "人工审批" + (decision.approver.takeIf { it.isNotBlank() }?.let { " · $it" } ?: "")
                                decision.kind == "rejected" ->
                                    "已否决" + (decision.reason.takeIf { it.isNotBlank() }?.let { " · $it" } ?: "")
                                decision.kind == "auto" -> "自动"
                                else -> decision.kind
                            },
                            fontSize = 11.5.sp,
                            color = palette.textMid,
                        )
                        val deployment = detail.deployment
                        if (deployment?.canaryConclusion?.isNotBlank() == true) {
                            Text(
                                "金丝雀结论：${deployment.canaryConclusion}",
                                fontSize = 11.5.sp,
                                color = palette.textMid,
                            )
                        }
                        val rolledBackTo = deployment?.rolledBackTo
                        if (rolledBackTo != null) {
                            Text(
                                "已回滚至世代 #$rolledBackTo",
                                fontSize = 11.5.sp,
                                color = palette.danger,
                            )
                        }
                    }
                }
            }
        }
    }
}

/** 门禁键规范序（g0..g4）在前、非规范键诚实追在后 */
private fun orderedVerdictKeys(verdicts: Map<String, EvolutionVerdict>): List<String> {
    val canonical = listOf("g0", "g1", "g2", "g3", "g4").filter { verdicts.containsKey(it) }
    val extras = verdicts.keys.filter { !canonical.contains(it) }.sorted()
    return canonical + extras
}

/** 世代状态 → 中文标签（未知值诚实保留原值） */
private fun statusLabel(status: String): String = when (status) {
    "proposed" -> "已立案"
    "shadowTesting" -> "影子验证中"
    "gated" -> "门禁完成"
    "canary" -> "金丝雀观测中"
    "deployed" -> "已部署"
    "rejected" -> "已拒绝"
    "rolledBack" -> "已回滚"
    else -> status
}

/** 世代状态 → 徽标色（deployed 绿 / 观测中黄 / 终态败红 / 其余中性） */
private fun statusColor(status: String, palette: NeurovaColors): Color = when (status) {
    "deployed" -> palette.success
    "canary", "shadowTesting" -> palette.warn
    "rejected", "rolledBack" -> palette.danger
    else -> palette.textLow
}

/** 门禁三态 → 中文标签（unevidenced 与 failed 分文——"没证据"不冒充"未过"） */
private fun verdictLabel(state: String): String = when (state) {
    "passed" -> "通过"
    "failed" -> "未过"
    else -> "无证据"
}

/** 门禁三态 → 徽标色 */
private fun verdictColor(state: String, palette: NeurovaColors): Color = when (state) {
    "passed" -> palette.success
    "failed" -> palette.danger
    else -> palette.warn
}

@Composable
private fun SectionLabel(text: String) {
    Text(
        text,
        fontSize = 12.sp,
        fontWeight = FontWeight.SemiBold,
        color = LocalNeurovaColors.current.textLow,
        modifier = Modifier.padding(top = 8.dp),
    )
}

@Composable
private fun GlassCard(content: @Composable () -> Unit) {
    val palette = LocalNeurovaColors.current
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(16.dp))
            .background(palette.glass)
            .border(1.dp, palette.glassBorder, RoundedCornerShape(16.dp))
            .padding(horizontal = 15.dp, vertical = 12.dp),
    ) {
        content()
    }
}

/** 三态/状态徽标（10% 同色底 + 同色文字，对齐 PC a-tag 语义） */
@Composable
private fun StatusBadge(text: String, tone: Color) {
    val palette = LocalNeurovaColors.current
    Box(
        modifier = Modifier
            .clip(RoundedCornerShape(999.dp))
            .background(tone.copy(alpha = 0.12f))
            .border(1.dp, tone.copy(alpha = 0.3f), RoundedCornerShape(999.dp))
            .padding(horizontal = 9.dp, vertical = 2.dp),
    ) {
        Text(text, fontSize = 10.sp, fontWeight = FontWeight.Medium, color = tone)
    }
}

/** 卡内次级说明行 */
@Composable
private fun MetaLine(text: String) {
    Text(text, fontSize = 11.5.sp, color = LocalNeurovaColors.current.textLow)
}
