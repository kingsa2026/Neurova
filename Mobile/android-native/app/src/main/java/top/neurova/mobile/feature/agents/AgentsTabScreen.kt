package top.neurova.mobile.feature.agents

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
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
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import top.neurova.mobile.core.model.AgentItem
import top.neurova.mobile.core.model.AgentStatus
import top.neurova.mobile.ui.components.LocalAppRuntime
import top.neurova.mobile.ui.components.PageHeader
import top.neurova.mobile.ui.theme.LocalNeurovaColors

/**
 * F7 智能体列表（智能体 Tab · Agent 中心）：GET /agents 单源（属主过滤）。
 * 点卡片 = 设为当前 Agent 并进对话（当前 Agent 单源在 AgentsStore，聊天头部切换同源）。
 */
@Composable
fun AgentsTabScreen(onOpenChat: () -> Unit) {
    val runtime = LocalAppRuntime.current
    val palette = LocalNeurovaColors.current
    val store = remember { runtime.agents }
    var reloadTick by remember { mutableStateOf(false) }

    LaunchedEffect(reloadTick) { store.load() }

    Column(modifier = Modifier.fillMaxSize()) {
        PageHeader(title = "智能体", subtitle = "Agent 中心")
        Text(
            "${store.agents.size} 个 · ${store.agents.count { AgentStatus.normalize(it.status) == AgentStatus.ACTIVE }} 在线",
            fontSize = 11.5.sp,
            color = palette.textLow,
            modifier = Modifier.padding(horizontal = 20.dp, vertical = 2.dp),
        )
        Spacer(modifier = Modifier.size(10.dp))
        when {
            store.loading -> Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                CircularProgressIndicator(color = palette.accent)
            }
            store.error != null -> Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Text(store.error!!, fontSize = 12.sp, color = palette.danger)
                    Spacer(modifier = Modifier.size(8.dp))
                    Text("点击重试", fontSize = 12.sp, color = palette.accent, modifier = Modifier.clickable {
                        reloadTick = !reloadTick
                    })
                }
            }
            store.agents.isEmpty() -> Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Text("暂无智能体", fontSize = 12.sp, color = palette.textLow)
            }
            else -> LazyColumn(
                modifier = Modifier.fillMaxSize(),
                contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 20.dp, vertical = 4.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                items(store.agents, key = { it.agentId }) { agent ->
                    AgentCard(
                        agent = agent,
                        isCurrent = agent.agentId == store.currentAgentId,
                        onClick = {
                            store.switchAgent(agent.agentId)
                            onOpenChat()
                        },
                    )
                }
            }
        }
    }
}

@Composable
private fun AgentCard(agent: AgentItem, isCurrent: Boolean, onClick: () -> Unit) {
    val palette = LocalNeurovaColors.current
    val shape = RoundedCornerShape(16.dp)
    val status = AgentStatus.normalize(agent.status)
    val statusColor = when (status) {
        AgentStatus.ACTIVE -> palette.success
        AgentStatus.SLEEPING -> palette.warn
        AgentStatus.ERROR -> palette.danger
        AgentStatus.INACTIVE -> palette.textLow
    }
    val statusLabel = when (status) {
        AgentStatus.ACTIVE -> "在线"
        AgentStatus.SLEEPING -> "休眠"
        AgentStatus.ERROR -> "异常"
        AgentStatus.INACTIVE -> "离线"
    }
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(shape)
            .background(palette.glass)
            .border(
                1.dp,
                if (isCurrent) palette.accent.copy(alpha = 0.5f) else palette.glassBorder,
                shape,
            )
            .clickable { onClick() }
            .padding(horizontal = 14.dp, vertical = 13.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            modifier = Modifier
                .size(44.dp)
                .clip(CircleShape)
                .background(palette.brandGradient),
            contentAlignment = Alignment.Center,
        ) {
            Text(
                agent.name.trim().firstOrNull()?.uppercaseChar()?.toString() ?: "N",
                color = androidx.compose.ui.graphics.Color.White,
                fontSize = 16.sp,
                fontWeight = FontWeight.Bold,
            )
        }
        Spacer(modifier = Modifier.width(12.dp))
        Column(modifier = Modifier.weight(1f)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    agent.name,
                    fontSize = 14.5.sp,
                    fontWeight = FontWeight.SemiBold,
                    color = palette.textHi,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f, fill = false),
                )
                Box(
                    modifier = Modifier
                        .padding(start = 6.dp)
                        .size(7.dp)
                        .clip(CircleShape)
                        .background(statusColor),
                )
                Text(
                    statusLabel,
                    fontSize = 10.5.sp,
                    color = statusColor,
                    modifier = Modifier.padding(start = 3.dp),
                )
            }
            if (!agent.description.isNullOrBlank()) {
                Text(
                    agent.description,
                    fontSize = 12.sp,
                    color = palette.textMid,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.padding(top = 2.dp),
                )
            }
            Text(
                buildString {
                    append(agent.model ?: "未知模型")
                    if (agent.toolsCount > 0) append(" · 工具 ${agent.toolsCount}")
                    if (agent.memoryEnabled) append(" · 记忆")
                },
                fontSize = 11.sp,
                color = palette.textLow,
                modifier = Modifier.padding(top = 2.dp),
            )
        }
    }
}
