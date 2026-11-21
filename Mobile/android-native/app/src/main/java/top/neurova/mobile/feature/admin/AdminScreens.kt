package top.neurova.mobile.feature.admin

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
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
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
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.launch
import top.neurova.mobile.core.model.AdminGroup
import top.neurova.mobile.core.model.AdminUser
import top.neurova.mobile.ui.components.LocalAppRuntime
import top.neurova.mobile.ui.theme.LocalNeurovaColors

/**
 * P8 管理员域次级页（F10 管理员：用户/用户组）：
 * - GET /enhanced-users（裸 {items,total}）、DELETE /enhanced-users/{id}（不可删自己）；
 * - GET /groups、POST /groups {name,description}；
 * - 路由级 role 门控：非管理员渲染诚实拦截态（后端同权鉴权兜底）。
 */
@Composable
fun AdminUsersScreen(onBack: () -> Unit) = AdminGate(title = "用户管理", onBack = onBack) {
    val runtime = LocalAppRuntime.current
    val palette = LocalNeurovaColors.current
    var users by remember { mutableStateOf<List<AdminUser>>(emptyList()) }
    var loading by remember { mutableStateOf(false) }
    var errorText by remember { mutableStateOf<String?>(null) }
    var deleting by remember { mutableStateOf<AdminUser?>(null) }

    suspend fun reload() {
        loading = true
        errorText = null
        runCatching { runtime.adminRepo.users() }
            .onSuccess { users = it.items }
            .onFailure { errorText = it.message ?: "用户列表加载失败" }
        loading = false
    }

    LaunchedEffect(Unit) { reload() }

    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 20.dp, vertical = 4.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        item(key = "count") {
            Text("共 ${users.size} 个账号", fontSize = 11.5.sp, color = palette.textLow)
        }
        items(users, key = { it.id }) { user ->
            val isSelf = runtime.auth.user?.id == user.id.toString()
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(14.dp))
                    .background(palette.glass)
                    .border(1.dp, palette.glassBorder, RoundedCornerShape(14.dp))
                    .padding(horizontal = 13.dp, vertical = 11.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Box(
                    modifier = Modifier
                        .size(36.dp)
                        .clip(CircleShape)
                        .background(palette.brandGradient),
                    contentAlignment = Alignment.Center,
                ) {
                    Text(
                        user.username.trim().firstOrNull()?.uppercaseChar()?.toString() ?: "U",
                        color = androidx.compose.ui.graphics.Color.White,
                        fontSize = 14.sp,
                        fontWeight = FontWeight.Bold,
                    )
                }
                Spacer(modifier = Modifier.size(10.dp))
                Column(modifier = Modifier.weight(1f)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(user.username, fontSize = 13.5.sp, fontWeight = FontWeight.SemiBold, color = palette.textHi)
                        if (user.role == "admin") {
                            Text(
                                "管理员",
                                fontSize = 9.5.sp,
                                color = palette.accent,
                                modifier = Modifier.padding(start = 6.dp),
                            )
                        }
                        if (isSelf) {
                            Text("（当前账号）", fontSize = 9.5.sp, color = palette.textLow, modifier = Modifier.padding(start = 4.dp))
                        }
                    }
                    Text(
                        "${user.email.ifBlank { "无邮箱" }} · ${if (user.active) "启用" else "停用"} · 最近登录 ${user.lastLogin?.ifBlank { "-" } ?: "-"}",
                        fontSize = 10.5.sp,
                        color = palette.textLow,
                        maxLines = 1,
                        overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis,
                    )
                }
                if (!isSelf) {
                    IconButton(onClick = { deleting = user }) {
                        Icon(Icons.Filled.Delete, contentDescription = "删除用户", tint = palette.textLow)
                    }
                }
            }
        }
    }

    deleting?.let { target ->
        AlertDialog(
            onDismissRequest = { deleting = null },
            title = { Text("删除用户", fontSize = 16.sp) },
            text = { Text("确认删除账号「${target.username}」（ID ${target.id}）？该操作不可恢复。", fontSize = 13.sp) },
            confirmButton = {
                TextButton(onClick = {
                    val targetId = target.id
                    deleting = null
                    runtime.scope.launch {
                        runCatching { runtime.adminRepo.deleteUser(targetId) }
                        reload()
                    }
                }) { Text("删除", color = palette.danger) }
            },
            dismissButton = { TextButton(onClick = { deleting = null }) { Text("取消") } },
        )
    }
}

@Composable
fun AdminGroupsScreen(onBack: () -> Unit) = AdminGate(title = "用户组", onBack = onBack) {
    val runtime = LocalAppRuntime.current
    val palette = LocalNeurovaColors.current
    var groups by remember { mutableStateOf<List<AdminGroup>>(emptyList()) }
    var loading by remember { mutableStateOf(false) }
    var errorText by remember { mutableStateOf<String?>(null) }
    var creating by remember { mutableStateOf(false) }
    var newName by remember { mutableStateOf("") }
    var newDesc by remember { mutableStateOf("") }

    suspend fun reload() {
        loading = true
        errorText = null
        runCatching { runtime.adminRepo.groups() }
            .onSuccess { groups = it }
            .onFailure { errorText = it.message ?: "用户组加载失败" }
        loading = false
    }

    LaunchedEffect(Unit) { reload() }

    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 20.dp, vertical = 4.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        item(key = "add") {
            Text(
                "+ 新建用户组",
                fontSize = 12.5.sp,
                color = palette.accent,
                modifier = Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(12.dp))
                    .clickable { creating = true }
                    .padding(12.dp),
            )
        }
        items(groups, key = { it.groupId }) { group ->
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(14.dp))
                    .background(palette.glass)
                    .border(1.dp, palette.glassBorder, RoundedCornerShape(14.dp))
                    .padding(horizontal = 13.dp, vertical = 11.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(modifier = Modifier.weight(1f)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(group.name, fontSize = 13.5.sp, fontWeight = FontWeight.SemiBold, color = palette.textHi)
                        if (group.membersCount > 0) {
                            Text(
                                "${group.membersCount} 成员",
                                fontSize = 9.5.sp,
                                color = palette.textLow,
                                modifier = Modifier.padding(start = 6.dp),
                            )
                        }
                    }
                    if (group.description.isNotBlank()) {
                        Text(
                            group.description,
                            fontSize = 10.5.sp,
                            color = palette.textLow,
                            maxLines = 1,
                            overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis,
                        )
                    }
                }
            }
        }
    }

    creating.let {
        AlertDialog(
            onDismissRequest = { creating = false },
            title = { Text("新建用户组", fontSize = 16.sp) },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedTextField(value = newName, onValueChange = { newName = it }, label = { Text("名称") }, singleLine = true)
                    OutlinedTextField(value = newDesc, onValueChange = { newDesc = it }, label = { Text("描述") }, singleLine = true)
                }
            },
            confirmButton = {
                TextButton(onClick = {
                    val name = newName.trim()
                    creating = false
                    if (name.isNotEmpty()) {
                        runtime.scope.launch {
                            runCatching { runtime.adminRepo.createGroup(name, newDesc.trim()) }
                            reload()
                        }
                    }
                    newName = ""
                    newDesc = ""
                }) { Text("创建") }
            },
            dismissButton = { TextButton(onClick = { creating = false }) { Text("取消") } },
        )
    }
}

/** 管理员路由门控：非管理员渲染诚实拦截态（后端同权鉴权兜底）；P1-8 演化状态页复用 */
@Composable
internal fun AdminGate(title: String, onBack: () -> Unit, content: @Composable () -> Unit) {
    val runtime = LocalAppRuntime.current
    val palette = LocalNeurovaColors.current
    Column(modifier = Modifier.fillMaxSize().statusBarsPadding()) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(start = 8.dp, end = 16.dp, top = 6.dp, bottom = 6.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            IconButton(onClick = onBack) {
                Icon(Icons.Filled.ArrowBack, contentDescription = "返回", tint = palette.textHi)
            }
            Text(title, fontSize = 17.sp, fontWeight = FontWeight.Bold, color = palette.textHi)
        }
        if (!runtime.auth.isAdmin) {
            Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Text("需要管理员身份", fontSize = 12.sp, color = palette.textLow)
            }
        } else {
            content()
        }
    }
}
