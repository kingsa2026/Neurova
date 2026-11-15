package top.neurova.mobile.feature.workbench

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

/** Tab2 工作台：仪表盘（F3）在工作台批次接线，本屏先落页头与诚实空态。 */
@Composable
fun WorkbenchTabScreen() {
    val palette = LocalNeurovaColors.current
    Column(modifier = Modifier.fillMaxSize()) {
        PageHeader(title = "工作台", subtitle = "仪表盘 · 真数据")
        Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            Text("仪表盘建设中", fontSize = 12.sp, color = palette.textLow)
        }
    }
}
