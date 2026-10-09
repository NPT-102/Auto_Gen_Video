"""Cảnh "flow": sơ đồ tự dàn bố cục cho mọi chủ đề kiến thức.

Người viết (Gemini hoặc người) chỉ mô tả CẤU TRÚC — nhóm, nút, mũi tên, thứ tự hiện — không cần toạ độ:
  {"type": "flow", "say": "...", "kicker": "...", "heading": "...", "direction": "down" | "right",
   "groups": [{"id": "vpc", "label": "VPC", "kind": "vpc", "parent": null}],
   "nodes":  [{"id": "web", "label": "Máy chủ web", "icon": "aws:ec2", "group": "vpc"}],
   "edges":  [{"from": "users", "to": "web", "label": "HTTPS", "style": "flow"}],
   "steps":  [{"cue": "cụm từ trong lời đọc", "show": ["users", "web"], "focus": ["web"]}]}
icon: "aws:<tên>" (icon AWS chính thức, xem AWS_ICONS) · một emoji bất kỳ (🧠 ⚡ 💰…) · tên icon có sẵn (globe, server…).
group.kind: region · vpc · az · public · private · box (mặc định); group.tone: blue · green · purple · orange · gray · red.
edge.style: solid (mặc định) · flow (luồng dữ liệu chạy) · blocked (bị chặn).

compile_flows() dùng ELK (tools/elk) để tính toạ độ rồi đổi cảnh flow thành cảnh "diagram" mà renderer
HyperFrames/Remotion đã vẽ được: nút hiện dần theo steps, mũi tên hiện khi đủ hai đầu, camera theo bước.
"""

import base64
import hashlib
import json
import subprocess
from functools import lru_cache
from pathlib import Path

from .config import CACHE_DIR, ROOT

ELK_SCRIPT = ROOT / "tools" / "elk" / "layout.mjs"
LAYOUT_CACHE = CACHE_DIR / "layout"

NODE_W, NODE_H = 210, 172        # khung một nút: ô icon 100px + nhãn 2 dòng
TILE = 100
GROUP_PAD = "[top=64,left=22,bottom=22,right=22]"

_AWS = {
    # tính toán
    "ec2": "compute/ec2", "asg": "compute/ec2-auto-scaling", "lambda": "compute/lambda",
    "ecs": "compute/elastic-container-service", "eks": "compute/elastic-kubernetes-service",
    "fargate": "compute/fargate", "ecr": "compute/ec2-container-registry", "beanstalk": "compute/elastic-beanstalk",
    "batch": "compute/batch", "lightsail": "compute/lightsail", "spot": "compute/ec2-spot-instance",
    "ami": "compute/ec2-ami",
    # lưu trữ
    "s3": "storage/simple-storage-service-s3", "glacier": "storage/s3-glacier", "ebs": "storage/elastic-block-store-ebs",
    "efs": "storage/elastic-file-system-efs", "fsx": "storage/fsx", "backup": "storage/backup",
    "snowball": "storage/snowball", "storage-gateway": "storage/storage-gateway",
    # cơ sở dữ liệu
    "rds": "database/rds", "aurora": "database/aurora", "dynamodb": "database/dynamodb", "dax": "database/dynamodb-dax",
    "elasticache": "database/elasticache", "redshift": "database/redshift", "neptune": "database/neptune",
    "documentdb": "database/documentdb-mongodb-compatibility", "dms": "database/database-migration-service",
    "keyspaces": "database/keyspaces-managed-apache-cassandra-service", "timestream": "database/timestream",
    # mạng
    "vpc": "network/vpc", "igw": "network/internet-gateway", "nat": "network/nat-gateway",
    "alb": "network/elb-application-load-balancer", "nlb": "network/elb-network-load-balancer",
    "elb": "network/elastic-load-balancing", "cloudfront": "network/cloudfront", "route53": "network/route-53",
    "api-gateway": "network/api-gateway", "direct-connect": "network/direct-connect", "vpn": "network/site-to-site-vpn",
    "transit-gateway": "network/transit-gateway", "privatelink": "network/privatelink", "vpc-endpoint": "network/endpoint",
    "global-accelerator": "network/global-accelerator", "vpc-peering": "network/vpc-peering", "nacl": "network/nacl",
    "route-table": "network/route-table", "network-firewall": "network/network-firewall",
    # bảo mật
    "iam": "security/identity-and-access-management-iam", "iam-role": "security/identity-and-access-management-iam-role",
    "sts": "security/identity-and-access-management-iam-aws-sts", "mfa": "security/identity-and-access-management-iam-mfa-token",
    "kms": "security/key-management-service", "secrets-manager": "security/secrets-manager", "waf": "security/waf",
    "shield": "security/shield", "guardduty": "security/guardduty", "inspector": "security/inspector",
    "macie": "security/macie", "cognito": "security/cognito", "acm": "security/certificate-manager",
    "cloudhsm": "security/cloudhsm", "security-hub": "security/security-hub",
    # quản trị
    "cloudwatch": "management/cloudwatch", "cloudtrail": "management/cloudtrail", "config": "management/config",
    "organizations": "management/organizations", "cloudformation": "management/cloudformation",
    "systems-manager": "management/systems-manager", "trusted-advisor": "management/trusted-advisor",
    "control-tower": "management/control-tower", "auto-scaling": "management/auto-scaling",
    # tích hợp, phân tích, AI
    "sqs": "integration/simple-queue-service-sqs", "sns": "integration/simple-notification-service-sns",
    "eventbridge": "integration/eventbridge", "step-functions": "integration/step-functions", "mq": "integration/mq",
    "kinesis": "analytics/kinesis-data-streams", "firehose": "analytics/kinesis-data-firehose", "athena": "analytics/athena",
    "glue": "analytics/glue", "emr": "analytics/emr", "quicksight": "analytics/quicksight",
    "opensearch": "analytics/amazon-opensearch-service", "msk": "analytics/managed-streaming-for-kafka",
    "sagemaker": "ml/sagemaker", "bedrock": "ml/bedrock", "rekognition": "ml/rekognition", "polly": "ml/polly",
    "transcribe": "ml/transcribe", "translate": "ml/translate", "comprehend": "ml/comprehend", "textract": "ml/textract",
    "datasync": "migration/datasync", "transfer-family": "migration/transfer-for-sftp",
    "codepipeline": "devtools/codepipeline", "codebuild": "devtools/codebuild", "codedeploy": "devtools/codedeploy",
    # chung
    "users": "general/users", "user": "general/user", "client": "general/client", "mobile": "general/mobile-client",
    "internet": "general/internet-alt1", "office": "general/office-building", "server": "general/traditional-server",
    "firewall": "general/generic-firewall", "database": "general/generic-database",
}

BUILTIN_ICONS = {"globe", "gateway", "nat", "server", "database", "balance", "bulb", "x", "shield", "lock", "down"}


@lru_cache(maxsize=1)
def _aws_root() -> Path | None:
    try:
        import diagrams  # noqa: F401 — chỉ để tìm thư mục icon đi kèm gói
        root = Path(diagrams.__file__).resolve().parent.parent / "resources" / "aws"
        return root if root.is_dir() else None
    except ImportError:
        return None


@lru_cache(maxsize=1)
def aws_icons() -> dict[str, Path]:
    root = _aws_root()
    if not root:
        return {}
    return {k: root / f"{v}.png" for k, v in _AWS.items() if (root / f"{v}.png").exists()}


@lru_cache(maxsize=256)
def _data_uri(path: str) -> str:
    return "data:image/png;base64," + base64.b64encode(Path(path).read_bytes()).decode()


def icon_fields(icon: str | None) -> dict:
    """Đổi khai báo icon thành trường cho renderer: img (data URI) | emoji | icon (tên có sẵn)."""
    icon = (icon or "").strip()
    if icon.startswith("aws:"):
        p = aws_icons().get(icon[4:].lower())
        return {"img": _data_uri(str(p))} if p else {"emoji": "☁️"}
    if icon in BUILTIN_ICONS:
        return {"icon": icon}
    if icon and not icon.isascii():
        return {"emoji": icon[:8]}
    return {"emoji": "🔹"}


def _layout(graph: dict) -> dict:
    LAYOUT_CACHE.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(graph, ensure_ascii=False, sort_keys=True)
    key = raw + ELK_SCRIPT.read_text(encoding="utf-8")   # đổi tuỳ chọn ELK thì dàn lại
    f = LAYOUT_CACHE / f"{hashlib.sha1(key.encode()).hexdigest()[:16]}.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    p = subprocess.run(["node", str(ELK_SCRIPT)], input=raw, capture_output=True, text=True, encoding="utf-8", timeout=60)
    if p.returncode != 0:
        raise RuntimeError(f"ELK không dàn được sơ đồ: {p.stderr[-400:]}")
    f.write_text(p.stdout, encoding="utf-8")
    return json.loads(p.stdout)


def _label_size(text: str) -> tuple[int, int]:
    return min(260, 20 + 13 * len(text)), 34


def compile_flow(scene: dict, name: str) -> tuple[dict, list[dict]]:
    """Trả về (sơ đồ dạng diagram, events) cho một cảnh flow."""
    groups = {g["id"]: g for g in scene.get("groups", [])}
    nodes = {n["id"]: n for n in scene.get("nodes", [])}
    edges = [e for e in scene.get("edges", []) if e.get("from") in nodes and e.get("to") in nodes]

    # --- đồ thị ELK: nhóm lồng nhau, nút cỡ cố định, nhãn mũi tên có kích thước ---
    def elk_node(nid):
        return {"id": nid, "width": NODE_W, "height": NODE_H}

    def elk_group(gid):
        kids = [elk_group(c) for c, g in groups.items() if g.get("parent") == gid]
        kids += [elk_node(n) for n, v in nodes.items() if v.get("group") == gid]
        return {"id": gid, "layoutOptions": {"elk.padding": GROUP_PAD}, "children": kids}

    top = [elk_group(g) for g, v in groups.items() if not v.get("parent") or v.get("parent") not in groups]
    top += [elk_node(n) for n, v in nodes.items() if not v.get("group") or v.get("group") not in groups]
    graph = {"id": "root", "direction": "RIGHT" if scene.get("direction") == "right" else "DOWN", "children": top,
             "edges": [{"id": f"e{i}", "sources": [e["from"]], "targets": [e["to"]],
                        **({"labels": [dict(zip(("width", "height"), _label_size(e["label"])), text=e["label"])]} if e.get("label") else {})}
                       for i, e in enumerate(edges)]}
    out = _layout(graph)

    boxes, shapes = {}, {}

    def walk(n):
        for c in n.get("children", []):
            (boxes if c["id"] in groups else shapes)[c["id"]] = c
            walk(c)
    walk(out)
    W, H = out["width"], out["height"]

    elements = []
    kind_style = {"region": "region", "vpc": "vpc", "az": "az", "public": "subnet pub", "private": "subnet pri"}
    for gid, g in groups.items():
        b = boxes.get(gid)
        if not b:
            continue
        style = kind_style.get(g.get("kind", "box"), f"group tone-{g.get('tone', 'blue')}")
        elements.append({"id": gid, "kind": "box", "style": style, "x": round(b["x"]), "y": round(b["y"]),
                         "w": round(b["width"]), "h": round(b["height"]), "label": g.get("label", ""), "label_on": g.get("label", "")})
    all_edges = []
    for i, e in enumerate(edges):
        sec = next((s for ed in _iter_edges(out) if ed["id"] == f"e{i}" for s in ed.get("sections", [])), None)
        if not sec:
            continue
        pts = [sec["startPoint"], *sec.get("bendPoints", []), sec["endPoint"]]
        eid = f"{name}_e{i}"
        elements.append({"id": eid, "kind": "arrow", "style": e.get("style", "solid"),
                         "points": [[round(p["x"]), round(p["y"])] for p in pts]})
        all_edges.append((eid, e))
        lab = next((ed.get("labels", [None])[0] for ed in _iter_edges(out) if ed["id"] == f"e{i}"), None)
        if e.get("label") and lab:
            elements.append({"id": f"{eid}_l", "kind": "text", "x": round(lab["x"]), "y": round(lab["y"]), "text": e["label"]})
    for nid, n in nodes.items():
        s = shapes.get(nid)
        if not s:
            continue
        tone = n.get("tone", "")
        elements.append({"id": nid, "kind": "node", "wrap": True, "x": round(s["x"] + NODE_W / 2), "y": round(s["y"] + 4 + TILE / 2),
                         "label": n.get("label", ""), "style": tone, **icon_fields(n.get("icon"))})

    # --- steps → events: nhóm hiện khi con đầu tiên hiện, mũi tên hiện khi đủ hai đầu ---
    steps = scene.get("steps") or [{"cue": "", "show": list(nodes)}]
    shown: set[str] = set()
    parent_chain = {}
    for nid, n in nodes.items():
        chain, g = [], n.get("group")
        while g in groups and g not in chain:
            chain.append(g)
            g = groups[g].get("parent")
        parent_chain[nid] = chain
    geo = {e["id"]: e for e in elements}
    events = []
    leftovers = [n for n in nodes if not any(n in (st.get("show") or []) for st in steps)]
    for k, st in enumerate(steps):
        new_nodes = [n for n in (st.get("show") or []) + (leftovers if k == 0 else []) if n in nodes and n not in shown]
        new_groups = []
        for n in new_nodes:
            for g in reversed(parent_chain[n]):
                if g not in shown and g not in new_groups:
                    new_groups.append(g)
        shown.update(new_nodes, new_groups)
        new_edges = [eid for eid, e in all_edges if e["from"] in shown and e["to"] in shown and eid not in shown]
        shown.update(new_edges)
        labels = [f"{eid}_l" for eid in new_edges if f"{eid}_l" in geo]
        show = new_groups + new_nodes + new_edges + labels
        ev = {"cue": st.get("cue") or "", "show": show, "focus": [f for f in st.get("focus", []) if f in geo],
              "bbox": _bbox([geo[i] for i in new_nodes + new_edges if i in geo]) or _bbox([geo[i] for i in show if i in geo])}
        events.append(ev)
    return {"w": round(W), "h": round(H), "camera": True, "elements": elements}, events


def _iter_edges(n):
    yield from n.get("edges", [])
    for c in n.get("children", []):
        yield from _iter_edges(c)


def _bbox(items: list[dict]) -> list[int] | None:
    xs, ys = [], []
    for e in items:
        if e["kind"] == "node":
            xs += [e["x"] - NODE_W / 2, e["x"] + NODE_W / 2]
            ys += [e["y"] - TILE / 2 - 4, e["y"] + NODE_H - TILE / 2 - 4]
        elif e["kind"] == "arrow":
            xs += [p[0] for p in e["points"]]
            ys += [p[1] for p in e["points"]]
        elif e["kind"] == "box":
            xs += [e["x"], e["x"] + e["w"]]
            ys += [e["y"], e["y"] + e["h"]]
    if not xs:
        return None
    return [round(min(xs)), round(min(ys)), round(max(xs) - min(xs)), round(max(ys) - min(ys))]


def compile_flows(spec_dict: dict) -> dict:
    """Đổi mọi cảnh flow trong spec (dạng dict) thành cảnh diagram + khai báo sơ đồ tương ứng."""
    diagrams = dict(spec_dict.get("diagrams") or {})
    scenes = []
    for i, sc in enumerate(spec_dict["scenes"]):
        if sc.get("type") != "flow":
            scenes.append(sc)
            continue
        name = f"flow{i + 1}"
        diagram, events = compile_flow(sc, name)
        diagrams[name] = diagram
        keep = {k: v for k, v in sc.items() if k not in ("groups", "nodes", "edges", "steps", "direction")}
        scenes.append({**keep, "type": "diagram", "diagram": name, "events": events, "flow": True})
    return {**spec_dict, "scenes": scenes, "diagrams": diagrams}
