package top.neurova.mobile.feature.chat

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

/** Tab1 对话：会话列表与聊天页（F4/F5/F6）在对话域批次接线，本屏先落页头与诚实空态。 */
@Composable
fun ChatTabScreen() {
    val palette = LocalNeurovaColors.current
    Column(modifier = Modifier.fillMaxSize()) {
        PageHeader(title = "对话", subtitle = "与 PC 端同源")
        Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            Text("会话域建设中", fontSize = 12.sp, color = palette.textLow)
        }
    }
}
