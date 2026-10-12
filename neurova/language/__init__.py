"""
Neurova language - 多语言与国际化的后端侧

这里管的是**两件事**，都不是"界面文案的完整清单"：

1. `Language` 枚举 + `normalizeTag()`：仓内流通的语言码（`zh-CN` 这一族带区域后缀的
   BCP-47 标签）到枚举的**唯一归一口径**。枚举本身有 32 个成员（含 `auto`），
   而前端 `NeurUI/src/i18n/locales/` 只交付 **11 种** locale——两者不是同一件事，
   原先这句"支持11种语言"写的其实是前端那份清单，落在包 docstring 上就成了名实不符
   （§6-160 改到实况）。
2. `LanguageManager`：内置译文库、外部/用户覆盖层（`is_approved=False`，
   经 `/api/v1/language/overlay` 如实读出）、以及**落盘的**用户语言偏好。

前端那一侧的 11 份 locale、语言下拉与覆盖层合并见 `NeurUI/src/i18n/index.ts`
与 `NeurUI/src/stores/app.ts`；HTTP 面见 `neurova/api/endpoints/language_api.py`。
"""

from neurova.language.models import Language

__all__ = ["Language"]

