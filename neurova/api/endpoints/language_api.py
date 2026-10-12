# -*- coding: utf-8 -*-
"""语言面 HTTP 读面（台账 §6-145 裁定乙：先接读面 + 补 `UserLanguagePreference` 落盘，不引入审批）。

## 这个文件存在的理由：把两条断链接上

- `UserLanguagePreference` 此前只写内存，且 `get_language_manager()` 全仓零调用点——
  「用户选了什么语言」在后台既不存在也留不住。这里给它一个**只有登录态能决定属主**的面。
- `save_external_translations()` 写进去的条目一律 `is_approved=False`，而内置读路
  `get_translation()` 只认已审条目，仓内又没有审批动作 ⇒ 写完没人读得出来。
  裁定是「**不引入审批**」，所以这里补的不是审批，而是一条**如实标未审**的读路
  （`/overlay`）：`approved` 与 `translator` 原样给出，读的人看得见状态。
  内置那条门一寸不动——判据 `testTheBuiltinReadFaceStillRefusesUnapprovedEntries` 专门钉它。

## 四条不放宽的口径

1. **语言码单点**：归一只走 `Language.normalizeTag`/`from_str`。本文件里不许出现
   `split("-")` 这类私藏一刀（§6-145 拆掉的就是这个形态），AST 判据钉住。
2. **属主只从登录态取**：请求体 `extra="forbid"`，`user_id` 多写一个键就 422——
   与渠道身份那条「面板没有替他人绑的入口」同口径。
3. **不识别就点名**：`klingon` 这类码回 400 并把坏值写进拒因。回 200 空列表是最坏形态：
   打错一个字母的人会以为自己那套语言没文案，而这个读数永远不会自己变红。
4. **写面不放宽门**：覆盖层的写入是**管理员**动作（未审内容进 UI 的入口，
   普通用户可写＝任意人给所有人的界面改文案）。
"""

from __future__ import annotations

from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path as PathParam, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from neurova.api.auth import get_current_user
from neurova.api.deps import require_admin
from neurova.core.logger import get_logger
from neurova.language import manager as languageManagerModule
from neurova.language.models import Language, UserLanguagePreference

logger = get_logger(__name__)

router = APIRouter()

#: 命名空间会变成文件名（`manager.save_external_translations` 用 `f"{namespace}.json"`），
#: 所以它先过路径安全门，不能原样拼路径。
_UNSAFE_NAMESPACE_MARKS = ("/", "\\", "?", "#", "\x00")


def _manager():
    """取用经**模块属性**而不是把函数名拷进来。

    `from neurova.language.manager import get_language_manager` 会让测试替身打在另一个
    对象上（写侧与路由实例不同源那一族，§6-155 实测过：门看着没咬住，其实是替换没生效）。
    """
    return languageManagerModule.get_language_manager()


def _userIdOr401(current_user: Dict[str, Any]) -> str:
    user_id = str(current_user.get("user_id") or current_user.get("neuser_id") or "")
    if not user_id or user_id == "unknown":
        # 身份取空却不拒，就会把所有人的偏好写进同一个匿名桶（§6-148 那一族空属主形态）
        raise HTTPException(status_code=401, detail="无法确定当前用户，未写入语言偏好")
    return user_id


def _normalizeTagOr400(tag: Any, field_name: str) -> Language:
    """语言码→枚举的唯一入口；不识别点名到拒因里。"""
    normalized = Language.normalizeTag(tag)
    if normalized is None:
        raise HTTPException(
            status_code=400,
            detail="无法识别的语言码：%r（字段 %s）——本仓的归一口径在 Language.normalizeTag，"
                   "不接受在此之外补写的那一刀" % (tag, field_name))
    return normalized


def _safeNamespace(namespace: str) -> str:
    if (not namespace or namespace in (".", "..") or namespace.startswith(".")
            or any(mark in namespace for mark in _UNSAFE_NAMESPACE_MARKS)):
        raise HTTPException(
            status_code=400,
            detail="非法的译文命名空间：%r（命名空间会变成数据根下的文件名，"
                   "路径分隔、点开头与空值一律拒）" % namespace)
    return namespace


class PreferenceUpdate(BaseModel):
    """本人语言偏好更新——**没有 user_id 这个口**，属主只从登录态取。"""

    model_config = ConfigDict(extra="forbid")

    primary_language: str = Field(..., description="首选语言，接受 `zh`/`zh-CN` 这一族标签")
    secondary_languages: List[str] = Field(default_factory=list, description="次选语言列表")
    fallback_language: Optional[str] = Field(default=None, description="回退语言")
    auto_detect: Optional[bool] = Field(default=None,
                                        description="是否跟随浏览器/客户端检测；"
                                                    "「自动检测」这件事由本字段承载，"
                                                    "不是把 `auto` 当语言")


class OverlayUpdate(BaseModel):
    """覆盖层写入：`{翻译键: {语言码: 文案}}`，与 manager 的落盘格式同形。"""

    model_config = ConfigDict(extra="forbid")

    translations: Dict[str, Dict[str, str]] = Field(
        ..., description="例如 {\"save\": {\"zh-CN\": \"保存\"}}")


#: 「这个用户没设过偏好时该是什么」不另抄一份——就取数据类自己的默认值。
#: 端点里再写一遍 `Language.ENGLISH` 之类的字面量，就是第二个默认值出处（教义第 6 条），
#: 而两份默认值漂移时，坏的是"面板显示的"与"存下来的"不是同一件事。
_DEFAULT_PREFERENCE = UserLanguagePreference(user_id="__defaults__")


def _preferenceView(user_id: str, preference: Optional[UserLanguagePreference]) -> Dict[str, Any]:
    """把偏好投影成读数；没设过的人拿到的是**数据类自己的默认值**并如实标 default。"""
    effective = preference or _DEFAULT_PREFERENCE
    return {
        "user_id": user_id,
        "configured": preference is not None,
        "source": "user" if preference is not None else "default",
        "primary_language": effective.primary_language.value,
        "secondary_languages": [lang.value for lang in effective.secondary_languages],
        "fallback_language": effective.fallback_language.value,
        "auto_detect": effective.auto_detect,
        "updated_at": effective.updated_at if preference is not None else None,
    }


@router.get("/preferences/mine")
async def getMyPreference(
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """本人的语言偏好（**只读**：没设过就报未设，不替用户建一条，也不落文件）。"""
    user_id = _userIdOr401(current_user)
    preference = _manager().get_user_preference(user_id)

    return {"code": 0, "message": "success", "data": _preferenceView(user_id, preference)}


@router.put("/preferences/mine")
async def setMyPreference(
    request: Request,
    body: PreferenceUpdate,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """写入本人的语言偏好：内存与盘同成或同败，盘没写成就不回 200。"""
    user_id = _userIdOr401(current_user)

    primary = _normalizeTagOr400(body.primary_language, "primary_language")
    secondary = [_normalizeTagOr400(tag, "secondary_languages")
                 for tag in body.secondary_languages]
    fallback = (None if body.fallback_language is None
                else _normalizeTagOr400(body.fallback_language, "fallback_language"))

    existing = _manager().get_user_preference(user_id)
    # 没给的字段沿用"现值，没有现值就用数据类自己的默认值"——两处都不在本文件重抄字面量
    fallbackLanguage = (
        fallback if fallback is not None
        else existing.fallback_language if existing
        else _DEFAULT_PREFERENCE.fallback_language)
    autoDetect = (
        body.auto_detect if body.auto_detect is not None
        else existing.auto_detect if existing
        else _DEFAULT_PREFERENCE.auto_detect)

    try:
        preference = UserLanguagePreference(
            user_id=user_id,
            primary_language=primary,
            secondary_languages=secondary,
            fallback_language=fallbackLanguage,
            auto_detect=autoDetect,
            # 首次写入时**不给** created_at，让 dataclass 的默认工厂取"现在"；
            # 给 `_DEFAULT_PREFERENCE.created_at` 会把导入那一刻冻成所有人的创建时间。
            **({"created_at": existing.created_at} if existing else {}),
        )
    except ValueError as e:
        # `auto` 当首选/回退语言会在构造点被拒（`models.py`）——那是 400，不是 500
        raise HTTPException(status_code=400, detail=str(e))

    view = dict(_preferenceView(user_id, preference))
    view["requested_tag"] = body.primary_language

    if not _manager().set_user_preference(user_id, preference):
        raise HTTPException(
            status_code=500,
            detail="语言偏好未能落盘（内存已回滚）——不拿「内存里已经有了」向用户承诺已保存")

    logger.info("用户语言偏好已保存：user=%s language=%s", user_id, preference.primary_language.value)
    return {"code": 0, "message": "success", "data": view}


@router.get("/overlay")
async def getOverlay(
    request: Request,
    language: Annotated[str, Query(description="语言标签，接受 `zh`/`zh-CN` 这一族")],
    namespace: Annotated[str, Query(description="译文命名空间，默认 default")] = "default",
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """覆盖层读面：外部/用户上传的译文，**含未审条目并如实标出状态**。

    与 `get_translation()` 的分工：那条是内置读路（只认已审），这里是"用户/运营自己
    补的那一层"——裁定没有引入审批，所以未审的内容不冒充成已审，而是把状态交出去。
    """
    resolved = _normalizeTagOr400(language, "language")
    safeNamespace = _safeNamespace(namespace)
    entries = _manager().overlayEntries(safeNamespace, resolved)

    return {
        "code": 0,
        "message": "success",
        "data": {
            "namespace": safeNamespace,
            "requested_tag": language,
            "resolved_language": resolved.value,
            "entries": [
                {
                    "key": item.key,
                    "value": item.value,
                    "approved": bool(item.is_approved),
                    "translator": item.translator,
                }
                for item in entries
            ],
            "unapproved_count": sum(1 for item in entries if not item.is_approved),
        },
    }


@router.put("/overlay/{namespace}")
async def putOverlay(
    request: Request,
    namespace: Annotated[str, PathParam(description="译文命名空间（落盘文件名）")],
    body: OverlayUpdate,
    current_user: Dict[str, Any] = Depends(require_admin()),
):
    """覆盖层写面（管理员）：把 `{key: {tag: 文案}}` 交给 manager 的同一份校验与落盘。

    拒因来自 `LanguageManager.rejectedLanguageTags` 那一份单点——本文件不重抄校验循环，
    否则同一件事在两处各写一遍、先漂移的一定是"拒因文本"这种没人对着读的东西。
    """
    safeNamespace = _safeNamespace(namespace)
    rejected = _manager().rejectedLanguageTags(body.translations)
    if rejected:
        raise HTTPException(
            status_code=400,
            detail="译文库整批拒收，不识别的语言码：%s" % (
                ", ".join("%s=%r" % (key, tag) for key, tag in rejected),))

    if not _manager().save_external_translations(safeNamespace, body.translations):
        raise HTTPException(
            status_code=500,
            detail="译文覆盖层未能落盘（内存未写入或已回滚）——见服务端日志的拒收/失败原因")

    logger.info("译文覆盖层已保存：namespace=%s by=%s", safeNamespace,
                current_user.get("user_id"))
    return {"code": 0, "message": "success",
            "data": {"namespace": safeNamespace,
                     "keys": sorted(body.translations.keys()),
                     "approved": False}}
