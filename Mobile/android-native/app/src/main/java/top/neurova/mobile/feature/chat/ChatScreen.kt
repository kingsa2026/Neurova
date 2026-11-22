package top.neurova.mobile.feature.chat

import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
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
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.Send
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material.icons.filled.Star
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.launch
import top.neurova.mobile.core.model.ChatMessage
import top.neurova.mobile.core.model.ChatSessionItem
import top.neurova.mobile.core.net.MobileWsChannel
import top.neurova.mobile.ui.components.LocalAppRuntime
import top.neurova.mobile.ui.theme.LocalNeurovaColors

/**
 * F5 聊天页（流式进行中）+ F6 会话抽屉：
 * - 事件经配对 WS 通道（ChatSessionController），历史经 REST 同源回放；
 * - 流式光标 / 停止按钮与 PC ChatPage 同构；
 * - 抽屉从右上角呼出：跨会话搜索 + 重命名/置顶/归档/fork/删除（与 PC 会话侧栏同一组端点）。
 */
@Composable
fun ChatScreen(sessionId: String, initialTitle: String, onBack: () -> Unit, showBack: Boolean = true) {
    val runtime = LocalAppRuntime.current
    val palette = LocalNeurovaColors.current
    val controller = remember { runtime.chatSessions }
    var drawerOpen by remember { mutableStateOf(false) }
    var input by remember { mutableStateOf("") }

    LaunchedEffect(sessionId, initialTitle) {
        runtime.agents.load()
        controller.enter(sessionId, initialTitle)
        if (controller.agentId.isBlank()) controller.useAgent(runtime.agents.currentAgentId)
    }
    androidx.compose.runtime.DisposableEffect(Unit) { onDispose { controller.leave() } }

    Box(modifier = Modifier.fillMaxSize()) {
        Column(modifier = Modifier.fillMaxSize()) {
            ChatHeader(
                title = controller.sessionTitle.ifBlank { "会话" },
                agentId = controller.agentId,
                agents = runtime.agents.agents,
                generating = controller.isGenerating,
                wsState = runtime.ws.state.value,
                showBack = showBack,
                onBack = onBack,
                onOpenDrawer = { drawerOpen = true },
                onSwitchAgent = { target ->
                    runtime.agents.switchAgent(target)
                    controller.useAgent(target)
                },
            )
            TurnProgressStrip(
                queuePosition = controller.queuePosition,
                queueReason = controller.queueReason,
                reasoningSnippet = controller.reasoningSnippet,
                generating = controller.isGenerating,
                chunkCount = controller.chunkCount,
            )
            // 车道G：蜂群协作过程视图，挂在会话进度条正下方（同一运行详情区）
            SwarmFlowPanel(parentSessionId = sessionId)
            Box(modifier = Modifier.weight(1f).fillMaxWidth(), contentAlignment = Alignment.TopCenter) {
                val listState = rememberLazyListState()
                LaunchedEffect(controller.messages.size) {
                    if (controller.messages.isNotEmpty()) listState.animateScrollToItem(controller.messages.size - 1)
                }
                LazyColumn(
                    state = listState,
                    modifier = Modifier
                        .widthIn(max = 720.dp)
                        .fillMaxWidth()
                        .padding(horizontal = 18.dp, vertical = 14.dp),
                    verticalArrangement = Arrangement.spacedBy(14.dp),
                ) {
                    items(controller.messages, key = { it.id }) { message -> MessageBubble(message) }
                    if (controller.messages.isEmpty() && !controller.historyLoading) {
                        item {
                            Text(
                                "发条消息开始这段对话",
                                fontSize = 12.sp,
                                color = palette.textLow,
                                modifier = Modifier.fillMaxWidth(),
                            )
                        }
                    }
                }
            }
            // U1/U6 确认与审批卡：needs_host_confirmation / pending_approval 到达即内联弹出
            controller.hostConfirmation?.let { card ->
                Column(modifier = Modifier.padding(horizontal = 18.dp, vertical = 4.dp)) {
                    HostKeyConfirmCard(
                        card = card,
                        acting = controller.cardActing,
                        error = controller.cardError,
                        onConfirm = { controller.confirmHostKey() },
                        onDismiss = { controller.dismissHostKey() },
                    )
                }
            }
            controller.approval?.let { card ->
                Column(modifier = Modifier.padding(horizontal = 18.dp, vertical = 4.dp)) {
                    ApprovalCardView(
                        card = card,
                        acting = controller.cardActing,
                        error = controller.cardError,
                        onApprove = { controller.approvePending() },
                        onReject = { controller.rejectPending() },
                    )
                }
            }
            controller.sendError?.let { message ->
                Text(
                    message,
                    fontSize = 12.sp,
                    color = palette.danger,
                    modifier = Modifier.padding(horizontal = 18.dp, vertical = 2.dp),
                )
            }
            ChatInputBar(
                text = input,
                onTextChange = { input = it },
                generating = controller.isGenerating,
                onSend = {
                    controller.send(input)
                    input = ""
                },
                onCancel = { controller.cancel() },
            )
        }
        if (drawerOpen) {
            SessionDrawer(
                currentSessionId = sessionId,
                onClose = { drawerOpen = false },
                onSwitchSession = { target, title ->
                    drawerOpen = false
                    runtime.scope.launch { controller.enter(target, title) }
                },
            )
        }
    }
}

@Composable
private fun ChatHeader(
    title: String,
    agentId: String,
    agents: List<top.neurova.mobile.core.model.AgentItem>,
    generating: Boolean,
    wsState: MobileWsChannel.State,
    showBack: Boolean,
    onBack: () -> Unit,
    onOpenDrawer: () -> Unit,
    onSwitchAgent: (String) -> Unit,
) {
    val palette = LocalNeurovaColors.current
    val statusText = when {
        generating -> "正在生成"
        wsState == MobileWsChannel.State.AUTHED -> "已连接"
        wsState == MobileWsChannel.State.CONNECTING ||
            wsState == MobileWsChannel.State.RECONNECTING ||
            wsState == MobileWsChannel.State.REAUTHING -> "连接中"
        else -> "通道未连接"
    }
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .statusBarsPadding()
            .padding(start = 8.dp, end = 16.dp, top = 6.dp, bottom = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (showBack) {
            IconButton(onClick = onBack) {
                Icon(Icons.Filled.ArrowBack, contentDescription = "返回", tint = palette.textHi)
            }
        } else {
            Spacer(modifier = Modifier.width(48.dp))
        }
        Column(modifier = Modifier.weight(1f)) {
            Text(title, fontSize = 15.sp, fontWeight = FontWeight.Bold, color = palette.textHi)
            var switcherOpen by remember { mutableStateOf(false) }
            Box {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    modifier = Modifier.clickable { if (agents.isNotEmpty()) switcherOpen = true },
                ) {
                    Box(
                        modifier = Modifier
                            .size(7.dp)
                            .clip(androidx.compose.foundation.shape.CircleShape)
                            .background(if (generating) palette.success else palette.textLow),
                    )
                    Spacer(modifier = Modifier.width(6.dp))
                    Text(
                        "${agentId.ifBlank { "default" }} · $statusText ▾",
                        fontSize = 11.sp,
                        color = palette.textLow,
                    )
                }
                DropdownMenu(expanded = switcherOpen, onDismissRequest = { switcherOpen = false }) {
                    agents.forEach { agent ->
                        DropdownMenuItem(
                            text = { Text("${agent.name}（${agent.agentId}）") },
                            onClick = {
                                switcherOpen = false
                                onSwitchAgent(agent.agentId)
                            },
                        )
                    }
                }
            }
        }
        IconButton(onClick = onOpenDrawer) {
            Icon(Icons.Filled.MoreVert, contentDescription = "会话抽屉", tint = palette.textMid)
        }
    }
}

/** 会话进度条（P9+ 运行态透明化）：排队位 → 思考流 → 生成进度，全部来自真实运行态事件 */
@Composable
private fun TurnProgressStrip(
    queuePosition: Int?,
    queueReason: String?,
    reasoningSnippet: String?,
    generating: Boolean,
    chunkCount: Int,
) {
    val palette = LocalNeurovaColors.current
    val label = when {
        queuePosition != null -> "排队中 · 第 ${queuePosition + 1} 位"
        queueReason != null -> "排队中 · $queueReason"
        reasoningSnippet != null -> "思考中 · $reasoningSnippet"
        generating -> "生成中 · 已接收 $chunkCount 段"
        else -> return
    }
    val color = when {
        queuePosition != null || queueReason != null -> palette.warn
        reasoningSnippet != null -> palette.accent
        else -> palette.success
    }
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 20.dp, vertical = 2.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            modifier = Modifier
                .size(7.dp)
                .clip(CircleShape)
                .background(color),
        )
        Spacer(modifier = Modifier.width(6.dp))
        Text(
            label,
            fontSize = 11.sp,
            color = palette.textMid,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

@Composable
private fun MessageBubble(message: ChatMessage) {
    val palette = LocalNeurovaColors.current
    val isUser = message.role == "user"
    val shape = if (isUser) {
        RoundedCornerShape(topStart = 16.dp, topEnd = 16.dp, bottomStart = 16.dp, bottomEnd = 6.dp)
    } else {
        RoundedCornerShape(topStart = 16.dp, topEnd = 16.dp, bottomStart = 6.dp, bottomEnd = 16.dp)
    }
    Column(
        modifier = Modifier.fillMaxWidth(),
        horizontalAlignment = if (isUser) Alignment.End else Alignment.Start,
    ) {
        Row(verticalAlignment = Alignment.Bottom) {
            if (!isUser) {
                AgentGlyph(agentId = "", modifier = Modifier.padding(end = 8.dp))
            }
            Box(
                modifier = Modifier
                    .widthIn(max = 300.dp)
                    .clip(shape)
                    .then(
                        if (isUser) Modifier.background(palette.brandGradient)
                        else Modifier.background(palette.glassStrong),
                    )
                    .border(1.dp, if (isUser) Color.Transparent else palette.glassBorder, shape)
                    .padding(horizontal = 14.dp, vertical = 11.dp),
            ) {
                Text(
                    message.content,
                    fontSize = 13.5.sp,
                    lineHeight = 22.sp,
                    color = if (isUser) Color.White else palette.textHi,
                )
                if (message.status == "streaming") StreamingCursor()
            }
        }
        if (message.status == "error") {
            Text("生成中断", fontSize = 10.5.sp, color = palette.danger, modifier = Modifier.padding(top = 3.dp))
        } else if (message.status == "cancelled") {
            Text("已停止", fontSize = 10.5.sp, color = palette.textLow, modifier = Modifier.padding(top = 3.dp))
        }
    }
}

@Composable
private fun StreamingCursor() {
    val transition = rememberInfiniteTransition()
    val alpha by transition.animateFloat(
        initialValue = 0.15f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(tween(500), RepeatMode.Reverse),
    )
    Text(
        "▍",
        fontSize = 13.5.sp,
        color = LocalNeurovaColors.current.accent,
        modifier = Modifier.padding(start = 2.dp).alpha(alpha),
    )
}

@Composable
private fun ChatInputBar(
    text: String,
    onTextChange: (String) -> Unit,
    generating: Boolean,
    onSend: () -> Unit,
    onCancel: () -> Unit,
) {
    val palette = LocalNeurovaColors.current
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 14.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        OutlinedTextField(
            value = text,
            onValueChange = onTextChange,
            modifier = Modifier.weight(1f),
            placeholder = { Text("发消息…", color = palette.textLow, fontSize = 13.sp) },
            singleLine = false,
            maxLines = 4,
            shape = RoundedCornerShape(22.dp),
        )
        Spacer(modifier = Modifier.width(8.dp))
        if (generating) {
            IconButton(onClick = onCancel) {
                Icon(Icons.Filled.Stop, contentDescription = "停止", tint = palette.danger)
            }
        } else {
            IconButton(onClick = onSend, enabled = text.isNotBlank()) {
                Icon(
                    Icons.Filled.Send,
                    contentDescription = "发送",
                    tint = if (text.isNotBlank()) palette.accent else palette.textLow,
                )
            }
        }
    }
}

// ---------------------------------------------------------------------------
// F6 会话抽屉
// ---------------------------------------------------------------------------

@Composable
private fun SessionDrawer(
    currentSessionId: String,
    onClose: () -> Unit,
    onSwitchSession: (String, String) -> Unit,
) {
    val runtime = LocalAppRuntime.current
    val palette = LocalNeurovaColors.current
    var sessions by remember { mutableStateOf<List<ChatSessionItem>>(emptyList()) }
    var showArchived by remember { mutableStateOf(false) }
    var query by remember { mutableStateOf("") }
    var loading by remember { mutableStateOf(false) }
    var renaming by remember { mutableStateOf<ChatSessionItem?>(null) }
    var renameText by remember { mutableStateOf("") }
    var menuFor by remember { mutableStateOf<String?>(null) }

    suspend fun reload() {
        loading = true
        runCatching {
            if (showArchived) runtime.chatRepo.listArchived() else runtime.chatRepo.listSessions()
        }.onSuccess { sessions = it }
        loading = false
    }

    LaunchedEffect(showArchived) { reload() }

    fun runOp(operation: suspend () -> Unit) {
        runtime.scope.launch {
            runCatching { operation() }
            reload()
        }
    }

    Box(modifier = Modifier.fillMaxSize()) {
        Box(
            modifier = Modifier
                .matchParentSize()
                .background(Color.Black.copy(alpha = 0.6f))
                .clickable { onClose() },
        )
        Column(
            modifier = Modifier
                .align(Alignment.CenterEnd)
                .fillMaxSize()
                .width(302.dp)
                // 设计稿 .drawer 是 0.96 近实心底——玻璃透明会让聊天内容透出来
                .background(MaterialTheme.colorScheme.surface)
                .statusBarsPadding()
                .padding(horizontal = 14.dp, vertical = 12.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(modifier = Modifier.weight(1f)) {
                    Text("对话", fontSize = 18.sp, fontWeight = FontWeight.Bold, color = palette.textHi)
                    Text(
                        "会话 ${sessions.size} 个 · ${sessions.count { it.pinned }} 置顶",
                        fontSize = 11.sp,
                        color = palette.textLow,
                    )
                }
                TextButton(onClick = { showArchived = !showArchived }) {
                    Text(if (showArchived) "返回活跃" else "查看归档", fontSize = 11.sp, color = palette.accent)
                }
            }
            Spacer(modifier = Modifier.height(8.dp))
            OutlinedTextField(
                value = query,
                onValueChange = { query = it },
                modifier = Modifier.fillMaxWidth(),
                placeholder = { Text("跨会话搜索…", fontSize = 12.sp, color = palette.textLow) },
                singleLine = true,
                shape = RoundedCornerShape(12.dp),
            )
            Spacer(modifier = Modifier.height(8.dp))
            val filtered = sessions.filter {
                query.isBlank() || it.title.contains(query, ignoreCase = true) || it.agentId.contains(query, ignoreCase = true)
            }
            val groups = groupSessions(filtered, showArchived)
            LazyColumn(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                groups.forEach { (label, groupSessions) ->
                    item(key = "header-$label") {
                        Text(
                            label,
                            fontSize = 10.5.sp,
                            fontWeight = FontWeight.SemiBold,
                            color = palette.textLow,
                            modifier = Modifier.padding(start = 4.dp, top = 8.dp, bottom = 2.dp),
                        )
                    }
                    items(groupSessions, key = { it.id }) { session ->
                        DrawerSessionRow(
                            session = session,
                            isCurrent = session.id == currentSessionId,
                            menuOpen = menuFor == session.id,
                            onMenuToggle = { menuFor = if (menuFor == session.id) null else session.id },
                            onMenuDismiss = { menuFor = null },
                            onOpen = {
                                menuFor = null
                                if (showArchived) {
                                    runOp { runtime.chatRepo.unarchive(session.id) }
                                } else {
                                    onSwitchSession(session.id, session.title)
                                }
                            },
                            onRename = {
                                menuFor = null
                                renameText = session.title
                                renaming = session
                            },
                            onPinToggle = {
                                menuFor = null
                                runOp { runtime.chatRepo.setPinned(session.id, !session.pinned) }
                            },
                            onArchive = {
                                menuFor = null
                                runOp { runtime.chatRepo.archive(session.id) }
                            },
                            onFork = {
                                menuFor = null
                                runOp { runtime.chatRepo.fork(session.id) }
                            },
                            onDelete = {
                                menuFor = null
                                runOp { runtime.chatRepo.remove(session.id) }
                            },
                        )
                    }
                }
                if (filtered.isEmpty() && !loading) {
                    item { Text("没有会话", fontSize = 12.sp, color = palette.textLow, modifier = Modifier.padding(8.dp)) }
                }
            }
        }
        renaming?.let { target ->
            AlertDialog(
                onDismissRequest = { renaming = null },
                title = { Text("重命名会话", fontSize = 16.sp) },
                text = {
                    OutlinedTextField(
                        value = renameText,
                        onValueChange = { renameText = it },
                        singleLine = true,
                    )
                },
                confirmButton = {
                    TextButton(onClick = {
                        val targetId = target.id
                        val newTitle = renameText.trim()
                        renaming = null
                        if (newTitle.isNotEmpty()) runOp { runtime.chatRepo.rename(targetId, newTitle) }
                    }) { Text("保存") }
                },
                dismissButton = { TextButton(onClick = { renaming = null }) { Text("取消") } },
            )
        }
    }
}

@Composable
private fun DrawerSessionRow(
    session: ChatSessionItem,
    isCurrent: Boolean,
    menuOpen: Boolean,
    onMenuToggle: () -> Unit,
    onMenuDismiss: () -> Unit,
    onOpen: () -> Unit,
    onRename: () -> Unit,
    onPinToggle: () -> Unit,
    onArchive: () -> Unit,
    onFork: () -> Unit,
    onDelete: () -> Unit,
) {
    val palette = LocalNeurovaColors.current
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(13.dp))
            .background(if (isCurrent) palette.accent.copy(alpha = 0.12f) else palette.glass)
            .border(
                1.dp,
                if (session.pinned) palette.accent.copy(alpha = 0.45f) else palette.glassBorder,
                RoundedCornerShape(13.dp),
            )
            .clickable { onOpen() }
            .padding(horizontal = 10.dp, vertical = 9.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        AgentGlyph(agentId = session.agentId)
        Spacer(modifier = Modifier.width(10.dp))
        Column(modifier = Modifier.weight(1f)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    session.title,
                    fontSize = 13.5.sp,
                    fontWeight = FontWeight.SemiBold,
                    color = palette.textHi,
                    maxLines = 1,
                    overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f, fill = false),
                )
                if (session.pinned) {
                    Icon(
                        Icons.Filled.Star,
                        contentDescription = "置顶",
                        tint = palette.accent,
                        modifier = Modifier.padding(start = 4.dp).size(12.dp),
                    )
                }
            }
            Text(
                formatSessionTime(session.updatedAt),
                fontSize = 10.5.sp,
                color = palette.textLow,
            )
        }
        Box {
            IconButton(onClick = onMenuToggle) {
                Icon(Icons.Filled.MoreVert, contentDescription = "会话操作", tint = palette.textMid)
            }
            DropdownMenu(expanded = menuOpen, onDismissRequest = onMenuDismiss) {
                DropdownMenuItem(text = { Text(if (session.pinned) "取消置顶" else "置顶") }, onClick = onPinToggle)
                DropdownMenuItem(text = { Text("重命名") }, onClick = onRename)
                DropdownMenuItem(text = { Text("分叉") }, onClick = onFork)
                DropdownMenuItem(text = { Text("归档") }, onClick = onArchive)
                DropdownMenuItem(text = { Text("删除", color = palette.danger) }, onClick = onDelete)
            }
        }
    }
}

/** Agent 头像：品牌渐变圆 + agent 首字符（会话卡与聊天气泡共用） */
@Composable
internal fun AgentGlyph(agentId: String, modifier: Modifier = Modifier) {
    val palette = LocalNeurovaColors.current
    val initial = agentId.trim().firstOrNull()?.uppercaseChar()?.toString() ?: "N"
    Box(
        modifier = modifier
            .size(38.dp)
            .clip(androidx.compose.foundation.shape.CircleShape)
            .background(palette.brandGradient),
        contentAlignment = Alignment.Center,
    ) {
        Text(initial, color = Color.White, fontSize = 15.sp, fontWeight = FontWeight.Bold)
    }
}

private fun groupSessions(sessions: List<ChatSessionItem>, archived: Boolean): List<Pair<String, List<ChatSessionItem>>> {
    val groups = LinkedHashMap<String, MutableList<ChatSessionItem>>()
    val today = java.time.LocalDate.now()
    val ordered = sessions.sortedWith(
        compareByDescending<ChatSessionItem> { it.pinned }.thenByDescending { it.updatedAt ?: "" },
    )
    for (session in ordered) {
        val label = when {
            archived -> "归档"
            session.pinned -> "置顶"
            sessionDate(session.updatedAt) == today -> "今天"
            else -> "更早"
        }
        groups.getOrPut(label) { mutableListOf() }.add(session)
    }
    return groups.map { (key, value) -> key to value.toList() }
}

private fun sessionDate(raw: String?): java.time.LocalDate? = try {
    java.time.LocalDateTime.parse(raw?.take(19)).toLocalDate()
} catch (e: Exception) {
    null
}

internal fun formatSessionTime(raw: String?): String {
    if (raw.isNullOrBlank()) return ""
    return try {
        val dateTime = java.time.LocalDateTime.parse(raw.take(19))
        val today = java.time.LocalDate.now()
        if (dateTime.toLocalDate() == today) {
            dateTime.format(java.time.format.DateTimeFormatter.ofPattern("HH:mm"))
        } else {
            dateTime.format(java.time.format.DateTimeFormatter.ofPattern("MM-dd HH:mm"))
        }
    } catch (e: Exception) {
        raw.take(16).replace('T', ' ')
    }
}
