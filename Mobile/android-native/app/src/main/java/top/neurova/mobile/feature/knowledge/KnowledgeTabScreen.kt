package top.neurova.mobile.feature.knowledge

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

/** Tab4 知识：检索/导入/图谱速览（F9/F12/F13/F18）在知识批次接线，本屏先落页头与诚实空态。 */
@Composable
fun KnowledgeTabScreen() {
    val palette = LocalNeurovaColors.current
    Column(modifier = Modifier.fillMaxSize()) {
        PageHeader(title = "知识", subtitle = "知识库轻量子集")
        Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            Text("知识域建设中", fontSize = 12.sp, color = palette.textLow)
        }
    }
}
