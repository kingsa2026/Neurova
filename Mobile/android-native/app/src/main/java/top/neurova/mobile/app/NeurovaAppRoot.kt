package top.neurova.mobile.app

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.MenuBook
import androidx.compose.material.icons.automirrored.outlined.MenuBook
import androidx.compose.material.icons.filled.ChatBubble
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.SmartToy
import androidx.compose.material.icons.filled.SpaceDashboard
import androidx.compose.material.icons.outlined.ChatBubbleOutline
import androidx.compose.material.icons.outlined.Person
import androidx.compose.material.icons.outlined.SmartToy
import androidx.compose.material.icons.outlined.SpaceDashboard
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.adaptive.navigationsuite.NavigationSuiteScaffold
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.navigation.NavHostController
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import top.neurova.mobile.feature.admin.AdminEvolutionScreen
import top.neurova.mobile.feature.admin.AdminGroupsScreen
import top.neurova.mobile.feature.admin.AdminUsersScreen
import top.neurova.mobile.feature.aigc.AigcScreen
import top.neurova.mobile.feature.aigc.AigcWorkbenchEntry
import top.neurova.mobile.feature.agents.AgentsTabScreen
import top.neurova.mobile.feature.auth.LoginScreen
import top.neurova.mobile.feature.chat.ChatScreen
import top.neurova.mobile.feature.chat.ChatTabScreen
import top.neurova.mobile.feature.devicebridge.DeviceBridgeScreen
import top.neurova.mobile.feature.knowledge.KnowledgeTabScreen
import top.neurova.mobile.feature.models.ModelsScreen
import top.neurova.mobile.feature.pairing.PairingScreen
import top.neurova.mobile.feature.profile.ProfileTabScreen
import top.neurova.mobile.feature.profile.ServerManageScreen
import top.neurova.mobile.feature.workbench.WorkbenchTabScreen
import top.neurova.mobile.ui.components.LocalAppRuntime
import top.neurova.mobile.ui.theme.LocalNeurovaColors

/** 底部五 Tab（信息架构唯一事实源：安卓端界面布局规划 §02） */
enum class TabDestination(val route: String, val label: String, val outlined: ImageVector, val filled: ImageVector) {
    CHAT("chat", "对话", Icons.Outlined.ChatBubbleOutline, Icons.Filled.ChatBubble),
    WORKBENCH("workbench", "工作台", Icons.Outlined.SpaceDashboard, Icons.Filled.SpaceDashboard),
    AGENTS("agents", "智能体", Icons.Outlined.SmartToy, Icons.Filled.SmartToy),
    KNOWLEDGE("knowledge", "知识", Icons.AutoMirrored.Outlined.MenuBook, Icons.AutoMirrored.Filled.MenuBook),
    PROFILE("profile", "我的", Icons.Outlined.Person, Icons.Filled.Person),
}

/**
 * 入口门控（前置流程一次性：登录 → 配对检查 → 五 Tab；会话恢复走安全存储验活）。
 * 门控为渲染级分支，深链 neurova://pair 由 MainActivity 注入配对仓。
 */
private enum class Gate { BOOTSTRAP, LOGIN, PAIRING, MAIN }

@Composable
fun NeurovaAppRoot() {
    val runtime = LocalAppRuntime.current
    var gate by remember { mutableStateOf(Gate.BOOTSTRAP) }

    LaunchedEffect(Unit) {
        runtime.auth.restore()
        runtime.pairing.restore()
        gate = when {
            runtime.auth.user == null -> Gate.LOGIN
            !runtime.pairing.paired -> Gate.PAIRING
            else -> Gate.MAIN
        }
    }

    when (gate) {
        Gate.BOOTSTRAP -> BootstrapSplash()
        Gate.LOGIN -> LoginScreen(
            onLoginSuccess = {
                gate = if (runtime.pairing.paired) Gate.MAIN else Gate.PAIRING
            },
            onOpenPairing = { gate = Gate.PAIRING },
            onOpenServers = { /* 档案管理页在 P8 接线（F10 服务器与配对） */ },
        )
        Gate.PAIRING -> PairingScreen(
            onPaired = { gate = Gate.MAIN },
        )
        Gate.MAIN -> MainTabsShell()
    }
}

@Composable
private fun BootstrapSplash() {
    val palette = LocalNeurovaColors.current
    Box(modifier = Modifier.fillMaxSize().background(MaterialTheme.colorScheme.background), contentAlignment = Alignment.Center) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Text("Neurova", fontSize = 26.sp, fontWeight = FontWeight.Bold, color = palette.textHi)
            Spacer(modifier = Modifier.height(6.dp))
            Text("正在恢复会话…", fontSize = 12.sp, color = palette.textLow)
        }
    }
}

@Composable
private fun MainTabsShell() {
    val navController = rememberNavController()
    val backStackEntry by navController.currentBackStackEntryAsState()
    val currentRoute = backStackEntry?.destination?.route

    NavigationSuiteScaffold(
        navigationSuiteItems = {
            TabDestination.entries.forEach { tab ->
                item(
                    selected = currentRoute == tab.route,
                    onClick = { openTab(navController, tab) },
                    icon = {
                        Icon(
                            imageVector = if (currentRoute == tab.route) tab.filled else tab.outlined,
                            contentDescription = tab.label,
                        )
                    },
                    label = { Text(tab.label, fontSize = 10.sp) },
                )
            }
        },
    ) {
        val palette = LocalNeurovaColors.current
        Box(
            modifier = Modifier
                .fillMaxSize()
                .background(MaterialTheme.colorScheme.background)
                .background(palette.screenGlow),
        ) {
            NeurovaNavHost(navController)
        }
    }
}

private fun openTab(navController: NavHostController, tab: TabDestination) {
    navController.navigate(tab.route) {
        popUpTo(TabDestination.CHAT.route) { saveState = true }
        launchSingleTop = true
        restoreState = true
    }
}

@Composable
private fun NeurovaNavHost(navController: NavHostController) {
    NavHost(
        navController = navController,
        startDestination = TabDestination.CHAT.route,
    ) {
        composable(TabDestination.CHAT.route) {
            ChatTabScreen(
                onOpenSession = { sessionId, title ->
                    navController.navigate("chat/$sessionId?title=${android.net.Uri.encode(title)}")
                },
            )
        }
        composable(
            route = "chat/{sessionId}?title={title}",
            arguments = listOf(
                navArgument("sessionId") { type = NavType.StringType },
                navArgument("title") {
                    type = NavType.StringType
                    defaultValue = ""
                },
            ),
        ) { entry ->
            ChatScreen(
                sessionId = entry.arguments?.getString("sessionId").orEmpty(),
                initialTitle = entry.arguments?.getString("title").orEmpty(),
                onBack = { navController.popBackStack() },
            )
        }
        composable(TabDestination.WORKBENCH.route) {
            AigcWorkbenchEntry(onOpenAigc = { navController.navigate("workbench/aigc") }) {
                WorkbenchTabScreen()
            }
        }
        composable(TabDestination.AGENTS.route) {
            AgentsTabScreen(onOpenChat = { openTab(navController, TabDestination.CHAT) })
        }
        composable(TabDestination.KNOWLEDGE.route) { KnowledgeTabScreen() }
        composable(TabDestination.PROFILE.route) {
            ProfileTabScreen(
                onOpenServers = { navController.navigate("profile/servers") },
                onOpenModels = { navController.navigate("profile/models") },
                onOpenAdminUsers = { navController.navigate("admin/users") },
                onOpenAdminGroups = { navController.navigate("admin/groups") },
                onOpenAdminEvolution = { navController.navigate("admin/evolution") },
                onOpenDeviceBridge = { navController.navigate("profile/devicebridge") },
            )
        }
        composable("profile/servers") { ServerManageScreen(onBack = { navController.popBackStack() }) }
        composable("profile/models") { ModelsScreen(onBack = { navController.popBackStack() }) }
        composable("profile/devicebridge") { DeviceBridgeScreen(onBack = { navController.popBackStack() }) }
        composable("workbench/aigc") { AigcScreen(onBack = { navController.popBackStack() }) }
        composable("admin/users") { AdminUsersScreen(onBack = { navController.popBackStack() }) }
        composable("admin/groups") { AdminGroupsScreen(onBack = { navController.popBackStack() }) }
        composable("admin/evolution") { AdminEvolutionScreen(onBack = { navController.popBackStack() }) }
    }
}
