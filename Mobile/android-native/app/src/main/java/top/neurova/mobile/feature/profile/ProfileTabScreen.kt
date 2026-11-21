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
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
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
import top.neurova.mobile.ui.components.LocalAppRuntime
import top.neurova.mobile.ui.components.PageHeader
import top.neurova.mobile.ui.theme.LocalNeurovaColors

/**
 * F10 我的（个人与设备 · 服务器 · 管理入口）：
 * - 账号卡：/auth/me 的 username/role（admin 徽标）/email；
 * - 服务器：当前档案（ServersStore 单源）；设备：GET /mobile/pairing/list 在册数；
 * - 管理员域页面（用户/组/市场/设置）随 P8 批次接线，本批先亮身份与入口占位。
 */
@Composable
fun ProfileTabScreen(
    onOpenServers: () -> Unit = {},
    onOpenModels: () -> Unit = {},
    onOpenAdminUsers: () -> Unit = {},
    onOpenAdminGroups: () -> Unit = {},
    onOpenAdminEvolution: () -> Unit = {},
) {
    val runtime = LocalAppRuntime.current
    val palette = LocalNeurovaColors.current
    var deviceCount by remember { mutableStateOf(-1) }

    LaunchedEffect(Unit) {
        runCatching { runtime.pairing.pairedDeviceCount() }.onSuccess { deviceCount = it }
    }

    val user = runtime.auth.user
    val server = runtime.servers.active

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState()),
    ) {
        PageHeader(title = "我的", subtitle = "服务器 · 模型 · 管理")
        Spacer(modifier = Modifier.size(4.dp))

        // 账号卡
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 20.dp, vertical = 6.dp)
                .clip(RoundedCornerShape(16.dp))
                .background(palette.glass)
                .border(1.dp, palette.glassBorder, RoundedCornerShape(16.dp))
                .padding(16.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Box(
                modifier = Modifier
                    .size(52.dp)
                    .clip(CircleShape)
                    .background(palette.brandGradient),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    user?.username?.trim()?.firstOrNull()?.uppercaseChar()?.toString() ?: "N",
                    color = Color.White,
                    fontSize = 18.sp,
                    fontWeight = FontWeight.Bold,
                )
            }
            Spacer(modifier = Modifier.size(12.dp))
            Column(modifier = Modifier.weight(1f)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        user?.username ?: "未登录",
                        fontSize = 16.sp,
                        fontWeight = FontWeight.Bold,
                        color = palette.textHi,
                    )
                    if (runtime.auth.isAdmin) {
                        Text(
                            "管理员",
                            fontSize = 10.sp,
                            fontWeight = FontWeight.SemiBold,
                            color = palette.accent,
                            modifier = Modifier
                                .padding(start = 8.dp)
                                .clip(RoundedCornerShape(999.dp))
                                .background(palette.accent.copy(alpha = 0.14f))
                                .padding(horizontal = 8.dp, vertical = 2.dp),
                        )
                    }
                }
                val email = user?.email
                if (!email.isNullOrBlank()) {
                    Text(email, fontSize = 11.5.sp, color = palette.textLow)
                }
                Text("ID ${user?.id ?: "-"}", fontSize = 11.sp, color = palette.textLow)
            }
        }

        SectionTitle("服务器")
        InfoRow(
            title = server?.name?.ifBlank { "默认档案" } ?: "默认档案",
            subtitle = server?.baseUrl ?: "http://10.0.2.2:9527",
            onClick = onOpenServers,
        )
        InfoRow(title = "模型管理", subtitle = "服务商 · 模型 · 连通性", onClick = onOpenModels)
        SectionTitle("设备")
        InfoRow(
            title = "已配对设备",
            subtitle = if (deviceCount >= 0) "$deviceCount 台在册 · 扫码配对免重连" else "读取中…",
            onClick = onOpenServers,
        )

        if (runtime.auth.isAdmin) {
            SectionTitle("管理员域")
            InfoRow(title = "用户管理", subtitle = "账号列表 · 停用/删除", onClick = onOpenAdminUsers)
            InfoRow(title = "用户组", subtitle = "分组与成员", onClick = onOpenAdminGroups)
            // P1-8：演化状态只读入口（当前基线代/最近世代/门禁结果摘要；写面留 PC 治理页）
            InfoRow(title = "演化状态", subtitle = "当前基线代 · 门禁结果摘要", onClick = onOpenAdminEvolution)
        }
        Spacer(modifier = Modifier.size(24.dp))
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
