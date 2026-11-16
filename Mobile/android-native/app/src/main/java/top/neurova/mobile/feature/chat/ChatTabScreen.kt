package top.neurova.mobile.feature.chat

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
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Star
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Text
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.launch
import top.neurova.mobile.core.model.ChatSessionItem
import top.neurova.mobile.ui.components.LocalAppRuntime
import top.neurova.mobile.ui.components.PageHeader
import top.neurova.mobile.ui.theme.LocalNeurovaColors

/** F4 会话筛选段：全部 / 置顶 / 归档（归档走独立端点，其余客户端过滤同一份记录） */
private enum class SessionSegment(val label: String) {
    ALL("全部"),
    PINNED("置顶"),
    ARCHIVED("归档"),
}

/**
 * F4 会话列表（对话 Tab · 微信式首屏）：与 PC 端同一份会话记录（GET /console/chat/sessions）。
 * 点会话进 F5 聊天页；右上角新建会话；pin 状态取自同一会话记录。
 */
@Composable
fun ChatTabScreen(onOpenSession: (sessionId: String, title: String) -> Unit) {
    val runtime = LocalAppRuntime.current
    val palette = LocalNeurovaColors.current
    val scope = rememberCoroutineScope()
    var segment by remember { mutableStateOf(SessionSegment.ALL) }
    var sessions by remember { mutableStateOf<List<ChatSessionItem>>(emptyList()) }
    var loading by remember { mutableStateOf(false) }
    var errorText by remember { mutableStateOf<String?>(null) }

    suspend fun reload() {
        loading = true
        errorText = null
        runCatching {
            when (segment) {
                SessionSegment.ALL -> runtime.chatRepo.listSessions()
                SessionSegment.PINNED -> runtime.chatRepo.listSessions().filter { it.pinned }
                SessionSegment.ARCHIVED -> runtime.chatRepo.listArchived()
            }
        }.onSuccess { sessions = it }
            .onFailure { errorText = it.message ?: "会话加载失败" }
        loading = false
    }

    LaunchedEffect(segment) { reload() }

    Column(modifier = Modifier.fillMaxSize()) {
        PageHeader(
            title = "对话",
            subtitle = "与 PC 端同源",
            actions = {
                IconButton(
                    onClick = {
                        scope.launch {
                            runCatching { runtime.chatRepo.createSession() }
                                .onSuccess { newId -> onOpenSession(newId, "新对话") }
                                .onFailure { errorText = it.message ?: "建会话失败" }
                        }
                    },
                ) {
                    Icon(Icons.Filled.Add, contentDescription = "新建会话", tint = palette.textHi)
                }
            },
        )
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 20.dp, vertical = 4.dp),
            horizontalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            SessionSegment.entries.forEach { candidate ->
                val selected = candidate == segment
                Text(
                    candidate.label,
                    fontSize = 12.sp,
                    fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Normal,
                    color = if (selected) palette.textHi else palette.textMid,
                    modifier = Modifier
                        .clip(RoundedCornerShape(999.dp))
                        .background(if (selected) palette.accent.copy(alpha = 0.25f) else palette.glass)
                        .border(
                            1.dp,
                            if (selected) palette.accent.copy(alpha = 0.6f) else palette.glassBorder,
                            RoundedCornerShape(999.dp),
                        )
                        .clickable { segment = candidate }
                        .padding(horizontal = 14.dp, vertical = 6.dp),
                )
            }
        }
        Spacer(modifier = Modifier.size(10.dp))
        when {
            loading -> Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                CircularProgressIndicator(color = palette.accent)
            }
            errorText != null -> Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Text(errorText!!, fontSize = 12.sp, color = palette.danger)
                    Spacer(modifier = Modifier.size(8.dp))
                    Text("下拉重试", fontSize = 12.sp, color = palette.accent, modifier = Modifier.clickable {
                        scope.launch { reload() }
                    })
                }
            }
            sessions.isEmpty() -> Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Text(
                    if (segment == SessionSegment.ARCHIVED) "暂无归档会话" else "暂无会话，点右上角新建",
                    fontSize = 12.sp,
                    color = palette.textLow,
                )
            }
            else -> LazyColumn(
                modifier = Modifier.fillMaxSize(),
                contentPadding = androidx.compose.foundation.layout.PaddingValues(
                    horizontal = 20.dp,
                    vertical = 4.dp,
                ),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                items(sessions, key = { it.id }) { session ->
                    SessionRow(
                        session = session,
                        onClick = {
                            if (segment == SessionSegment.ARCHIVED) {
                                // 归档会话先恢复再进入
                                scope.launch {
                                    runCatching { runtime.chatRepo.unarchive(session.id) }
                                    reload()
                                    onOpenSession(session.id, session.title)
                                }
                            } else {
                                onOpenSession(session.id, session.title)
                            }
                        },
                    )
                }
            }
        }
    }
}

@Composable
private fun SessionRow(session: ChatSessionItem, onClick: () -> Unit) {
    val palette = LocalNeurovaColors.current
    val shape = RoundedCornerShape(15.dp)
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(shape)
            .background(palette.glass)
            .border(
                1.dp,
                if (session.pinned) palette.accent.copy(alpha = 0.4f) else palette.glassBorder,
                shape,
            )
            .clickable { onClick() }
            .padding(horizontal = 14.dp, vertical = 13.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        AgentGlyph(agentId = session.agentId)
        Spacer(modifier = Modifier.width(12.dp))
        Column(modifier = Modifier.weight(1f)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    session.title,
                    fontSize = 14.5.sp,
                    fontWeight = FontWeight.SemiBold,
                    color = palette.textHi,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f, fill = false),
                )
                if (session.pinned) {
                    Icon(
                        Icons.Filled.Star,
                        contentDescription = "置顶",
                        tint = palette.accent,
                        modifier = Modifier.padding(start = 5.dp).size(12.dp),
                    )
                }
            }
            Spacer(modifier = Modifier.size(3.dp))
            Text(
                session.agentId.ifBlank { "default" },
                fontSize = 12.sp,
                color = palette.textMid,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
        Spacer(modifier = Modifier.width(8.dp))
        Text(formatSessionTime(session.updatedAt), fontSize = 10.5.sp, color = palette.textLow)
    }
}
