package top.neurova.mobile.feature.auth

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.launch
import top.neurova.mobile.core.AppRuntime

/** 登录编排：凭 AuthStore 完成 JWT 换发；成功/失败回调驱屏（失败文案取后端 detail） */
class LoginViewModel(private val runtime: AppRuntime) : ViewModel() {

    fun login(username: String, password: String, onSuccess: () -> Unit, onFailure: (String) -> Unit) {
        viewModelScope.launch {
            runCatching { runtime.auth.login(username, password) }
                .onSuccess { onSuccess() }
                .onFailure { failure ->
                    onFailure(
                        when (failure) {
                            is LoginRejected -> failure.message ?: "登录失败"
                            is top.neurova.mobile.core.net.ChannelHttpException -> failure.detail.ifBlank { "登录失败（HTTP ${failure.code}）" }
                            else -> "网络不可达：请检查服务器档案与内网连接"
                        },
                    )
                }
        }
    }

    companion object {
        fun factory(runtime: AppRuntime): ViewModelProvider.Factory = object : ViewModelProvider.Factory {
            @Suppress("UNCHECKED_CAST")
            override fun <T : ViewModel> create(modelClass: Class<T>): T = LoginViewModel(runtime) as T
        }
    }
}
