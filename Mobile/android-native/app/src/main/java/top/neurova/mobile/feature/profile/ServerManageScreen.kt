package top.neurova.mobile.feature.profile

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
import top.neurova.mobile.core.model.PairedDevice
import top.neurova.mobile.ui.components.LocalAppRuntime
import top.neurova.mobile.ui.theme.LocalNeurovaColors

/**
 * F10 次级页 · 服务器与配对管理：
 * - 服务器档案：本地 ServersStore（增/删/切换；切换即刻改变全部通道的 apiBase）；
 * - 配对设备：GET /mobile/pairing/list + DELETE /mobile/pairing/{id}（撤销后该设备重连即 4001）。
 */
@Composable
fun ServerManageScreen(onBack: () -> Unit) {
    val runtime = LocalAppRuntime.current
    val palette = LocalNeurovaColors.current
    var adding by remember { mutableStateOf(false) }
    var newName by remember { mutableStateOf("") }
    var newUrl by remember { mutableStateOf("") }
    var devices by remember { mutableStateOf<List<PairedDevice>>(emptyList()) }
    var revoking by remember { mutableStateOf<PairedDevice?>(null) }
    var reloadTick by remember { mutableStateOf(false) }

    LaunchedEffect(reloadTick) {
        runCatching { runtime.pairing.listPairedDevices() }.onSuccess { devices = it }
    }

    Column(modifier = Modifier.fillMaxSize().statusBarsPadding()) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(start = 8.dp, end = 16.dp, top = 6.dp, bottom = 6.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            IconButton(onClick = onBack) {
                Icon(Icons.Filled.ArrowBack, contentDescription = "返回", tint = palette.textHi)
            }
            Text("服务器与配对", fontSize = 17.sp, fontWeight = FontWeight.Bold, color = palette.textHi)
        }

        LazyColumn(modifier = Modifier.weight(1f), contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 20.dp, vertical = 4.dp)) {
            item(key = "servers-title") { SectionLabel("服务器档案") }
            items(runtime.servers.profiles, key = { it.id }) { profile ->
                val isActive = profile.id == runtime.servers.activeId
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(vertical = 4.dp)
                        .clip(RoundedCornerShape(14.dp))
                        .background(palette.glass)
                        .border(
                            1.dp,
                            if (isActive) palette.accent.copy(alpha = 0.5f) else palette.glassBorder,
                            RoundedCornerShape(14.dp),
                        )
                        .clickable { runtime.servers.activate(profile.id) }
                        .padding(horizontal = 13.dp, vertical = 11.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Box(
                        modifier = Modifier
                            .size(9.dp)
                            .clip(CircleShape)
                            .background(if (isActive) palette.success else palette.textLow),
                    )
                    Spacer(modifier = Modifier.size(10.dp))
                    Column(modifier = Modifier.weight(1f)) {
                        Text(profile.name, fontSize = 13.5.sp, fontWeight = FontWeight.SemiBold, color = palette.textHi)
                        Text(profile.baseUrl, fontSize = 11.sp, color = palette.textLow, maxLines = 1, overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis)
                    }
                    if (isActive) {
                        Text("当前", fontSize = 10.5.sp, color = palette.accent)
                    }
                    IconButton(onClick = { runtime.servers.remove(profile.id) }) {
                        Icon(Icons.Filled.Delete, contentDescription = "删除档案", tint = palette.textLow)
                    }
                }
            }
            item(key = "add-server") {
                Text(
                    "+ 新增服务器档案",
                    fontSize = 12.5.sp,
                    color = palette.accent,
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(vertical = 8.dp)
                        .clip(RoundedCornerShape(12.dp))
                        .clickable { adding = true }
                        .padding(12.dp),
                )
            }
            item(key = "devices-title") { SectionLabel("已配对设备（${devices.size}）") }
            items(devices, key = { it.pairingId }) { device ->
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(vertical = 4.dp)
                        .clip(RoundedCornerShape(14.dp))
                        .background(palette.glass)
                        .border(1.dp, palette.glassBorder, RoundedCornerShape(14.dp))
                        .padding(horizontal = 13.dp, vertical = 11.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Column(modifier = Modifier.weight(1f)) {
                        Text(device.deviceName, fontSize = 13.5.sp, fontWeight = FontWeight.SemiBold, color = palette.textHi)
                        Text(
                            "${device.deviceType} · ${if (device.isOnline) "在线" else "离线"}",
                            fontSize = 11.sp,
                            color = palette.textLow,
                        )
                    }
                    TextButton(onClick = { revoking = device }) {
                        Text("解除配对", fontSize = 11.sp, color = palette.danger)
                    }
                }
            }
        }
    }

    if (adding) {
        AlertDialog(
            onDismissRequest = { adding = false },
            title = { Text("新增服务器档案", fontSize = 16.sp) },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedTextField(value = newName, onValueChange = { newName = it }, label = { Text("名称") }, singleLine = true)
                    OutlinedTextField(value = newUrl, onValueChange = { newUrl = it }, label = { Text("地址（http://host:port）") }, singleLine = true)
                }
            },
            confirmButton = {
                TextButton(onClick = {
                    val name = newName.trim()
                    val url = newUrl.trim()
                    adding = false
                    if (name.isNotEmpty() && url.isNotEmpty()) {
                        runtime.servers.upsert(runtime.servers.newProfile(name, url, top.neurova.mobile.core.model.ServerProfile.EntryMode.DIRECT))
                    }
                    newName = ""
                    newUrl = ""
                }) { Text("保存") }
            },
            dismissButton = { TextButton(onClick = { adding = false }) { Text("取消") } },
        )
    }
    revoking?.let { device ->
        AlertDialog(
            onDismissRequest = { revoking = null },
            title = { Text("解除配对", fontSize = 16.sp) },
            text = { Text("撤销后「${device.deviceName}」的长期身份立即失效，需重新扫码配对。", fontSize = 13.sp) },
            confirmButton = {
                TextButton(onClick = {
                    val target = device.pairingId
                    revoking = null
                    runtime.scope.launch {
                        runCatching { runtime.pairing.revokePairing(target) }
                        reloadTick = !reloadTick
                    }
                }) { Text("解除", color = palette.danger) }
            },
            dismissButton = { TextButton(onClick = { revoking = null }) { Text("取消") } },
        )
    }
}

@Composable
private fun SectionLabel(text: String) {
    Text(
        text,
        fontSize = 12.sp,
        fontWeight = FontWeight.SemiBold,
        color = LocalNeurovaColors.current.textLow,
        modifier = Modifier.padding(top = 10.dp, bottom = 4.dp),
    )
}
