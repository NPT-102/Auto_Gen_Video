"""Small deterministic fallback from a narration scene to whiteboard objects.

An upstream LLM can supply `whiteboard_plan` with a richer scene. This module
keeps the Whiteboard engine usable without an image API: it selects a legible
object vocabulary and known-good locations from the script's subject and type.
"""
from __future__ import annotations

from .spec import Spec


def _text(scene, title: str) -> str:
    extra = scene.model_extra or {}
    return " ".join([title, scene.say, str(extra.get("heading", "")), str(extra.get("question", ""))]).lower()


def _security() -> dict:
    return {"objects": [
        {"kind": "laptop", "x": .08, "y": .36, "scale": .90},
        {"kind": "lock", "x": .62, "y": .35, "scale": 1.28, "color": "orange"},
        {"kind": "shield", "x": .58, "y": .60, "scale": 1.16, "color": "green", "checked": True},
        {"kind": "arrow", "x": .48, "y": .50, "to_x": .58, "to_y": .50, "color": "green"},
    ]}


def _network() -> dict:
    return {"objects": [
        {"kind": "laptop", "x": .07, "y": .41, "scale": .78},
        {"kind": "cloud", "x": .42, "y": .30, "scale": 1.25, "color": "blue"},
        {"kind": "server", "x": .68, "y": .43, "scale": 1.05, "color": "blue"},
        {"kind": "arrow", "x": .37, "y": .52, "to_x": .47, "to_y": .45, "color": "blue"},
        {"kind": "arrow", "x": .62, "y": .45, "to_x": .68, "to_y": .51, "color": "blue"},
    ]}


def _money() -> dict:
    return {"objects": [
        {"kind": "chart", "x": .10, "y": .38, "scale": 1.05, "color": "blue"},
        {"kind": "coin", "x": .66, "y": .40, "scale": 1.30, "color": "orange"},
        {"kind": "coin", "x": .76, "y": .59, "scale": .95, "color": "orange"},
        {"kind": "arrow", "x": .52, "y": .58, "to_x": .64, "to_y": .53, "color": "green"},
    ]}


def _checklist(scene_type: str) -> dict:
    objects = [
        {"kind": "bulb", "x": .39, "y": .27, "scale": 1.25, "color": "orange"},
        {"kind": "checklist", "x": .16, "y": .53, "scale": .95},
    ]
    if scene_type == "tip":
        objects.insert(1, {"kind": "shield", "x": .70, "y": .32, "scale": .72, "color": "green", "checked": True})
    return {"objects": objects}


def _compare() -> dict:
    return {"objects": [
        {"kind": "phone", "x": .11, "y": .38, "scale": .90},
        {"kind": "laptop", "x": .53, "y": .46, "scale": .82},
        {"kind": "arrow", "x": .42, "y": .56, "to_x": .52, "to_y": .56, "color": "orange"},
        {"kind": "star", "x": .50, "y": .34, "scale": .80, "color": "blue"},
    ]}


def plan_from_spec(spec: Spec) -> list[dict]:
    """Return one drawable object plan per narration scene."""
    plans = []
    for scene in spec.scenes:
        text, kind = _text(scene, spec.title), scene.type
        if any(word in text for word in ("mật khẩu", "đăng nhập", "bảo mật", "xác thực", "2fa", "otp", "lừa đảo")):
            plan = _security()
        elif any(word in text for word in ("mạng", "internet", "website", "server", "dữ liệu", "đám mây", "dns")):
            plan = _network()
        elif any(word in text for word in ("tiền", "giá", "doanh thu", "lợi nhuận", "đầu tư", "bitcoin", "ngân hàng")):
            plan = _money()
        elif kind == "compare":
            plan = _compare()
        else:
            plan = _checklist(kind)
        plans.append(plan)
    return plans
