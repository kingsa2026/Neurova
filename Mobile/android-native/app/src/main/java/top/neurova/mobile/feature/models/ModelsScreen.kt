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
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
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
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.launch
import top.neurova.mobile.core.model.ModelInfo
import top.neurova.mobile.core.model.ProviderInfo
import top.neurova.mobile.core.model.ProviderTrafficRow
import top.neurova.mobile.ui.components.LocalAppRuntime
import top.neurova.mobile.ui.theme.LocalNeurovaColors

/**
 * P8 次级页 · 模型管理：GET /providers + /models + /providers/active-model（裸数组/裸 dict），
 * 服务商连通性探测 POST /providers/{id}/check-connection，服务商增删编辑
 * （POST/PUT/DELETE /providers，provider.py Create/UpdateProviderRequest 契约）。
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
    var creating by remember { mutableStateOf(false) }
    var editing by remember { mutableStateOf<ProviderInfo?>(null) }
    var deleting by remember { mutableStateOf<ProviderInfo?>(null) }
    // D-R2 观测项：服务商真实流量分布（usage_history 按 provider 聚合）
    var traffic by remember { mutableStateOf<List<ProviderTrafficRow>>(emptyList()) }

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
        // 流量分布副路径：失败静默回空（卡片隐藏），不影响主看板
        traffic = runCatching { runtime.modelsRepo.providerTraffic() }.getOrDefault(emptyList())
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
            Text("模型管理", fontSize = 17.sp, fontWeight = FontWeight.Bold, color = palette.textHi, modifier = Modifier.weight(1f))
            IconButton(onClick = { creating = true }) {
                Icon(Icons.Filled.Add, contentDescription = "新增服务商", tint = palette.textHi)
            }
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
                            IconButton(onClick = { editing = provider }, modifier = Modifier.size(28.dp)) {
                                Icon(Icons.Filled.Edit, contentDescription = "编辑服务商", tint = palette.textMid, modifier = Modifier.size(16.dp))
                            }
                            IconButton(onClick = { deleting = provider }, modifier = Modifier.size(28.dp)) {
                                Icon(Icons.Filled.Delete, contentDescription = "删除服务商", tint = palette.textLow, modifier = Modifier.size(16.dp))
                            }
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
                if (traffic.isNotEmpty()) {
                    item(key = "traffic-title") { SectionLabel("服务商流量分布（近 7 日）") }
                    item(key = "traffic-card") {
                        Column(
                            modifier = Modifier
                                .fillMaxWidth()
                                .clip(RoundedCornerShape(14.dp))
                                .background(palette.glass)
                                .border(1.dp, palette.glassBorder, RoundedCornerShape(14.dp))
                                .padding(horizontal = 13.dp, vertical = 11.dp),
                        ) {
                            traffic.forEach { row ->
                                Row(
                                    modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp),
                                    verticalAlignment = Alignment.CenterVertically,
                                ) {
                                    Text(
                                        row.provider,
                                        fontSize = 12.sp,
                                        fontWeight = FontWeight.SemiBold,
                                        color = palette.textHi,
                                        maxLines = 1,
                                        overflow = TextOverflow.Ellipsis,
                                        modifier = Modifier.weight(1f, fill = false),
                                    )
                                    Text(
                                        "${row.calls} 次 · ${row.tokens} tokens",
                                        fontSize = 10.5.sp,
                                        color = palette.textMid,
                                        modifier = Modifier.padding(start = 8.dp),
                                    )
                                    Text(
                                        "${row.share}%",
                                        fontSize = 12.sp,
                                        fontWeight = FontWeight.SemiBold,
                                        color = palette.accent,
                                        modifier = Modifier.padding(start = 10.dp),
                                    )
                                }
                                Box(
                                    modifier = Modifier
                                        .fillMaxWidth(row.share.toFloat().coerceIn(0.02f, 1f))
                                        .height(5.dp)
                                        .clip(RoundedCornerShape(3.dp))
                                        .background(palette.accent),
                                )
                            }
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

    if (creating) {
        ProviderFormDialog(
            title = "新增服务商",
            initialName = "",
            initialType = "openai",
            initialBaseUrl = "",
            initialApiKey = "",
            initialWeight = 1.0,
            initialEmbeddingModel = "",
            dismiss = { creating = false },
            submit = { name, type, baseUrl, apiKey, weight, embeddingModel ->
                creating = false
                runtime.scope.launch {
                    runCatching { runtime.modelsRepo.createProvider(name, type, baseUrl, apiKey, weight, embeddingModel) }
                    reloadTick = !reloadTick
                }
            },
        )
    }
    editing?.let { provider ->
        ProviderFormDialog(
            title = "编辑服务商",
            initialName = provider.name,
            initialType = provider.providerType,
            initialBaseUrl = provider.baseUrl,
            initialApiKey = "",
            initialWeight = provider.weight,
            initialEmbeddingModel = provider.embeddingModel ?: "",
            dismiss = { editing = null },
            submit = { name, _, baseUrl, apiKey, weight, embeddingModel ->
                val target = provider.providerId
                editing = null
                runtime.scope.launch {
                    runCatching { runtime.modelsRepo.updateProvider(target, name, baseUrl, apiKey, weight, embeddingModel) }
                    reloadTick = !reloadTick
                }
            },
        )
    }
    deleting?.let { provider ->
        AlertDialog(
            onDismissRequest = { deleting = null },
            title = { Text("删除服务商", fontSize = 16.sp) },
            text = { Text("确认删除「${provider.name}」？其模型清单将一并移除。", fontSize = 13.sp) },
            confirmButton = {
                TextButton(onClick = {
                    val target = provider.providerId
                    deleting = null
                    runtime.scope.launch {
                        runCatching { runtime.modelsRepo.deleteProvider(target) }
                        reloadTick = !reloadTick
                    }
                }) { Text("删除", color = palette.danger) }
            },
            dismissButton = { TextButton(onClick = { deleting = null }) { Text("取消") } },
        )
    }
}

private val PROVIDER_TYPES = listOf("openai", "anthropic", "gemini", "ollama", "openrouter")

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

/** 新增/编辑共用表单：编辑时 apiKey 留空 = 不改动（后端 Update 语义）。
 *  weight/embeddingModel：D-R2/R11 声明位——weight 留空 = 不改动；
 *  embeddingModel 编辑时清空 = 清除声明（后端空串语义），创建时留空 = 不下发。 */
@Composable
private fun ProviderFormDialog(
    title: String,
    initialName: String,
    initialType: String,
    initialBaseUrl: String,
    initialApiKey: String,
    initialWeight: Double,
    initialEmbeddingModel: String,
    dismiss: () -> Unit,
    submit: (name: String, type: String, baseUrl: String, apiKey: String, weight: Double?, embeddingModel: String) -> Unit,
) {
    val palette = LocalNeurovaColors.current
    var name by remember { mutableStateOf(initialName) }
    var type by remember { mutableStateOf(initialType) }
    var baseUrl by remember { mutableStateOf(initialBaseUrl) }
    var apiKey by remember { mutableStateOf(initialApiKey) }
    var weightText by remember { mutableStateOf(initialWeight.toString().removeSuffix(".0")) }
    var embeddingModel by remember { mutableStateOf(initialEmbeddingModel) }

    AlertDialog(
        onDismissRequest = dismiss,
        title = { Text(title, fontSize = 16.sp) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(value = name, onValueChange = { name = it }, label = { Text("名称") }, singleLine = true)
                Text("类型", fontSize = 11.sp, color = palette.textLow)
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    PROVIDER_TYPES.forEach { candidate ->
                        val selected = candidate == type
                        Text(
                            candidate,
                            fontSize = 11.sp,
                            color = if (selected) palette.textHi else palette.textMid,
                            modifier = Modifier
                                .clip(RoundedCornerShape(999.dp))
                                .background(if (selected) palette.accent.copy(alpha = 0.25f) else palette.glass)
                                .border(
                                    1.dp,
                                    if (selected) palette.accent.copy(alpha = 0.6f) else palette.glassBorder,
                                    RoundedCornerShape(999.dp),
                                )
                                .clickable { type = candidate }
                                .padding(horizontal = 10.dp, vertical = 5.dp),
                        )
                    }
                }
                OutlinedTextField(value = baseUrl, onValueChange = { baseUrl = it }, label = { Text("API 地址") }, singleLine = true)
                OutlinedTextField(
                    value = apiKey,
                    onValueChange = { apiKey = it },
                    label = { Text(if (initialApiKey.isEmpty()) "API Key" else "API Key（留空=不改动）") },
                    singleLine = true,
                )
                OutlinedTextField(
                    value = weightText,
                    onValueChange = { weightText = it },
                    label = { Text("分流权重（同优先级组内；0=仅兜底）") },
                    singleLine = true,
                )
                OutlinedTextField(
                    value = embeddingModel,
                    onValueChange = { embeddingModel = it },
                    label = { Text("嵌入模型（选填；留空=本地嵌入）") },
                    singleLine = true,
                )
            }
        },
        confirmButton = {
            TextButton(
                onClick = {
                    val trimmedName = name.trim()
                    if (trimmedName.isNotEmpty()) {
                        dismiss()
                        val weight = weightText.trim().toDoubleOrNull()
                        submit(trimmedName, type, baseUrl.trim(), apiKey.trim(), weight, embeddingModel.trim())
                    }
                },
                enabled = name.trim().isNotEmpty(),
            ) { Text("保存") }
        },
        dismissButton = { TextButton(onClick = dismiss) { Text("取消") } },
    )
}
