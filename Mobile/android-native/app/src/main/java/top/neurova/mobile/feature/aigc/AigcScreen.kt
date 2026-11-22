package top.neurova.mobile.feature.aigc

import android.content.Intent
import android.graphics.BitmapFactory
import android.media.MediaPlayer
import android.net.Uri
import android.widget.MediaController
import android.widget.VideoView
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.OpenInNew
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilledIconButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import top.neurova.mobile.core.net.ChannelHttpException
import top.neurova.mobile.ui.components.LocalAppRuntime
import top.neurova.mobile.ui.theme.LocalNeurovaColors

/**
 * AIGC 生成页（多模态追平增量）：图像/视频/音频/音乐四类入口。
 * 提交 → （视频/音乐每 3s 轮询至终态，随页面卸载取消）→ 产物展示
 * （图预览 / 视频播放器 / 音频播放器 / 下载链接）。失败、服务端拒绝（含无可用模型）、
 * 超时一律以原文诚实呈现，不吞不降级。
 */
@Composable
fun AigcScreen(onBack: () -> Unit) {
    val runtime = LocalAppRuntime.current
    val palette = LocalNeurovaColors.current
    // 页面级协程域：离开组合即取消，轮询协程随之清理（勿改挂 runtime.scope 常驻域）
    val scope = rememberCoroutineScope()
    val repo = runtime.aigcRepo

    var kind by remember { mutableStateOf(AigcKind.IMAGE) }
    var prompt by remember { mutableStateOf("") }
    var widthText by remember { mutableStateOf("1024") }
    var heightText by remember { mutableStateOf("1024") }
    var durationText by remember { mutableStateOf("5") }
    var resolution by remember { mutableStateOf("1080p") }
    var voice by remember { mutableStateOf("default") }
    var speedText by remember { mutableStateOf("1.0") }

    var busy by remember { mutableStateOf(false) }
    var statusText by remember { mutableStateOf<String?>(null) }
    var errorText by remember { mutableStateOf<String?>(null) }
    var warnText by remember { mutableStateOf<String?>(null) }
    var imageResult by remember { mutableStateOf<ImageGenerationResult?>(null) }
    var mediaUrl by remember { mutableStateOf<String?>(null) }
    var rawUrl by remember { mutableStateOf<String?>(null) }

    fun showError(e: Throwable) {
        errorText = when (e) {
            is ChannelHttpException -> e.detail.ifBlank { e.message }
            else -> e.message
        } ?: "生成失败"
    }

    fun resetOutcome() {
        errorText = null
        warnText = null
        imageResult = null
        mediaUrl = null
        rawUrl = null
    }

    fun submit() {
        val content = prompt.trim()
        if (busy || content.isEmpty()) return
        val width = widthText.toIntOrNull()
        val height = heightText.toIntOrNull()
        val duration = durationText.toIntOrNull()
        val speed = speedText.toDoubleOrNull()
        if (kind == AigcKind.IMAGE && (width == null || width <= 0 || height == null || height <= 0)) {
            errorText = "宽高需为正整数"
            return
        }
        if ((kind == AigcKind.VIDEO || kind == AigcKind.MUSIC) && (duration == null || duration <= 0)) {
            errorText = "时长需为正整数（秒）"
            return
        }
        if (kind == AigcKind.AUDIO && (speed == null || speed <= 0.0)) {
            errorText = "语速需为正数"
            return
        }

        val accessToken = runtime.credentials.accessToken()
        val baseUrl = runtime.currentProfile().baseUrl
        busy = true
        resetOutcome()
        statusText = "提交中…"
        scope.launch {
            try {
                when (kind) {
                    AigcKind.IMAGE -> {
                        statusText = "图像生成中…"
                        val result = repo.submitImage(content, width ?: 1024, height ?: 1024)
                        imageResult = result
                        if (result.images.none { it.url.isNotBlank() }) {
                            warnText = "任务完成但未返回可用图像地址"
                        }
                    }
                    AigcKind.VIDEO -> {
                        val submitted = repo.submitVideo(content, duration ?: 5, resolution.trim().ifBlank { "1080p" })
                        if (submitted.taskId.isBlank()) throw GenerationSubmitFailed("提交未返回任务 ID")
                        statusText = "视频任务已提交（${submitted.protocol}），生成中…"
                        val done = repo.pollUntilDone(AigcKind.VIDEO, submitted.taskId, onPoll = {
                            statusText = "视频生成中（${it.status}）…"
                        })
                        mediaUrl = resolveMediaUrl(baseUrl, done.url, accessToken).ifBlank { null }
                        rawUrl = done.url.ifBlank { null }
                        warnText = done.warning.ifBlank { null }
                        if (mediaUrl == null) warnText = (warnText?.plus("；") ?: "") + "任务完成但未返回产物地址"
                    }
                    AigcKind.AUDIO -> {
                        statusText = "音频合成中…"
                        val result = repo.submitAudio(content, voice.trim().ifBlank { "default" }, speed ?: 1.0)
                        mediaUrl = resolveMediaUrl(baseUrl, result.url, accessToken).ifBlank { null }
                        rawUrl = result.url.ifBlank { null }
                        if (mediaUrl == null) warnText = "合成完成但未返回产物地址"
                    }
                    AigcKind.MUSIC -> {
                        val submitted = repo.submitMusic(content, duration ?: 30)
                        if (submitted.taskId.isBlank()) throw GenerationSubmitFailed("提交未返回任务 ID")
                        statusText = "音乐任务已提交（${submitted.protocol}），生成中…"
                        val done = repo.pollUntilDone(AigcKind.MUSIC, submitted.taskId, onPoll = {
                            statusText = "音乐生成中（${it.status}）…"
                        })
                        mediaUrl = resolveMediaUrl(baseUrl, done.url, accessToken).ifBlank { null }
                        rawUrl = done.url.ifBlank { null }
                        warnText = done.warning.ifBlank { null }
                        if (mediaUrl == null) warnText = (warnText?.plus("；") ?: "") + "任务完成但未返回产物地址"
                    }
                }
                statusText = null
            } catch (e: CancellationException) {
                throw e
            } catch (e: Throwable) {
                statusText = null
                showError(e)
            } finally {
                busy = false
            }
        }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .statusBarsPadding()
            .imePadding(),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(start = 8.dp, end = 16.dp, top = 6.dp, bottom = 6.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            IconButton(onClick = onBack) {
                Icon(Icons.Filled.ArrowBack, contentDescription = "返回", tint = palette.textHi)
            }
            Text("AIGC 生成", fontSize = 17.sp, fontWeight = FontWeight.Bold, color = palette.textHi, modifier = Modifier.weight(1f))
        }
        LazyColumn(
            modifier = Modifier.fillMaxSize(),
            contentPadding = PaddingValues(horizontal = 20.dp, vertical = 4.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            item(key = "kinds") {
                KindChips(selected = kind, enabled = !busy, onSelect = { kind = it })
            }
            item(key = "prompt") {
                OutlinedTextField(
                    value = prompt,
                    onValueChange = { prompt = it },
                    label = { Text(if (kind == AigcKind.AUDIO) "文本内容" else "提示词") },
                    modifier = Modifier.fillMaxWidth(),
                    minLines = 3,
                )
            }
            item(key = "params") {
                when (kind) {
                    AigcKind.IMAGE -> Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedTextField(
                            value = widthText,
                            onValueChange = { widthText = it },
                            label = { Text("宽 px") },
                            singleLine = true,
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                            modifier = Modifier.weight(1f),
                        )
                        OutlinedTextField(
                            value = heightText,
                            onValueChange = { heightText = it },
                            label = { Text("高 px") },
                            singleLine = true,
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                            modifier = Modifier.weight(1f),
                        )
                    }
                    AigcKind.VIDEO -> Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedTextField(
                            value = durationText,
                            onValueChange = { durationText = it },
                            label = { Text("时长（秒）") },
                            singleLine = true,
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                            modifier = Modifier.weight(1f),
                        )
                        OutlinedTextField(
                            value = resolution,
                            onValueChange = { resolution = it },
                            label = { Text("分辨率") },
                            singleLine = true,
                            modifier = Modifier.weight(1f),
                        )
                    }
                    AigcKind.AUDIO -> Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedTextField(
                            value = voice,
                            onValueChange = { voice = it },
                            label = { Text("音色") },
                            singleLine = true,
                            modifier = Modifier.weight(1f),
                        )
                        OutlinedTextField(
                            value = speedText,
                            onValueChange = { speedText = it },
                            label = { Text("语速") },
                            singleLine = true,
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                            modifier = Modifier.weight(1f),
                        )
                    }
                    AigcKind.MUSIC -> OutlinedTextField(
                        value = durationText,
                        onValueChange = { durationText = it },
                        label = { Text("时长（秒）") },
                        singleLine = true,
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
            }
            item(key = "submit") {
                Button(
                    onClick = { submit() },
                    enabled = !busy && prompt.isNotBlank(),
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Text(if (busy) "处理中…" else "生成")
                }
            }
            if (busy) {
                item(key = "progress") {
                    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        CircularProgressIndicator(modifier = Modifier.size(16.dp), strokeWidth = 2.dp, color = palette.accent)
                        Text(statusText ?: "处理中…", fontSize = 12.sp, color = palette.textMid)
                    }
                }
            }
            errorText?.let { message ->
                item(key = "error") {
                    Text(message, fontSize = 12.sp, color = palette.danger)
                }
            }
            warnText?.let { message ->
                item(key = "warn") {
                    Text(message, fontSize = 11.5.sp, color = palette.warn)
                }
            }
            imageResult?.let { result ->
                if (result.ignoredParams.isNotBlank()) {
                    item(key = "ignored") {
                        Text("已忽略参数：${result.ignoredParams}", fontSize = 11.sp, color = palette.textLow)
                    }
                }
                itemsIndexed(result.images, key = { _, img -> "img-${img.url}-${img.error}" }) { _, image ->
                    when {
                        image.error.isNotBlank() -> Text("该图生成失败：${image.error}", fontSize = 12.sp, color = palette.danger)
                        image.url.isBlank() -> Text("该图未返回产物地址", fontSize = 12.sp, color = palette.warn)
                        else -> ImagePreviewItem(repo, image.url)
                    }
                }
            }
            mediaUrl?.let { url ->
                item(key = "media") {
                    key(url) {
                        when (kind) {
                            AigcKind.VIDEO -> VideoPlayerItem(url)
                            AigcKind.AUDIO, AigcKind.MUSIC -> AudioPlayerItem(url)
                            else -> {}
                        }
                    }
                }
            }
            rawUrl?.let { link ->
                item(key = "link") {
                    MediaLinkRow(runtime.currentProfile().baseUrl, link, runtime.credentials.accessToken())
                }
            }
        }
    }
}

@Composable
private fun KindChips(selected: AigcKind, enabled: Boolean, onSelect: (AigcKind) -> Unit) {
    val palette = LocalNeurovaColors.current
    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        AigcKind.entries.forEach { candidate ->
            val isSelected = candidate == selected
            Text(
                candidate.label,
                fontSize = 12.sp,
                color = when {
                    isSelected -> palette.textHi
                    enabled -> palette.textMid
                    else -> palette.textLow
                },
                modifier = Modifier
                    .clip(RoundedCornerShape(999.dp))
                    .background(if (isSelected) palette.accent.copy(alpha = 0.25f) else palette.glass)
                    .border(
                        1.dp,
                        if (isSelected) palette.accent.copy(alpha = 0.6f) else palette.glassBorder,
                        RoundedCornerShape(999.dp),
                    )
                    .clickable(enabled = enabled) { onSelect(candidate) }
                    .padding(horizontal = 14.dp, vertical = 7.dp),
            )
        }
    }
}

/** 图像预览：同源相对 url 走 Bearer 拉字节解码；解码失败/远程图诚实降级为提示（链接仍在下方） */
@Composable
private fun ImagePreviewItem(repo: AigcRepository, url: String) {
    val palette = LocalNeurovaColors.current
    var bitmap by remember(url) { mutableStateOf<ImageBitmap?>(null) }
    var failed by remember(url) { mutableStateOf(false) }
    LaunchedEffect(url) {
        if (!url.startsWith("/")) {
            failed = true
            return@LaunchedEffect
        }
        withContext(Dispatchers.IO) {
            runCatching { repo.fetchMediaBytes(url) }
                .onSuccess { bytes ->
                    val decoded = BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
                    if (decoded != null) bitmap = decoded.asImageBitmap() else failed = true
                }
                .onFailure { failed = true }
        }
    }
    val bmp = bitmap
    when {
        bmp != null -> Image(
            bitmap = bmp,
            contentDescription = "生成图像预览",
            modifier = Modifier
                .fillMaxWidth()
                .clip(RoundedCornerShape(14.dp)),
        )
        failed -> Text("图片预览不可用，可经下方链接访问", fontSize = 11.5.sp, color = palette.warn)
        else -> Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            CircularProgressIndicator(modifier = Modifier.size(16.dp), strokeWidth = 2.dp, color = palette.accent)
            Text("图片加载中…", fontSize = 11.5.sp, color = palette.textMid)
        }
    }
}

/** 视频播放器：VideoView + 系统媒体控件；播放失败显示原始错误码，不静默黑屏 */
@Composable
private fun VideoPlayerItem(playbackUrl: String) {
    val palette = LocalNeurovaColors.current
    var playError by remember(playbackUrl) { mutableStateOf<String?>(null) }
    AndroidView(
        factory = { context ->
            VideoView(context).apply {
                setVideoURI(Uri.parse(playbackUrl))
                setMediaController(MediaController(context))
                setOnErrorListener { _, what, extra ->
                    playError = "视频播放失败（what=$what extra=$extra），可经下方链接播放"
                    true
                }
                start()
            }
        },
        modifier = Modifier
            .fillMaxWidth()
            .aspectRatio(16f / 9f)
            .clip(RoundedCornerShape(14.dp))
            .background(androidx.compose.ui.graphics.Color.Black),
    )
    playError?.let { Text(it, fontSize = 11.5.sp, color = palette.warn) }
}

/** 音频播放器：MediaPlayer 异步起播，播放/停止按钮 + 失败诚实显示；离开页面即释放 */
@Composable
private fun AudioPlayerItem(playbackUrl: String) {
    val palette = LocalNeurovaColors.current
    val context = LocalContext.current
    var player by remember { mutableStateOf<MediaPlayer?>(null) }
    var playing by remember { mutableStateOf(false) }
    var playError by remember(playbackUrl) { mutableStateOf<String?>(null) }

    fun stopPlayback() {
        player?.let { current ->
            runCatching { current.stop() }
            current.release()
        }
        player = null
        playing = false
    }

    DisposableEffect(playbackUrl) {
        onDispose { stopPlayback() }
    }

    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        FilledIconButton(onClick = {
            if (playing) {
                stopPlayback()
            } else {
                stopPlayback()
                val fresh = MediaPlayer()
                try {
                    fresh.setDataSource(context, Uri.parse(playbackUrl))
                    fresh.setOnCompletionListener { stopPlayback() }
                    fresh.setOnErrorListener { _, what, extra ->
                        playError = "音频播放失败（what=$what extra=$extra）"
                        playing = false
                        true
                    }
                    fresh.setOnPreparedListener { it.start(); playing = true }
                    fresh.prepareAsync()
                    player = fresh
                } catch (e: Exception) {
                    fresh.release()
                    playError = "音频初始化失败：${e.message}"
                }
            }
        }) {
            Icon(
                if (playing) Icons.Filled.Stop else Icons.Filled.PlayArrow,
                contentDescription = if (playing) "停止播放" else "开始播放",
            )
        }
        Text(if (playing) "播放中…" else "点击播放", fontSize = 12.sp, color = palette.textMid)
    }
    playError?.let { Text(it, fontSize = 11.5.sp, color = palette.danger) }
}

/** 产物链接：展示原值，绝对地址（同源补 access_token 凭证）经系统浏览器打开/下载 */
@Composable
private fun MediaLinkRow(baseUrl: String, rawUrl: String, accessToken: String) {
    val palette = LocalNeurovaColors.current
    val context = LocalContext.current
    var openError by remember { mutableStateOf<String?>(null) }
    val absoluteUrl = remember(baseUrl, rawUrl, accessToken) { resolveMediaUrl(baseUrl, rawUrl, accessToken) }

    Column {
        Text("产物链接", fontSize = 11.sp, color = palette.textLow)
        Text(rawUrl, fontSize = 10.5.sp, color = palette.textLow, maxLines = 2)
        TextButton(onClick = {
            runCatching { context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(absoluteUrl))) }
                .onFailure { openError = "无法打开链接：${it.message}" }
        }) {
            Icon(Icons.AutoMirrored.Filled.OpenInNew, contentDescription = null, modifier = Modifier.size(14.dp))
            Spacer(modifier = Modifier.width(4.dp))
            Text("打开 / 下载", fontSize = 12.sp)
        }
        openError?.let { Text(it, fontSize = 11.sp, color = palette.danger) }
    }
}
