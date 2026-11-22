package top.neurova.mobile.feature.chat

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.graphics.Color
import kotlinx.serialization.json.JsonObject
import top.neurova.mobile.core.protocol.ApprovalCard
import top.neurova.mobile.core.protocol.HostConfirmationCard
import top.neurova.mobile.ui.theme.LocalNeurovaColors
import top.neurova.mobile.ui.theme.NeurovaColors

/**
 * 确认/审批卡（卡 C · U1 主机确认 / U6 动态干预审批）——聊天页内联交互卡。
 * 形态对齐安卓端既有玻璃卡族（ServerManageScreen 同款视觉语言），文案中文。
 */

@Composable
fun HostKeyConfirmCard(
    card: HostConfirmationCard,
    acting: Boolean,
    error: String?,
    onConfirm: () -> Unit,
    onDismiss: () -> Unit,
) {
    val palette = LocalNeurovaColors.current
    ActionCardSurface(palette = palette) {
        CardTitle(palette, palette.warn, "主机确认")
        Spacer(modifier = Modifier.size(6.dp))
        Text(
            "首次连接主机 ${card.host}:${card.port ?: 22}，请核对服务器公钥指纹：",
            fontSize = 12.sp,
            color = palette.textMid,
        )
        Spacer(modifier = Modifier.size(4.dp))
        Text(
            card.fingerprint.ifBlank { "（服务端未提供指纹）" },
            fontSize = 12.sp,
            fontFamily = FontFamily.Monospace,
            fontWeight = FontWeight.SemiBold,
            color = palette.textHi,
        )
        card.keyType?.takeIf { it.isNotBlank() }?.let {
            Spacer(modifier = Modifier.size(2.dp))
            Text("密钥类型：$it", fontSize = 11.sp, color = palette.textLow)
        }
        CardError(error, palette)
        CardActions(
            palette = palette,
            acting = acting,
            confirmText = "确认连接",
            onConfirm = onConfirm,
            dismissText = "拒绝",
            onDismiss = onDismiss,
        )
    }
}

@Composable
fun ApprovalCardView(
    card: ApprovalCard,
    acting: Boolean,
    error: String?,
    onApprove: () -> Unit,
    onReject: () -> Unit,
) {
    val palette = LocalNeurovaColors.current
    ActionCardSurface(palette = palette) {
        CardTitle(palette, palette.accent, "执行审批")
        Spacer(modifier = Modifier.size(6.dp))
        Text(
            "Agent 请求执行：${card.toolName.ifBlank { "未知工具" }}",
            fontSize = 12.sp,
            color = palette.textMid,
        )
        card.params?.let { params ->
            Spacer(modifier = Modifier.size(4.dp))
            Text(
                "参数：${compactJson(params)}",
                fontSize = 11.sp,
                fontFamily = FontFamily.Monospace,
                color = palette.textLow,
                maxLines = 4,
                overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis,
            )
        }
        card.reason?.takeIf { it.isNotBlank() }?.let {
            Spacer(modifier = Modifier.size(4.dp))
            Text(it, fontSize = 11.sp, color = palette.textLow)
        }
        CardError(error, palette)
        CardActions(
            palette = palette,
            acting = acting,
            confirmText = "批准",
            onConfirm = onApprove,
            dismissText = "拒绝",
            onDismiss = onReject,
        )
    }
}

@Composable
private fun ActionCardSurface(
    palette: NeurovaColors,
    content: @Composable androidx.compose.foundation.layout.ColumnScope.() -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(16.dp))
            .background(palette.glass)
            .border(1.dp, palette.glassBorder, RoundedCornerShape(16.dp))
            .padding(horizontal = 14.dp, vertical = 12.dp),
        content = content,
    )
}

@Composable
private fun CardTitle(palette: NeurovaColors, dotColor: Color, text: String) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        androidx.compose.foundation.layout.Box(
            modifier = Modifier
                .size(8.dp)
                .clip(CircleShape)
                .background(dotColor),
        )
        Spacer(modifier = Modifier.width(8.dp))
        Text(text, fontSize = 13.5.sp, fontWeight = FontWeight.Bold, color = palette.textHi)
    }
}

@Composable
private fun CardError(error: String?, palette: NeurovaColors) {
    error?.takeIf { it.isNotBlank() }?.let {
        Spacer(modifier = Modifier.size(4.dp))
        Text(it, fontSize = 11.sp, color = palette.danger)
    }
}

@Composable
private fun CardActions(
    palette: NeurovaColors,
    acting: Boolean,
    confirmText: String,
    onConfirm: () -> Unit,
    dismissText: String,
    onDismiss: () -> Unit,
) {
    Spacer(modifier = Modifier.size(6.dp))
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.End,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (acting) {
            Text("处理中…", fontSize = 11.sp, color = palette.textLow)
            Spacer(modifier = Modifier.width(8.dp))
        }
        TextButton(onClick = onDismiss, enabled = !acting) {
            Text(dismissText, fontSize = 12.5.sp, color = palette.danger)
        }
        TextButton(onClick = onConfirm, enabled = !acting) {
            Text(confirmText, fontSize = 12.5.sp, color = palette.accent)
        }
    }
}

/** 参数单行摘要（kotlinx JsonObject 紧凑序列化，卡面展示用） */
private fun compactJson(params: JsonObject): String =
    params.toString().take(160)
