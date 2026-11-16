package top.neurova.mobile.feature.models

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
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
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
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.launch
import top.neurova.mobile.core.model.ModelInfo
import top.neurova.mobile.core.model.ProviderInfo
import top.neurova.mobile.ui.components.LocalAppRuntime
import top.neurova.mobile.ui.theme.LocalNeurovaColors

/**
 * P8 次级页 · 模型管理：GET /providers + /models + /providers/active-model（裸数组/裸 dict），
 * 服务商连通性探测 POST /providers/{id}/check-connection。增删服务商属管理端配置，随 P9 批次评估。
 */
@Composable
fun ModelsScreen(onBack: () -> Unit) {
    val runtime = LocalAppRuntime.current
    val palette = LocalNeurovaColors.current
    var providers by remember { mutableStateOf<List<ProviderInfo>>(emptyList()) }
    var models by remember { mutableStateOf<List<ModelInfo>>(emptyList()) }
    var activeModel by remember { mutableStateOf<String?>(null) }
    var activeProvider by remember { mutableStateOf<String?>(null) }
    var loading by remember { mutableStateOf(false) }
    var errorText by remember { mutableStateOf<String?>(null) }
    var testing by remember { mutableStateOf<String?>(null) }
    var testResult by remember { mutableStateOf<String?>(null) }
    var reloadTick by remember { mutableStateOf(false) }

    LaunchedEffect(reloadTick) {
        loading = true
        errorText = null
        runCatching {
            providers = runtime.modelsRepo.providers()
            models = runtime.modelsRepo.models()
            val active = runtime.modelsRepo.activeModel()
            activeModel = active.model
            activeProvider = active.provider
        }.onFailure { errorText = it.message ?: "模型域加载失败" }
        loading = false
    }

    Column(modifier = Modifier.fillMaxSize().statusBarsPadding()) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(start = 8.dp, end = 16.dp, top = 6.dp, bottom = 6.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            IconButton(onClick = onBack) {
                Icon(Icons.Filled.ArrowBack, contentDescription = "返回", tint = palette.textHi)
            }
            Text("模型管理", fontSize = 17.sp, fontWeight = FontWeight.Bold, color = palette.textHi)
        }
        when {
            loading && providers.isEmpty() -> Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
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
            else -> LazyColumn(
                modifier = Modifier.fillMaxSize(),
                contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 20.dp, vertical = 4.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                item(key = "active") {
                    Column(modifier = Modifier.fillMaxWidth()) {
                        Text("当前激活模型", fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = palette.textLow, modifier = Modifier.padding(vertical = 4.dp))
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .clip(RoundedCornerShape(14.dp))
                                .background(palette.accent.copy(alpha = 0.1f))
                                .border(1.dp, palette.accent.copy(alpha = 0.5f), RoundedCornerShape(14.dp))
                                .padding(horizontal = 13.dp, vertical = 11.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Box(modifier = Modifier.size(9.dp).clip(CircleShape).background(palette.success))
                            Spacer(modifier = Modifier.size(10.dp))
                            Text(
                                "${activeModel ?: "未设置"}（${activeProvider ?: "-"}）",
                                fontSize = 13.5.sp,
                                fontWeight = FontWeight.SemiBold,
                                color = palette.textHi,
                            )
                        }
                    }
                }
                item(key = "providers-title") { SectionLabel("服务商（${providers.size}）") }
                items(providers, key = { it.providerId }) { provider ->
                    var result by remember { mutableStateOf<String?>(null) }
                    Column(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clip(RoundedCornerShape(14.dp))
                            .background(palette.glass)
                            .border(1.dp, palette.glassBorder, RoundedCornerShape(14.dp))
                            .padding(horizontal = 13.dp, vertical = 11.dp),
                    ) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text(
                                provider.name,
                                fontSize = 13.5.sp,
                                fontWeight = FontWeight.SemiBold,
                                color = palette.textHi,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                                modifier = Modifier.weight(1f, fill = false),
                            )
                            Text(
                                if (provider.apiKeyConfigured) "密钥已配" else "密钥未配",
                                fontSize = 10.sp,
                                color = if (provider.apiKeyConfigured) palette.success else palette.warn,
                                modifier = Modifier.padding(start = 6.dp),
                            )
                        }
                        Text(
                            "${provider.providerType} · ${provider.modelsCount} 个模型 · ${provider.baseUrl}",
                            fontSize = 10.5.sp,
                            color = palette.textLow,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                        )
                        result?.let {
                            Text(it, fontSize = 10.5.sp, color = palette.textMid, modifier = Modifier.padding(top = 3.dp))
                        }
                        TextButton(onClick = {
                            testing = provider.providerId
                            runtime.scope.launch {
                                val outcome = runCatching { runtime.modelsRepo.checkConnection(provider.providerId) }
                                result = outcome.fold(
                                    onSuccess = { r -> if (r.connected) "连通正常" else "不通：${r.message}" },
                                    onFailure = { e -> "探测失败：${e.message}" },
                                )
                                testing = null
                            }
                        }) {
                            Text(
                                if (testing == provider.providerId) "探测中…" else "测试连通",
                                fontSize = 11.sp,
                                color = palette.accent,
                            )
                        }
                    }
                }
                item(key = "models-title") { SectionLabel("模型（${models.size}）") }
                items(models, key = { it.modelId }) { model ->
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clip(RoundedCornerShape(13.dp))
                            .background(palette.glass)
                            .border(1.dp, palette.glassBorder, RoundedCornerShape(13.dp))
                            .padding(horizontal = 13.dp, vertical = 10.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Column(modifier = Modifier.weight(1f)) {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Text(
                                    model.name,
                                    fontSize = 13.sp,
                                    fontWeight = FontWeight.SemiBold,
                                    color = palette.textHi,
                                    maxLines = 1,
                                    overflow = TextOverflow.Ellipsis,
                                    modifier = Modifier.weight(1f, fill = false),
                                )
                                if (model.modelId == activeModel) {
                                    Text(
                                        "激活中",
                                        fontSize = 9.5.sp,
                                        color = palette.success,
                                        modifier = Modifier.padding(start = 6.dp),
                                    )
                                }
                            }
                            Text(
                                "${model.provider} · ${model.capabilities.joinToString("/").ifBlank { "text" }}",
                                fontSize = 10.5.sp,
                                color = palette.textLow,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                            )
                        }
                    }
                }
            }
        }
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
