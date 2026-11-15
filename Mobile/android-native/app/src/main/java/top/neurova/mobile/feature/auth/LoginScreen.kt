package top.neurova.mobile.feature.auth

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Lock
import androidx.compose.material.icons.outlined.Person
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.viewmodel.compose.viewModel
import top.neurova.mobile.ui.components.LocalAppRuntime
import top.neurova.mobile.ui.theme.LocalNeurovaColors

/**
 * F1 登录（主通道：账号密码 → JWT；服务器档案不匹配在此切换，见设计方案 §5.1）。
 * 登录成功后进入配对检查（未配对 → F2），再入五 Tab。
 */
@Composable
fun LoginScreen(onLoginSuccess: () -> Unit, onOpenPairing: () -> Unit, onOpenServers: () -> Unit) {
    val palette = LocalNeurovaColors.current
    val runtime = LocalAppRuntime.current
    val viewModel: LoginViewModel = viewModel(factory = LoginViewModel.factory(runtime))

    var username by rememberSaveable { mutableStateOf("") }
    var password by rememberSaveable { mutableStateOf("") }
    var errorMessage by rememberSaveable { mutableStateOf<String?>(null) }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(horizontal = 26.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Spacer(modifier = Modifier.weight(1f))
        BrandGlyph()
        Spacer(modifier = Modifier.height(8.dp))
        Text("Neurova", fontSize = 30.sp, fontWeight = FontWeight.Bold, color = palette.textHi)
        Text("你的私有 AI 工作台", fontSize = 13.sp, color = palette.textLow)
        Spacer(modifier = Modifier.height(30.dp))
        OutlinedTextField(
            value = username,
            onValueChange = { username = it; errorMessage = null },
            modifier = Modifier.fillMaxWidth(),
            leadingIcon = { Icon(Icons.Outlined.Person, contentDescription = null) },
            placeholder = { Text("用户名", color = palette.textLow) },
            singleLine = true,
            shape = RoundedCornerShape(14.dp),
        )
        Spacer(modifier = Modifier.height(12.dp))
        OutlinedTextField(
            value = password,
            onValueChange = { password = it; errorMessage = null },
            modifier = Modifier.fillMaxWidth(),
            leadingIcon = { Icon(Icons.Outlined.Lock, contentDescription = null) },
            placeholder = { Text("密码", color = palette.textLow) },
            singleLine = true,
            visualTransformation = PasswordVisualTransformation(),
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
            shape = RoundedCornerShape(14.dp),
        )
        errorMessage?.let { message ->
            Spacer(modifier = Modifier.height(8.dp))
            Text(message, fontSize = 12.sp, color = palette.danger)
        }
        Spacer(modifier = Modifier.height(20.dp))
        Button(
            onClick = {
                viewModel.login(
                    username = username,
                    password = password,
                    onSuccess = onLoginSuccess,
                    onFailure = { errorMessage = it },
                )
            },
            enabled = username.isNotBlank() && password.isNotBlank() && !runtime.auth.loading,
            modifier = Modifier
                .fillMaxWidth()
                .height(48.dp),
            shape = RoundedCornerShape(14.dp),
            colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.primary),
        ) {
            if (runtime.auth.loading) {
                CircularProgressIndicator(modifier = Modifier.size(20.dp), strokeWidth = 2.dp)
            } else {
                Text("登 录", fontSize = 15.5.sp, fontWeight = FontWeight.SemiBold)
            }
        }
        Spacer(modifier = Modifier.height(22.dp))
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .clickable { onOpenServers() }
                .padding(vertical = 10.dp, horizontal = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.Center,
        ) {
            Box(
                modifier = Modifier
                    .size(8.dp)
                    .background(palette.success, CircleShape),
            )
            Spacer(modifier = Modifier.size(8.dp))
            Text(
                "当前服务器 ${runtime.servers.active?.baseUrl.orEmpty()} · 档案管理",
                fontSize = 12.sp,
                color = palette.textMid,
            )
        }
        Spacer(modifier = Modifier.weight(1.4f))
    }
}

/** 品牌四芒星：Canvas 矢量绘制，品牌渐变着色（不用字符/emoji 充当图形） */
@Composable
private fun BrandGlyph() {
    val palette = LocalNeurovaColors.current
    Canvas(modifier = Modifier.size(64.dp)) {
        val star = Path().apply {
            val cx = size.width / 2f
            val cy = size.height / 2f
            val long = size.width * 0.42f
            val short = size.width * 0.12f
            moveTo(cx, cy - long)
            quadraticTo(cx + short, cy - short, cx + long, cy)
            quadraticTo(cx + short, cy + short, cx, cy + long)
            quadraticTo(cx - short, cy + short, cx - long, cy)
            quadraticTo(cx - short, cy - short, cx, cy - long)
            close()
        }
        drawPath(star, palette.brandGradient)
        drawCircle(
            brush = palette.brandGradient,
            radius = size.width * 0.05f,
            center = Offset(x = size.width * 0.72f, y = size.height * 0.28f),
        )
    }
}
