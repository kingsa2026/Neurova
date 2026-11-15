package top.neurova.mobile.feature.profile

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.sp
import top.neurova.mobile.ui.components.PageHeader
import top.neurova.mobile.ui.theme.LocalNeurovaColors

/** Tab5 我的：个人/服务器档案/模型/管理员域（F10/F11/F14–F17）在我的批次接线。 */
@Composable
fun ProfileTabScreen() {
    val palette = LocalNeurovaColors.current
    Column(modifier = Modifier.fillMaxSize()) {
        PageHeader(title = "我的", subtitle = "服务器 · 模型 · 管理")
        Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            Text("个人域建设中", fontSize = 12.sp, color = palette.textLow)
        }
    }
}
