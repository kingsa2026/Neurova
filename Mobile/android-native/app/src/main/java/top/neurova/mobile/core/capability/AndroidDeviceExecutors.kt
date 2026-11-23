package top.neurova.mobile.core.capability

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.BatteryManager
import android.os.Build
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonPrimitive
import java.util.Locale

/**
 * 设备桥能力执行器的安卓实现（2026-11-23 计划卡 A3）。
 *
 * 每个执行器只做「取参 → 调系统 API → 回结构化结局」；失败不吞——异常上抛由
 * 派发器统一转 executor_error 回执，或在此转更精确的错误码。框架类依赖使这些
 * 执行器只能上真机/仪器验；纯逻辑（路由/去重/后台闸）在 DeviceCommandDispatcher
 * 用 JVM 测试钉住。
 */
object AndroidDeviceExecutors {

    fun all(context: Context): List<DeviceActionExecutor> = listOf(
        OpenUrlExecutor(context),
        OpenAppExecutor(context),
        ClipboardReadExecutor(context),
        ClipboardWriteExecutor(context),
        AppListExecutor(context),
        DeviceEnvExecutor(context),
        ScreenExecutors.ScreenObserveExecutor(),
        ScreenExecutors.ScreenGestureExecutor(),
        top.neurova.mobile.core.notification.NotificationReadExecutor(),
    )

    fun text(payload: JsonObject, key: String): String =
        payload[key]?.jsonPrimitive?.content.orEmpty()
}

/** open_url：系统浏览器/默认打开方式打开 http/https 地址 */
class OpenUrlExecutor(private val context: Context) : DeviceActionExecutor {
    override val action = "open_url"

    override suspend fun execute(payload: JsonObject): ExecuteOutcome {
        val url = AndroidDeviceExecutors.text(payload, "url").trim()
        if (!url.lowercase(Locale.ROOT).startsWith("http://") &&
            !url.lowercase(Locale.ROOT).startsWith("https://")
        ) {
            return ExecuteOutcome.error("missing_params", "url 必须是 http/https 地址")
        }
        val intent = Intent(Intent.ACTION_VIEW, Uri.parse(url))
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        context.startActivity(intent)
        return ExecuteOutcome.ok(JsonObject(mapOf("url" to JsonPrimitive(url))))
    }
}

/** open_app：包名直拉 launch intent；应用名则对可见主入口做包含匹配 */
class OpenAppExecutor(private val context: Context) : DeviceActionExecutor {
    override val action = "open_app"

    override suspend fun execute(payload: JsonObject): ExecuteOutcome {
        val app = AndroidDeviceExecutors.text(payload, "app").trim()
        if (app.isEmpty()) {
            return ExecuteOutcome.error("missing_params", "app 必须是应用名或包名")
        }
        val pm = context.packageManager
        val launchIntent = pm.getLaunchIntentForPackage(app)
            ?: resolveByLabel(pm, app)
            ?: return ExecuteOutcome.error(
                "app_not_found",
                "未找到可打开的应用：$app",
            )
        launchIntent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        context.startActivity(launchIntent)
        return ExecuteOutcome.ok(JsonObject(mapOf("app" to JsonPrimitive(app))))
    }

    private fun resolveByLabel(pm: android.content.pm.PackageManager, query: String): Intent? {
        val main = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER)
        val candidates = pm.queryIntentActivities(main, 0)
        val lowered = query.lowercase(Locale.ROOT)
        val hit = candidates.firstOrNull {
            it.loadLabel(pm).toString().lowercase(Locale.ROOT).contains(lowered) ||
                it.activityInfo.packageName.lowercase(Locale.ROOT) == lowered
        } ?: return null
        return pm.getLaunchIntentForPackage(hit.activityInfo.packageName)
    }
}

/** clipboard_read：读主剪贴板文本（空剪贴板回空串，不报错） */
class ClipboardReadExecutor(private val context: Context) : DeviceActionExecutor {
    override val action = "clipboard_read"

    override suspend fun execute(payload: JsonObject): ExecuteOutcome {
        val manager = context.getSystemService(ClipboardManager::class.java)
        val text = manager.primaryClip?.getItemAt(0)?.text?.toString().orEmpty()
        return ExecuteOutcome.ok(JsonObject(mapOf("text" to JsonPrimitive(text))))
    }
}

/** clipboard_write：写主剪贴板文本 */
class ClipboardWriteExecutor(private val context: Context) : DeviceActionExecutor {
    override val action = "clipboard_write"

    override suspend fun execute(payload: JsonObject): ExecuteOutcome {
        val text = AndroidDeviceExecutors.text(payload, "text")
        if (text.isEmpty()) {
            return ExecuteOutcome.error("missing_params", "text 必须是非空字符串")
        }
        val manager = context.getSystemService(ClipboardManager::class.java)
        manager.setPrimaryClip(ClipData.newPlainText("neurova", text))
        return ExecuteOutcome.ok()
    }
}

/** app_list：可交互主入口应用清单（名称+包名，按名称排序） */
class AppListExecutor(private val context: Context) : DeviceActionExecutor {
    override val action = "app_list"

    override suspend fun execute(payload: JsonObject): ExecuteOutcome {
        val pm = context.packageManager
        val main = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER)
        val apps = pm.queryIntentActivities(main, 0)
            .map { info ->
                JsonObject(
                    mapOf(
                        "label" to JsonPrimitive(info.loadLabel(pm).toString()),
                        "package" to JsonPrimitive(info.activityInfo.packageName),
                    ),
                )
            }
            .sortedBy { it["label"]?.jsonPrimitive?.content.orEmpty() }
        return ExecuteOutcome.ok(JsonObject(mapOf("apps" to JsonArray(apps))))
    }
}

/** device_env：电量/充电态、系统版本、屏幕、语言区域、网络连通性快照 */
class DeviceEnvExecutor(private val context: Context) : DeviceActionExecutor {
    override val action = "device_env"

    override suspend fun execute(payload: JsonObject): ExecuteOutcome {
        val battery = context.registerReceiver(null, android.content.IntentFilter(Intent.ACTION_BATTERY_CHANGED))
        val level = battery?.getIntExtra(BatteryManager.EXTRA_LEVEL, -1) ?: -1
        val scale = battery?.getIntExtra(BatteryManager.EXTRA_SCALE, -1) ?: -1
        val plugged = battery?.getIntExtra(BatteryManager.EXTRA_PLUGGED, 0) ?: 0
        val metrics = context.resources.displayMetrics
        val connectivity = context.getSystemService(android.net.ConnectivityManager::class.java)
        val capabilities = connectivity?.getNetworkCapabilities(connectivity.activeNetwork)
        val data = JsonObject(
            mapOf(
                "battery" to JsonPrimitive(if (scale > 0) level.toDouble() / scale else -1.0),
                "charging" to JsonPrimitive(plugged != 0),
                "os_version" to JsonPrimitive(Build.VERSION.RELEASE),
                "sdk_int" to JsonPrimitive(Build.VERSION.SDK_INT),
                "screen" to JsonPrimitive("${metrics.widthPixels}x${metrics.heightPixels}"),
                "density" to JsonPrimitive(metrics.density.toDouble()),
                "locale" to JsonPrimitive(Locale.getDefault().toLanguageTag()),
                "network_online" to JsonPrimitive(
                    capabilities?.hasCapability(android.net.NetworkCapabilities.NET_CAPABILITY_INTERNET) == true,
                ),
            ),
        )
        return ExecuteOutcome.ok(data)
    }
}
