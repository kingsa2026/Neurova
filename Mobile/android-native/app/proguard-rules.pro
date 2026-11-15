# kotlinx-serialization：保留序列化器与可序列化数据类
-keepattributes *Annotation*, InnerClasses
-dontnote kotlinx.serialization.AnnotationsKt
-keepclassmembers class kotlinx.serialization.json.** { *** Companion; }
-keepclasseswithmembers class kotlinx.serialization.json.** { kotlinx.serialization.KSerializer serializer(...); }
-keep,includedescriptorclasses class top.neurova.mobile.**$$serializer { *; }
-keepclassmembers class top.neurova.mobile.** { *** Companion; }
-keepclasseswithmembers class top.neurova.mobile.** { kotlinx.serialization.KSerializer serializer(...); }

# OkHttp / Conscrypt 平台探测的告警降噪（不影响运行）
-dontwarn okhttp3.internal.platform.**
-dontwarn org.conscrypt.**
-dontwarn org.bouncycastle.**
-dontwarn org.openjsse.**
