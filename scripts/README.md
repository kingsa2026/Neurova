# scripts/ 目录说明

本目录脚本不进 CI 门禁；被流水线或守卫消费的脚本以 `.cnb.yml`、`.github/workflows/ci.yml`
与 `tests/` 中的实际引用为准。以下脚本为零引用的**手动工具**，按需手工执行、不自动触发：

- `generate_tts_previews.py` —— 手动工具：预生成 TTS 试听静态文件（`/tts-preview/`，
  前端音色试听按钮依赖；改音色清单后手动重跑）。
- `knowledge_concurrency_benchmark.py` —— 手动工具：知识库并发基准压测（调参排查时手工运行）。
- `desktop/gen_installer_art.py` —— 手动工具：生成桌面安装器美术资产
  （`NeurUI/src-tauri/installer-wpf/`，改视觉素材时手动重跑）。
