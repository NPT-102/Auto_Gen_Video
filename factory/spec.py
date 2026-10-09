"""Định dạng kịch bản chung (canonical spec) mà cả 5 engine cùng đọc.

Một video = danh sách cảnh. Mỗi cảnh có lời đọc riêng ("say") và phần hình theo loại cảnh:
  title    tiêu đề mở đầu: tag, headline [[chữ, tô_màu], ...], sub, chips
  bullets  danh sách ý: heading, items [{text, cue?}]
  compare  so sánh hai vế: heading, left/right {title, points[]}
  stat     số liệu lớn: heading, stats [{value, label, cue?}]
  flow     sơ đồ tự dàn bố cục (Gemini viết được): heading, groups, nodes, edges, steps — xem factory/flow.py
  diagram  sơ đồ toạ độ soạn tay: diagram, heading, events
  tip      mẹo / câu hỏi: question, answer, answer_cue (+ label, q_label, a_label tuỳ chọn)
  next     kết / tập sau: title, sub (+ label tuỳ chọn)
"cue" là cụm từ trong lời đọc; thành phần tương ứng hiện ra đúng lúc cụm đó được đọc.
Mỗi cảnh có thể thêm "stock": 1–2 từ khoá tiếng Anh tả thứ quay phim được trong lúc đọc cảnh đó (engine
Stock khớp lời tìm clip Pexels theo từng cảnh; thiếu thì chia đều stock_terms chung theo thứ tự).
"""

import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SceneType = Literal["title", "bullets", "compare", "stat", "flow", "diagram", "tip", "next"]

REQUIRED = {
    "title": ["headline"],
    "bullets": ["heading", "items"],
    "compare": ["heading", "left", "right"],
    "stat": ["stats"],
    "flow": ["heading", "nodes"],
    "diagram": ["diagram", "heading"],
    "tip": ["question", "answer"],
    "next": ["title"],
}


_AWS_WORDS = {  # icon AWS chỉ hợp lệ khi nhãn nói đúng về thứ đó (tránh dùng icon AWS làm hình trang trí)
    "users": ["nguoi dung", "user", "khach"], "user": ["nguoi dung", "user", "khach"],
    "client": ["client", "may khach", "may tinh", "trinh duyet", "laptop"], "mobile": ["dien thoai", "mobile", "app"],
    "internet": ["internet"], "server": ["may chu", "server"], "database": ["co so du lieu", "database", "csdl"],
    "office": ["van phong", "office", "tai cho", "on-prem", "onprem", "data center"], "firewall": ["firewall", "tuong lua"],
    "alb": ["load balancer", "alb", "can bang tai"], "nlb": ["load balancer", "nlb", "can bang tai"],
    "elb": ["load balancer", "elb", "can bang tai"], "igw": ["internet gateway", "igw"], "nat": ["nat"],
    "rds": ["rds", "database", "co so du lieu"], "aurora": ["aurora"], "asg": ["auto scaling", "asg"],
    "ec2": ["ec2", "instance", "may chu", "server"], "iam-role": ["role", "iam"], "sts": ["sts"], "mfa": ["mfa"],
}


def _plain(text: str) -> str:
    import unicodedata as u

    text = u.normalize("NFD", str(text)).replace("đ", "d").replace("Đ", "D")
    return "".join(c for c in text if u.category(c) != "Mn").lower().replace("-", " ")


def _check_flow(extra: dict) -> None:
    for n in extra.get("nodes", []) or []:
        icon = str(n.get("icon", ""))
        if icon.startswith("aws:"):
            alias = icon[4:].lower()
            words = _AWS_WORDS.get(alias, [alias.replace("-", " ")])
            label = _plain(n.get("label", ""))
            if not any(w in label for w in words):
                raise ValueError(f"flow: node '{n.get('label')}' dùng icon {icon} nhưng không phải dịch vụ đó — "
                                 "chỉ dùng aws:<name> khi node đúng là dịch vụ AWS ấy, còn lại dùng một emoji phù hợp")
    groups = {g.get("id") for g in extra.get("groups", []) or []}
    nodes = [n.get("id") for n in extra.get("nodes", []) or []]
    if len(nodes) != len(set(nodes)) or None in nodes:
        raise ValueError("flow: id của nodes phải có và không trùng")
    if not 2 <= len(nodes) <= 14:
        raise ValueError("flow: cần 2–14 nodes")
    ids = set(nodes) | groups
    for g in extra.get("groups", []) or []:
        if g.get("parent") and g["parent"] not in groups:
            raise ValueError(f"flow: group '{g.get('id')}' có parent '{g['parent']}' không tồn tại")
    for n in extra.get("nodes", []) or []:
        if n.get("group") and n["group"] not in groups:
            raise ValueError(f"flow: node '{n['id']}' thuộc group '{n['group']}' không tồn tại")
    for e in extra.get("edges", []) or []:
        if e.get("from") not in nodes or e.get("to") not in nodes:
            raise ValueError(f"flow: edge {e.get('from')}→{e.get('to')} trỏ tới node không tồn tại")
    for s in extra.get("steps", []) or []:
        bad = [i for i in (s.get("show", []) or []) + (s.get("focus", []) or []) if i not in ids]
        if bad:
            raise ValueError(f"flow: step '{s.get('cue')}' nhắc tới id không tồn tại {bad}")


class Scene(BaseModel):
    model_config = ConfigDict(extra="allow")
    type: SceneType
    say: str = Field(min_length=2)

    @model_validator(mode="after")
    def _fields(self):
        extra = self.model_extra or {}
        missing = [k for k in REQUIRED[self.type] if not extra.get(k)]
        if missing:
            raise ValueError(f"cảnh '{self.type}' thiếu {missing}")
        if self.type == "flow":
            _check_flow(extra)
        return self


class Spec(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    title: str
    series: str | None = None
    ep: int | None = None
    total: int | None = None
    voice: str = "vi-VN-HoaiMyNeural"
    scenes: list[Scene] = Field(min_length=1)
    diagrams: dict[str, Any] = {}
    stock_terms: list[str] = []          # từ khoá tiếng Anh tìm video nền (MoneyPrinterTurbo)
    description: str = ""                # mô tả khi đăng
    hashtags: list[str] = []
    # bản podcast (văn nói) chỉ MoneyPrinterTurbo dùng: title, say, stock_terms, voice (mai | nhatphong | voice_id)
    podcast: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _diagrams(self):
        for s in self.scenes:
            if s.type == "diagram" and s.model_extra["diagram"] not in self.diagrams:
                raise ValueError(f"sơ đồ '{s.model_extra['diagram']}' chưa được khai báo trong diagrams")
        if self.podcast is not None and len(str(self.podcast.get("say", "")).split()) < 20:
            raise ValueError("podcast.say phải là lời thoại đầy đủ (ít nhất 20 từ)")
        return self

    # --- tiện ích cho các engine ---
    def narration(self) -> str:
        return " ".join(s.say.strip() for s in self.scenes)

    def dump(self) -> dict:
        return self.model_dump(mode="json", exclude_none=True)


def load_spec(path: Path) -> Spec:
    return Spec.model_validate(json.loads(path.read_text(encoding="utf-8")))


def slugify(text: str, max_len: int = 48) -> str:
    text = unicodedata.normalize("NFD", text).replace("đ", "d").replace("Đ", "D")
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    return text[:max_len].strip("-") or "video"


def caption_text(spec: Spec) -> str:
    """Nội dung dán kèm khi đăng: tiêu đề, mô tả, hashtag."""
    head = f"{spec.series} · Tập {spec.ep}: {spec.title}" if spec.series and spec.ep else spec.title
    tags = " ".join(h if h.startswith("#") else f"#{h}" for h in spec.hashtags)
    return "\n\n".join(p for p in (head, spec.description.strip(), tags) if p)
