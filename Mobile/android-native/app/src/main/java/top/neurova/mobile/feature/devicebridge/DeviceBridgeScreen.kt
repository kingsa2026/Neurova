package top.neurova.mobile.feature.devicebridge

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import top.neurova.mobile.core.capability.DeviceCapabilities
import top.neurova.mobile.core.capability.DeviceHealthChecks
import top.neurova.mobile.core.net.MobileWsChannel
import top.neurova.mobile.ui.components.LocalAppRuntime
import top.neurova.mobile.ui.theme.LocalNeurovaColors

/**
 * F-设备桥 · 能力授权与体检页（2026-11-23 计划卡 A6）：
 * - 逐能力授权开关（D4：默认全关；hello 目录与端上执行双检都读这里）；
 * - 体检三项：无障碍服务 / 通知监听 / 电池优化白名单（系统前置条件）；
 * - 通道状态与通知白名单展示。
 */
@Composable
fun DeviceBridgeScreen(onBack: () -> Unit) {
    val runtime = LocalAppRuntime.current
    val context = LocalContext.current
    val palette = LocalNeurovaColors.current
    var refreshTick by remember { mutableStateOf(0) }
    val wsState by runtime.ws.state.collectAsState()
    val health = remember(refreshTick) { DeviceHealthChecks.all(context) }
    val enabled = remember(refreshTick) { runtime.deviceAuth.enabledCapabilities() }
    val whitelist = remember(refreshTick) { runtime.deviceAuth.notificationWhitelist() }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .statusBarsPadding()
            .verticalScroll(rememberScrollState()),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 12.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            IconButton(onClick = onBack) {
                Icon(Icons.Filled.ArrowBack, contentDescription = "返回", tint = palette.textHi)
            }
            Text("设备桥", fontSize = 18.sp, fontWeight = FontWeight.Bold, color = palette.textHi)
        }

        SectionTitle("通道")
        InfoRow("通道状态", "WS：${wsState.name} · 前台服务常驻")

        SectionTitle("能力授权（默认全关）")
        for (capability in DeviceCapabilities.CLAIMED) {
            CapabilityRow(
                title = capability,
                enabled = capability in enabled,
                onToggle = { want ->
                    runtime.deviceAuth.setEnabled(capability, want)
                    refreshTick += 1
                },
            )
        }

        SectionTitle("体检")
        for (item in health) {
            InfoRow(
                title = if (item.ok) "✓ ${item.title}" else "✗ ${item.title}",
                subtitle = item.hint,
                onClick = {
                    val action = when (item.key) {
                        "accessibility" -> DeviceHealthChecks.ACTION_ACCESSIBILITY_SETTINGS
                        "notification_listener" -> DeviceHealthChecks.ACTION_NOTIFICATION_LISTENER_SETTINGS
                        else -> null
                    }
                    action?.let {
                        context.startActivity(android.content.Intent(it))
                    }
                },
            )
        }

        SectionTitle("通知白名单（空 = 全量采集）")
        InfoRow(
            title = if (whitelist.isEmpty()) "全量采集" else "仅 ${whitelist.size} 个应用",
            subtitle = if (whitelist.isEmpty()) "可在授权后按应用收窄" else whitelist.joinToString("、"),
        )

        Spacer(modifier = Modifier.padding(bottom = 24.dp))
    }
}

@Composable
private fun CapabilityRow(title: String, enabled: Boolean, onToggle: (Boolean) -> Unit) {
    val palette = LocalNeurovaColors.current
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 20.dp, vertical = 4.dp)
            .clip(RoundedCornerShape(14.dp))
            .background(palette.glass)
            .border(1.dp, palette.glassBorder, RoundedCornerShape(14.dp))
            .padding(horizontal = 14.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text(title, fontSize = 13.5.sp, fontWeight = FontWeight.SemiBold, color = palette.textHi)
        Switch(checked = enabled, onCheckedChange = onToggle)
    }
}

@Composable
private fun SectionTitle(text: String) {
    Text(
        text,
        fontSize = 12.sp,
        fontWeight = FontWeight.SemiBold,
        color = LocalNeurovaColors.current.textLow,
        modifier = Modifier.padding(horizontal = 20.dp, vertical = 8.dp),
    )
}

@Composable
private fun InfoRow(title: String, subtitle: String, onClick: (() -> Unit)? = null) {
    val palette = LocalNeurovaColors.current
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 20.dp, vertical = 4.dp)
            .clip(RoundedCornerShape(14.dp))
            .background(palette.glass)
            .border(1.dp, palette.glassBorder, RoundedCornerShape(14.dp))
            .then(if (onClick != null) Modifier.clickable { onClick() } else Modifier)
            .padding(horizontal = 14.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Column {
            Text(title, fontSize = 13.5.sp, fontWeight = FontWeight.SemiBold, color = palette.textHi)
            Text(subtitle, fontSize = 11.sp, color = palette.textLow)
        }
    }
}
