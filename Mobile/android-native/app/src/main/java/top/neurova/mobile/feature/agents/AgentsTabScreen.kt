package top.neurova.mobile.feature.agents

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

/** Tab3 智能体：列表与详情（F7/F8）在智能体批次接线，本屏先落页头与诚实空态。 */
@Composable
fun AgentsTabScreen() {
    val palette = LocalNeurovaColors.current
    Column(modifier = Modifier.fillMaxSize()) {
        PageHeader(title = "智能体", subtitle = "Agent 中心")
        Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            Text("智能体域建设中", fontSize = 12.sp, color = palette.textLow)
        }
    }
}
