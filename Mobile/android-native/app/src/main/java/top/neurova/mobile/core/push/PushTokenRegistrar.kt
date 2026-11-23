package top.neurova.mobile.core.push

import android.content.Context
import com.google.firebase.messaging.FirebaseMessaging
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import top.neurova.mobile.core.AppRuntime
import java.util.UUID
import kotlin.coroutines.resume

/**
 * FCM 推送令牌注册（计划批三 B7 遗留清偿）：令牌就绪且用户已登录时上报
 * ``PUT /mobile/push/push-tokens``（服务端 push_store 单源）。
 *
 * Firebase 未配置（缺 google-services.json）时 [fcmToken] 如实返回 null——
 * App 零崩溃，推送通道在凭据到位后自动生效，不引入第二种注册路径。
 */
object PushTokenRegistrar {

    private const val PREF_DEVICE_ID = "neurova.push.device_id"

    /** 已登录且拿到 FCM 令牌 → 上报并返回 true；其余情况返回 false（不抛出）。 */
    suspend fun registerIfNeeded(context: Context, runtime: AppRuntime): Boolean {
        if (runtime.auth.user == null) {
            return false
        }
        val token = fcmToken() ?: return false
        val body = JsonObject(
            mapOf(
                "platform" to JsonPrimitive("android"),
                "push_token" to JsonPrimitive(token),
                "device_id" to JsonPrimitive(deviceId(context, runtime)),
            ),
        )
        runtime.http.putJson("/mobile/push/push-tokens", body)
        return true
    }

    /** FCM 令牌：Firebase 未初始化（缺配置文件）返回 null，不抛出。 */
    private suspend fun fcmToken(): String? = try {
        suspendCancellableCoroutine { cont ->
            FirebaseMessaging.getInstance().token
                .addOnSuccessListener { cont.resume(it) }
                .addOnFailureListener { cont.resume(null) }
                .addOnCanceledListener { cont.cancel() }
        }
    } catch (e: Exception) {
        null
    }

    /** 稳定设备号：首用生成 UUID 并持久化（与配对身份解耦，注销令牌时仍可指认设备）。 */
    private fun deviceId(context: Context, runtime: AppRuntime): String {
        val existing = runtime.preferences.readString(PREF_DEVICE_ID)
        if (!existing.isNullOrBlank()) {
            return existing
        }
        val fresh = UUID.randomUUID().toString()
        runtime.preferences.writeString(PREF_DEVICE_ID, fresh)
        return fresh
    }
}
