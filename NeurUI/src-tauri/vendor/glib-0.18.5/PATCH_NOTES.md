# 本地补丁：glib 0.18.5 → 修复 RUSTSEC-2024-0429

本目录是 crates.io 上 `glib` **0.18.5** 的源码副本，仅含一处改动，用于消除
`VariantStrIter::impl_get` 的未定义行为（GHSA-wrw7-89jp-8q8g）。

## 补丁内容

`src/variant_iter.rs` 的 `impl_get`：出参指针由不可变引用改为可变引用。

```diff
-            let p: *mut libc::c_char = std::ptr::null_mut();
+            let mut p: *mut libc::c_char = std::ptr::null_mut();
             ffi::g_variant_get_child(
                 ...
-                &p,
+                &mut p,
```

## 为什么不用升级

上游在 `glib` 0.20.0 修复，但把 glib 钉在 0.18 的是 Tauri 桌面栈的 **gtk** 层：
wry 0.53–0.57 与 tao 0.34–0.37 的 `gtk` 依赖一律为 `^0.18`，而 `gtk` 0.19 才对应
`glib ^0.22`（gtk 0.19.0 发布于 2026-09-08，wry / tao 至 0.57.0 / 0.37.0 均未采用）。
仓内既不能经 registry 把 glib 抬到修复版，也不能单方面声明 glib 0.20（gtk 的
`glib ^0.18` 约束会失配）——故按上游修复方式就地打补丁。

`[patch.crates-io]` 只替换包的来源，版本保持 0.18.5，因此 gtk `^0.18` 约束不变。

## 退役条件

wry 或 tao 任一正式版把 `gtk` 抬到 `^0.19` → 升级 Tauri 栈到 glib ≥ 0.20，
删除本目录与 `Cargo.toml` 的 `[patch.crates-io]` 段。
守卫 `tests/unit/desktop/test_rust_vendor_patch_guard.py` 会在 gtk 离开 0.18 线时提醒。
