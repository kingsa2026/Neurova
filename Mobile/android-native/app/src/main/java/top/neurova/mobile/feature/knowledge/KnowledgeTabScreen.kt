package top.neurova.mobile.feature.knowledge

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
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.OutlinedTextField
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
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import top.neurova.mobile.core.model.KnowledgeEntry
import top.neurova.mobile.ui.components.LocalAppRuntime
import top.neurova.mobile.ui.components.PageHeader
import top.neurova.mobile.ui.theme.LocalNeurovaColors

/**
 * F9 知识库 Tab（轻量子集）：GET /knowledge 分页列表 + POST /knowledge/search 防抖搜索，
 * 与 PC/鸿蒙同一份知识记录。导入/条目详情/图谱速览随 P8 批次接线。
 */
@Composable
fun KnowledgeTabScreen() {
    val runtime = LocalAppRuntime.current
    val palette = LocalNeurovaColors.current
    var query by remember { mutableStateOf("") }
    var searching by remember { mutableStateOf(false) }
    var items by remember { mutableStateOf<List<KnowledgeEntry>>(emptyList()) }
    var total by remember { mutableStateOf(0) }
    var page by remember { mutableStateOf(1) }
    var loading by remember { mutableStateOf(false) }
    var errorText by remember { mutableStateOf<String?>(null) }
    var category by remember { mutableStateOf("全部") }

    suspend fun loadPage(target: Int, append: Boolean) {
        loading = true
        errorText = null
        runCatching { runtime.knowledgeRepo.list(page = target, pageSize = 20) }
            .onSuccess { payload ->
                total = payload.total
                page = payload.page
                items = if (append) items + payload.items else payload.items
            }
            .onFailure { errorText = it.message ?: "知识库加载失败" }
        loading = false
    }

    // 搜索防抖：停顿 400ms 且长度≥2 才走 POST /knowledge/search（裸数组）
    LaunchedEffect(query) {
        if (query.trim().length < 2) return@LaunchedEffect
        delay(400)
        searching = true
        errorText = null
        runCatching { runtime.knowledgeRepo.search(query.trim()) }
            .onSuccess { result ->
                items = result
                total = result.size
                category = "全部"
            }
            .onFailure { errorText = it.message ?: "搜索失败" }
        searching = false
    }

    LaunchedEffect(Unit) { loadPage(1, append = false) }

    val categories = listOf("全部") + items.map { it.category }.filter { it.isNotBlank() }.distinct()
    val visible = if (category == "全部") items else items.filter { it.category == category }

    Column(modifier = Modifier.fillMaxSize()) {
        PageHeader(title = "知识", subtitle = "知识库轻量子集")
        Text(
            "$total 条" + if (query.trim().length >= 2) " · 搜索：${query.trim()}" else "",
            fontSize = 11.5.sp,
            color = palette.textLow,
            modifier = Modifier.padding(horizontal = 20.dp, vertical = 2.dp),
        )
        OutlinedTextField(
            value = query,
            onValueChange = { query = it },
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 20.dp, vertical = 4.dp),
            placeholder = { Text("搜索知识、口径、规范…", fontSize = 12.5.sp, color = palette.textLow) },
            singleLine = true,
            shape = RoundedCornerShape(12.dp),
            keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
            keyboardActions = KeyboardActions(
                onSearch = {
                    if (query.trim().length >= 2) {
                        runtime.scope.launch {
                            searching = true
                            runCatching { runtime.knowledgeRepo.search(query.trim()) }
                                .onSuccess { result ->
                                    items = result
                                    total = result.size
                                    category = "全部"
                                }
                            searching = false
                        }
                    }
                },
            ),
        )
        if (items.isNotEmpty()) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 20.dp, vertical = 4.dp),
                horizontalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                categories.take(5).forEach { candidate ->
                    val selected = candidate == category
                    Text(
                        candidate,
                        fontSize = 11.5.sp,
                        color = if (selected) palette.textHi else palette.textMid,
                        modifier = Modifier
                            .clip(RoundedCornerShape(999.dp))
                            .background(if (selected) palette.accent.copy(alpha = 0.25f) else palette.glass)
                            .border(
                                1.dp,
                                if (selected) palette.accent.copy(alpha = 0.6f) else palette.glassBorder,
                                RoundedCornerShape(999.dp),
                            )
                            .clickable { category = candidate }
                            .padding(horizontal = 12.dp, vertical = 5.dp),
                    )
                }
            }
        }
        Spacer(modifier = Modifier.size(8.dp))
        when {
            (loading || searching) && items.isEmpty() -> Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                CircularProgressIndicator(color = palette.accent)
            }
            errorText != null -> Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Text(errorText!!, fontSize = 12.sp, color = palette.danger)
                    Spacer(modifier = Modifier.size(8.dp))
                    Text("点击重试", fontSize = 12.sp, color = palette.accent, modifier = Modifier.clickable {
                        runtime.scope.launch { loadPage(1, append = false) }
                    })
                }
            }
            visible.isEmpty() -> Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Text(
                    if (query.trim().length >= 2) "没有匹配的知识条目" else "知识库暂无条目",
                    fontSize = 12.sp,
                    color = palette.textLow,
                )
            }
            else -> LazyColumn(
                modifier = Modifier.fillMaxSize(),
                contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 20.dp, vertical = 4.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                items(visible, key = { it.knowledgeId }) { entry ->
                    KnowledgeCard(entry)
                }
                if (query.trim().length < 2 && items.size < total) {
                    item(key = "load-more") {
                        Box(modifier = Modifier.fillMaxWidth().padding(vertical = 8.dp), contentAlignment = Alignment.Center) {
                            if (loading) {
                                CircularProgressIndicator(color = palette.accent, modifier = Modifier.size(20.dp))
                            } else {
                                Text(
                                    "加载更多（${items.size}/$total）",
                                    fontSize = 12.sp,
                                    color = palette.accent,
                                    modifier = Modifier
                                        .clip(RoundedCornerShape(999.dp))
                                        .clickable { runtime.scope.launch { loadPage(page + 1, append = true) } }
                                        .padding(horizontal = 16.dp, vertical = 8.dp),
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun KnowledgeCard(entry: KnowledgeEntry) {
    val palette = LocalNeurovaColors.current
    val shape = RoundedCornerShape(14.dp)
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(shape)
            .background(palette.glass)
            .border(1.dp, palette.glassBorder, shape)
            .padding(horizontal = 13.dp, vertical = 11.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                entry.title,
                fontSize = 14.sp,
                fontWeight = FontWeight.SemiBold,
                color = palette.textHi,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.weight(1f, fill = false),
            )
            if (entry.category.isNotBlank()) {
                Text(
                    entry.category,
                    fontSize = 10.sp,
                    color = palette.accent,
                    modifier = Modifier
                        .padding(start = 6.dp)
                        .clip(RoundedCornerShape(999.dp))
                        .background(palette.accent.copy(alpha = 0.12f))
                        .padding(horizontal = 8.dp, vertical = 2.dp),
                )
            }
        }
        Spacer(modifier = Modifier.size(4.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(visibilityLabel(entry.visibility), fontSize = 10.5.sp, color = palette.textLow)
            if (entry.tags.isNotEmpty()) {
                Text(
                    " · " + entry.tags.take(3).joinToString(" / "),
                    fontSize = 10.5.sp,
                    color = palette.textLow,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            Spacer(modifier = Modifier.weight(1f))
            Text(formatEpoch(entry.updatedAt), fontSize = 10.5.sp, color = palette.textLow)
        }
    }
}

private fun visibilityLabel(visibility: String): String = when (visibility) {
    "public" -> "公共"
    "shared" -> "共享"
    else -> "私有"
}

private fun formatEpoch(seconds: Double?): String {
    if (seconds == null || seconds <= 0) return ""
    return try {
        val dateTime = java.time.Instant.ofEpochSecond(seconds.toLong())
            .atZone(java.time.ZoneId.systemDefault())
            .toLocalDateTime()
        val today = java.time.LocalDate.now()
        if (dateTime.toLocalDate() == today) {
            dateTime.format(java.time.format.DateTimeFormatter.ofPattern("HH:mm"))
        } else {
            dateTime.format(java.time.format.DateTimeFormatter.ofPattern("MM-dd HH:mm"))
        }
    } catch (e: Exception) {
        ""
    }
}
