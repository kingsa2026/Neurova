"""R3-1 SOM 视觉复活核心（CUA Phase 3 立项 §1）

无 UIA 树桌面（自绘/游戏/远程像素流）的中间档：截图 → 编号标注图 + id2xy。
默认检测器为确定性启发式（边缘 + 连通域），真实 ONNX/OCR 检测器可注入替换。

验收：
1. mark_screenshot 返回 annotated_png_b64 + marks(id/bbox/center/label) + id2xy
2. 编号跨调用稳定（同图同 id，PYTHONHASHSEED 无关——用 md5 非内置 hash）
3. id2xy 中心 == marks.center（点击解算依据）
4. 合成图（两个分离矩形）→ 检出 ≥2 区域
5. detector 可注入（真实模型接入点）
6. 标注图可解码回 PNG（尺寸不变）
"""

import base64
import io

from PIL import Image, ImageDraw

from neurova.computer_use.som import mark_screenshot, stable_id


def _synthetic_png():
    img = Image.new("RGB", (400, 300), "white")
    d = ImageDraw.Draw(img)
    d.rectangle([20, 20, 120, 80], outline="black", width=3, fill="lightblue")
    d.rectangle([250, 180, 360, 260], outline="black", width=3, fill="lightyellow")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class TestMarkScreenshot:
    def test_returns_full_contract(self):
        out = mark_screenshot(_synthetic_png())
        assert "annotated_png_b64" in out
        assert "marks" in out and isinstance(out["marks"], list)
        assert "id2xy" in out and isinstance(out["id2xy"], dict)
        assert len(out["marks"]) >= 2, "两个分离矩形应至少检出 2 区域"

    def test_id2xy_matches_mark_centers(self):
        out = mark_screenshot(_synthetic_png())
        for m in out["marks"]:
            assert tuple(out["id2xy"][str(m["id"])]) == tuple(m["center"])

    def test_mark_shape(self):
        out = mark_screenshot(_synthetic_png())
        m = out["marks"][0]
        assert set(["id", "bbox", "center", "label"]) <= set(m.keys())
        assert len(m["bbox"]) == 4 and len(m["center"]) == 2

    def test_annotated_image_decodes_same_size(self):
        src = _synthetic_png()
        out = mark_screenshot(src)
        img = Image.open(io.BytesIO(base64.b64decode(out["annotated_png_b64"])))
        assert img.size == (400, 300)

    def test_ids_stable_across_calls(self):
        a = mark_screenshot(_synthetic_png())
        b = mark_screenshot(_synthetic_png())
        assert [m["id"] for m in a["marks"]] == [m["id"] for m in b["marks"]], "同图编号必须跨调用一致"

    def test_detector_injectable(self):
        fake = lambda png: [{"bbox": (1, 2, 30, 40), "label": "btn"}]
        out = mark_screenshot(_synthetic_png(), detector=fake)
        assert len(out["marks"]) == 1
        assert out["marks"][0]["bbox"] == [1, 2, 30, 40]
        assert out["marks"][0]["center"] == [15, 21]


class TestStableId:
    def test_deterministic(self):
        assert stable_id(100, 200, "x") == stable_id(100, 200, "x")

    def test_grid_quantization_nearby_same(self):
        # 中心落在同格（grid=8）→ 同 id
        assert stable_id(100, 200, "x") == stable_id(103, 204, "x")

    def test_positive_int(self):
        assert isinstance(stable_id(5, 5, ""), int) and stable_id(5, 5, "") > 0
