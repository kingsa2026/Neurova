package top.neurova.mobile.feature.workbench

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.CircularProgressIndicator
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import top.neurova.mobile.core.model.WorkbenchStats
import top.neurova.mobile.ui.components.LocalAppRuntime
import top.neurova.mobile.ui.components.PageHeader
import top.neurova.mobile.ui.theme.LocalNeurovaColors

/**
 * F3 工作台（仪表盘 · 真数据）：GET /home/data 裸 dict（无信封），
 * 与 PC DashboardPage / 鸿蒙 DashboardPage 同一份汇总读数。
 */
@Composable
fun WorkbenchTabScreen() {
    val runtime = LocalAppRuntime.current
    val palette = LocalNeurovaColors.current
    var stats by remember { mutableStateOf<WorkbenchStats?>(null) }
    var loading by remember { mutableStateOf(false) }
    var errorText by remember { mutableStateOf<String?>(null) }
    var reloadTick by remember { mutableStateOf(false) }

    LaunchedEffect(reloadTick) {
        loading = true
        errorText = null
        runCatching { runtime.http.getJson("/home/data") }
            .onSuccess { stats = WorkbenchStats.fromHomeData(it) }
            .onFailure { errorText = it.message ?: "仪表盘加载失败" }
        loading = false
    }

    Column(modifier = Modifier.fillMaxSize()) {
        PageHeader(title = "工作台", subtitle = "仪表盘 · 真数据")
        when {
            loading && stats == null -> Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                CircularProgressIndicator(color = palette.accent)
            }
            errorText != null -> Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Text(errorText!!, fontSize = 12.sp, color = palette.danger)
                    Spacer(modifier = Modifier.size(8.dp))
                    Text("点击重试", fontSize = 12.sp, color = palette.accent, modifier = Modifier.clickable {
                        reloadTick = !reloadTick
                    })
                }
            }
            else -> {
                stats?.welcomeMessage?.takeIf { it.isNotBlank() }?.let {
                    Text(
                        it,
                        fontSize = 13.sp,
                        color = palette.textMid,
                        modifier = Modifier.padding(horizontal = 20.dp, vertical = 4.dp),
                    )
                }
                StatsGrid(stats = stats ?: WorkbenchStats("", 0, 0, 0, 0L, 0, 0))
            }
        }
    }
}

@Composable
private fun StatsGrid(stats: WorkbenchStats) {
    val palette = LocalNeurovaColors.current
    val cards = listOf(
        "智能体" to stats.agentCount.toLong(),
        "会话" to stats.conversationCount.toLong(),
        "记忆" to stats.memoryCount.toLong(),
        "LLM 调用" to stats.llmCallCount.toLong(),
        "插件" to stats.pluginCount.toLong(),
    )
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(horizontal = 20.dp, vertical = 8.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        cards.chunked(2).forEach { rowCards ->
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                rowCards.forEach { (label, value) ->
                    val shape = RoundedCornerShape(16.dp)
                    Column(
                        modifier = Modifier
                            .weight(1f)
                            .aspectRatio(1.6f)
                            .clip(shape)
                            .background(palette.glass)
                            .border(1.dp, palette.glassBorder, shape)
                            .padding(14.dp),
                        verticalArrangement = Arrangement.Center,
                    ) {
                        Text(
                            formatCount(value),
                            fontSize = 24.sp,
                            fontWeight = FontWeight.Bold,
                            color = palette.textHi,
                        )
                        Text(label, fontSize = 11.5.sp, color = palette.textLow)
                    }
                }
                if (rowCards.size == 1) Spacer(modifier = Modifier.weight(1f))
            }
        }
        Row {
            val shape = RoundedCornerShape(16.dp)
            Column(
                modifier = Modifier
                    .weight(1f)
                    .clip(shape)
                    .background(palette.glass)
                    .border(1.dp, palette.glassBorder, shape)
                    .padding(14.dp),
            ) {
                Text(formatCount(stats.tokenConsumption), fontSize = 24.sp, fontWeight = FontWeight.Bold, color = palette.textHi)
                Text("Token 消耗", fontSize = 11.5.sp, color = palette.textLow)
            }
        }
    }
}

private fun formatCount(value: Long): String = when {
    value >= 1_000_000 -> "%.1fM".format(value / 1_000_000.0)
    value >= 1_000 -> "%.1fk".format(value / 1_000.0)
    else -> value.toString()
}
