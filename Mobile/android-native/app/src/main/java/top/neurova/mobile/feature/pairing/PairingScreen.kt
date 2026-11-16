package top.neurova.mobile.feature.pairing

import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import java.util.concurrent.Executors
import kotlinx.coroutines.launch
import top.neurova.mobile.core.protocol.PairingRefParser
import top.neurova.mobile.ui.components.PageHeader
import top.neurova.mobile.ui.components.LocalAppRuntime
import top.neurova.mobile.ui.theme.LocalNeurovaColors

/**
 * F2 扫码配对 · 一扫配全（设计方案 §5.3/§8.2）：
 * 相机扫 PC 端二维码（neurova://pair?ref=…）→ resolve 换回连地址 → confirm 拿设备身份；
 * 二维码不可用时手动输入配对码/ref 兜底。
 */
@Composable
fun PairingScreen(onPaired: () -> Unit) {
    val palette = LocalNeurovaColors.current
    val runtime = LocalAppRuntime.current
    val scope = rememberCoroutineScope()
    var manualRef by remember { mutableStateOf("") }
    var errorMessage by remember { mutableStateOf<String?>(null) }
    var working by remember { mutableStateOf(false) }

    fun pairWithInput(input: String) {
        working = true
        errorMessage = null
        scope.launch {
            runCatching { runtime.pairing.pairByInput(input) }
                .onSuccess { onPaired() }
                .onFailure { failure ->
                    errorMessage = when (failure) {
                        is top.neurova.mobile.core.net.ChannelHttpException -> failure.detail.ifBlank { "配对失败（HTTP ${failure.code}）" }
                        else -> "配对不可达：请确认已连上同一网络或中继"
                    }
                }
            working = false
        }
    }

    Column(modifier = Modifier.fillMaxSize()) {
        PageHeader(title = "配对设备", subtitle = "扫码即完成服务器建档 + 设备配对")
        QrScannerArea(
            enabled = !working,
            onTokenFound = { raw ->
                PairingRefParser.parseRef(raw)?.let { ref -> pairWithInput(ref) }
            },
        )
        Spacer(modifier = Modifier.height(22.dp))
        Text(
            "对准 PC 端「配对设备」二维码",
            fontSize = 15.5.sp,
            fontWeight = FontWeight.SemiBold,
            color = palette.textHi,
            modifier = Modifier.padding(horizontal = 26.dp),
        )
        Text(
            "配对后本机获得长期设备身份，重连免扫码；服务器地址由二维码带回，无需手动录入",
            fontSize = 12.5.sp,
            color = palette.textMid,
            lineHeight = 18.sp,
            modifier = Modifier.padding(horizontal = 26.dp, vertical = 6.dp),
        )
        errorMessage?.let { message ->
            Text(message, fontSize = 12.sp, color = palette.danger, modifier = Modifier.padding(horizontal = 26.dp, vertical = 4.dp))
        }
        Spacer(modifier = Modifier.height(14.dp))
        OutlinedTextField(
            value = manualRef,
            onValueChange = { manualRef = it; errorMessage = null },
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 26.dp),
            placeholder = { Text("二维码不可用？粘贴 ref 或 6 位配对码", color = palette.textLow) },
            singleLine = true,
            shape = RoundedCornerShape(14.dp),
        )
        Spacer(modifier = Modifier.height(12.dp))
        Button(
            onClick = { pairWithInput(manualRef) },
            enabled = manualRef.isNotBlank() && !working,
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 26.dp)
                .height(46.dp),
            shape = RoundedCornerShape(14.dp),
        ) {
            if (working) {
                CircularProgressIndicator(modifier = Modifier.height(18.dp), strokeWidth = 2.dp, color = Color.White)
            } else {
                Text("配 对")
            }
        }
    }
}

/** 相机取景区：CameraX 预览 + MLKit 条码分析；无权限时给出引导态 */
@Composable
private fun QrScannerArea(enabled: Boolean, onTokenFound: (String) -> Unit) {
    val palette = LocalNeurovaColors.current
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    var hasPermission by remember {
        mutableStateOf(
            ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED,
        )
    }
    var cameraError by remember { mutableStateOf(false) }
    val scanner = remember { QrScannerHolder() }
    val permissionLauncher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        hasPermission = granted
    }

    Box(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 26.dp, vertical = 8.dp)
            .height(300.dp)
            .background(
                Brush.linearGradient(listOf(Color(0xFF131A2E), Color(0xFF0C1122))),
                RoundedCornerShape(22.dp),
            ),
        contentAlignment = Alignment.Center,
    ) {
        if (!hasPermission) {
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Text("需要相机权限以扫描配对码", fontSize = 13.sp, color = palette.textMid)
                Spacer(modifier = Modifier.height(10.dp))
                Button(onClick = { permissionLauncher.launch(Manifest.permission.CAMERA) }) {
                    Text("授权相机")
                }
            }
        } else if (cameraError) {
            Text("相机不可用：可改用下方手动输入配对码", fontSize = 13.sp, color = palette.warn)
        } else {
            AndroidView(
                modifier = Modifier.fillMaxSize(),
                factory = { viewContext ->
                    scanner.attach(
                        context = viewContext,
                        lifecycleOwner = lifecycleOwner,
                        onToken = { raw -> if (enabled) onTokenFound(raw) },
                        onError = { cameraError = true },
                    )
                },
                onRelease = { scanner.detach() },
            )
        }
    }
}

/** 扫码器持有者：相机绑定/解绑与条码识别的单生命周期宿主 */
private class QrScannerHolder {
    private val executor = Executors.newSingleThreadExecutor()
    private val scanner = com.google.mlkit.vision.barcode.BarcodeScanning.getClient(
        com.google.mlkit.vision.barcode.BarcodeScannerOptions.Builder()
            .setBarcodeFormats(com.google.mlkit.vision.barcode.Barcode.FORMAT_QR_CODE)
            .build(),
    )
    private var provider: ProcessCameraProvider? = null

    fun attach(
        context: android.content.Context,
        lifecycleOwner: androidx.lifecycle.LifecycleOwner,
        onToken: (String) -> Unit,
        onError: () -> Unit,
    ): PreviewView {
        val previewView = PreviewView(context)
        val analyzer = ImageAnalysis.Analyzer { proxy ->
            val media = proxy.image
            if (media == null) {
                proxy.close()
                return@Analyzer
            }
            val input = com.google.mlkit.vision.common.InputImage.fromMediaImage(media, proxy.imageInfo.rotationDegrees)
            scanner.process(input)
                .addOnSuccessListener { barcodes ->
                    barcodes.firstOrNull()?.rawValue?.let(onToken)
                }
                .addOnCompleteListener { proxy.close() }
        }
        ProcessCameraProvider.getInstance(context).addListener({
            try {
                val cameraProvider = ProcessCameraProvider.getInstance(context).get()
                provider = cameraProvider
                val preview = Preview.Builder().build().also { it.setSurfaceProvider(previewView.surfaceProvider) }
                val analysis = ImageAnalysis.Builder()
                    .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                    .build()
                    .also { it.setAnalyzer(executor, analyzer) }
                cameraProvider.unbindAll()
                cameraProvider.bindToLifecycle(lifecycleOwner, CameraSelector.DEFAULT_BACK_CAMERA, preview, analysis)
            } catch (_: Exception) {
                onError()
            }
        }, ContextCompat.getMainExecutor(context))
        return previewView
    }

    fun detach() {
        runCatching { provider?.unbindAll() }
        executor.shutdown()
        scanner.close()
    }
}
