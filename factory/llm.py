"""Nhờ Gemini viết kịch bản (canonical spec) từ một chủ đề — 3 bước: dàn ý → kịch bản → rà soát kiến thức.

Quy tắc dựa trên khảo sát video kiến thức TikTok (09/2026): móc câu ngay câu đầu (câu hỏi / phá niềm tin /
con số / rủi ro), không mở bằng "X là gì"; video chi tiết 2–4 phút được lưu và chia sẻ nhiều nhất khi hình
đổi liên tục; quá trình, cơ chế, kiến trúc được vẽ thành sơ đồ dựng dần; kết bằng lời kêu gọi lưu, theo dõi, bình luận.
"""

import base64
import json
import re
import time
from datetime import datetime

import httpx
from pydantic import ValidationError

from .config import CONTENT_DIR, gemini_api_key, gemini_model
from .flow import aws_icons
from .spec import Spec, slugify

LEVELS = {  # số cảnh, số từ lời đọc (giọng Hoài My ~190 từ/phút)
    "short": (6, 170, "khoảng 1 phút"),
    "medium": (9, 330, "khoảng 2 phút"),
    "deep": (13, 560, "khoảng 3 phút"),
}

HOOKS = {
    "auto": "chọn kiểu móc câu hợp nhất với chủ đề trong các kiểu dưới đây",
    "curiosity": 'tò mò về cơ chế: "X hoạt động bằng cách nào?", "Bên trong X có gì?", "Chuyện gì xảy ra trong 1 giây khi…"',
    "myth": 'phá niềm tin: "Bạn nghĩ … ? Sai rồi.", "90 phần trăm người dùng hiểu sai …"',
    "list": 'danh sách con số: "5 dấu hiệu…", "3 sai lầm…", "7 khái niệm…" (mỗi mục là một ý rõ ràng)',
    "danger": 'rủi ro / nỗi đau: "Sai lầm này khiến bạn mất…", "Sự thật đáng sợ về…"',
    "exam": 'câu hỏi thi: "Câu hỏi bẫy nhất về … trong đề thi", mở bằng một tình huống đề hay hỏi',
}

OUTLINE_PROMPT = """You are an expert Vietnamese educational short-video writer who studies what performs on TikTok.
Topic: {topic}
{notes}Target: {minutes}, about {words} spoken words, {scenes} scenes, vertical 9:16.
Hook style: {hook}.
Return ONLY JSON:
{{
  "angle": "the specific, surprising angle that makes this worth watching (Vietnamese)",
  "title": "clickable Vietnamese title following the hook style, <= 60 chars, never of the form 'X là gì'",
  "hook_line": "the very first spoken sentence, <= 18 words: curiosity, a challenged belief, a striking number or a risk. Never start with 'Xin chào', 'Hôm nay', 'Chào mừng'",
  "facts": ["6-12 precise, verifiable facts with numbers where possible"],
  "misconceptions": ["common wrong beliefs and the truth"],
  "analogy": "one everyday analogy that makes the core idea click",
  "examples": ["concrete real-world examples"],
  "diagrams": ["processes, mechanisms, flows or architectures worth drawing step by step (0-3 items); for each, name its 4-8 stages or components in order, e.g. 'Gửi tin nhắn: điện thoại → mã hoá → trạm BTS → cáp quang → máy chủ → điện thoại người nhận'"],
  "beats": [{{"type": "title|bullets|compare|stat|flow|tip|next", "point": "what this scene teaches"}}]
}}
Be factually rigorous. If unsure about a number, leave it out."""

SCRIPT_PROMPT = """Write the full script for a Vietnamese educational short video from this outline:
{outline}

Target: {minutes}, about {words} spoken words in total, exactly {scenes} scenes.
{notes}Return ONLY a JSON object:
{{
  "id": "short-ascii-slug",
  "title": "the outline title",
  "voice": "vi-VN-HoaiMyNeural",
  "stock_terms": ["5 English stock-footage searches of things a camera can film, 1-3 words, in narration order: places, animals, food, objects, people doing an action (e.g. 'hanoi street', 'woman typing phone'); never abstract terms like 'cloud computing' or 'load balancer'"],
  "description": "1–2 Vietnamese sentences for the post caption, ending with a question inviting comments",
  "hashtags": ["4-6 tags without #"],
  "whiteboard_plan": [{{"page":1, "objects": [{{"kind":"phone|laptop|lock|shield|warning|code|checklist|arrow|star|bulb|chart|coin|cloud|server|text|stat|formula|person|books|document|explosion|atom", "at":0.0, "x":0.0, "y":0.0, "scale":1.0, "color":"blue|orange|green|red|pink", "text":"only for text/stat/formula", "label":"optional stat label", "checked":false, "broken":false, "value":"optional code", "to_x":0.0, "to_y":0.0}}]}}],
  "scenes": [ ... ]
}}
Scene types (every scene has "type", "say" and "stock": 1-2 English stock-footage searches of what a camera would film
while THIS scene is said, e.g. ["suspension bridge", "man walking on bridge"] — concrete and filmable, never abstract):
- title   {{"type":"title","say":...,"tag":"SHORT UPPERCASE TOPIC","headline":[["WORD",true],["WORD",false]],"sub":"one-line subtitle",
            "chips":[{{"text":"<=22 chars","cue":"phrase from say"}}]}}   (1–3 headline tokens, at most 3 chips)
- bullets {{"type":"bullets","say":...,"kicker":"SHORT LABEL","heading":"<=48 chars","items":[{{"text":"<=34 chars","cue":"phrase from say"}}]}}  (2–4 items)
- compare {{"type":"compare","say":...,"kicker":"SHORT LABEL","heading":"<=48 chars",
            "left":{{"title":"<=20 chars","points":["<=30 chars"],"cue":"phrase"}},"right":{{"title":"<=20 chars","points":["<=30 chars"],"cue":"phrase"}}}}
- stat    {{"type":"stat","say":...,"kicker":"SHORT LABEL","heading":"<=48 chars","stats":[{{"value":"<=6 chars","label":"<=28 chars","cue":"phrase"}}]}}  (1–3 stats)
- flow    {{"type":"flow","say":...,"kicker":"SHORT LABEL","heading":"<=48 chars","direction":"down",
            "groups":[{{"id":"g1","label":"Điện thoại của bạn","kind":"box","tone":"blue","parent":null}},
                      {{"id":"g2","label":"Nhà mạng","kind":"box","tone":"green","parent":null}}],
            "nodes":[{{"id":"n1","label":"Ứng dụng nhắn tin","icon":"📱","group":"g1"}},{{"id":"n2","label":"Mã hoá","icon":"🔒","group":"g1"}},
                     {{"id":"n3","label":"Trạm BTS","icon":"📡","group":"g2"}},{{"id":"n4","label":"Cáp quang","icon":"💡","group":"g2"}},
                     {{"id":"n5","label":"Máy chủ","icon":"🖥️"}}],
            "edges":[{{"from":"n1","to":"n2","style":"solid"}},{{"from":"n2","to":"n3","label":"sóng radio","style":"flow"}},
                     {{"from":"n3","to":"n4","style":"flow"}},{{"from":"n4","to":"n5","label":"ánh sáng","style":"flow"}}],
            "steps":[{{"cue":"phrase from say","show":["n1","n2"],"focus":["n2"]}},{{"cue":"later phrase","show":["n3","n4"],"focus":["n3"]}},
                     {{"cue":"last phrase","show":["n5"],"focus":["n5"]}}]}}
          (The example shows the shape only — build this topic's own diagram from the outline.)
          A step-by-step diagram that builds up while it is narrated. It MUST have 4–8 nodes and 3–4 steps: a 3-node chain is
          too thin — add the component or actor doing each job, the medium the thing travels through, or split a stage into
          its sub-steps. Every node appears in some step, steps follow the order of the narration. groups are optional (kind: box|region|vpc|az|public|private,
          tone: blue|green|purple|orange|gray|red) — use them to show "what lives inside what". edge style: solid |
          flow (moving data / energy) | blocked (not allowed). Keep the main direction top→bottom, avoid edges that point back up.
          Icons: use ONE fitting emoji per node (📡 📱 ⚡ 🧠 🔒 💰 🧬 🏭 …). Use aws:<name> ONLY when the node literally is that
          AWS service (its label names it); never as decoration. Allowed AWS names: {aws_icons}.
- tip     {{"type":"tip","say":...,"label":"MẸO|SAI LẦM PHỔ BIẾN|MẸO THI","q_label":"CÂU HỎI|TÌNH HUỐNG","a_label":"ĐÁP ÁN|NÊN LÀM",
            "question":"<=110 chars","answer":"<=28 chars","answer_cue":"phrase from say said right before the answer"}}
- next    {{"type":"next","say":...,"label":"GHI NHỚ|TIẾP THEO","title":"<=40 chars","sub":"<=60 chars"}}
Whiteboard plan rules:
- Return one whiteboard_plan item for every scene, in exactly the same order.
- Each item has 2-6 objects. Use only the listed object kinds. x and y are normalized board coordinates from 0 to 1; keep objects inside x=.05-.80 and y=.12-.78.
- at is a fraction of this narration scene from 0 to 1. Draw the first object at .05 and the last no later than .75. Objects are drawn in listed order. Use arrow only to connect nearby objects and give it to_x/to_y.
- page is a positive integer. Consecutive scenes with the same page continue drawing on the same board and retain the objects already drawn. Start a new page only when the explanation changes to a new idea.
- text, stat and formula are part of the whiteboard drawing. Use them sparingly for a keyword, a number or a short formula; captions retain the full narration.
- Choose concrete doodles that explain this scene. The plan is a simple visual storyboard, not a stock-photo search.
Rules:
- Scene 1 is "title" and its "say" starts with the hook line. The last scene is "next": a one-line takeaway plus a call to save the video,
  follow, and answer a question in the comments. Include exactly one "tip". Include 1–3 "flow" scenes whenever the outline lists diagrams.
- Every scene's "say" has 2–4 sentences (about 10–18 seconds) of natural spoken Vietnamese; keep technical terms in English;
  use the analogy and at least two concrete facts or examples; no filler.
- Write numbers as digits. Do not use the symbols / % & + (write "phần trăm").
- Every "cue" and "answer_cue" must be copied exactly, character for character, from the "say" of the same scene, in speaking order.
- On-screen texts are short keywords, never full sentences. Be factually accurate."""

REVIEW_PROMPT = """You are a meticulous fact-checker. Review this Vietnamese educational video script for factual errors,
outdated information, misleading simplifications and internal contradictions. Topic: {topic}
Script JSON:
{script}
Fix every problem directly in the script, keeping the same structure, scene count and style rules (cues must still match "say"
exactly). Return ONLY a JSON object: {{"issues": ["short Vietnamese description of each fix"], "script": {{...the corrected full script...}}}}"""


# Bản podcast cho MoneyPrinterTurbo: đặc điểm đo từ các video podcast tình yêu top đầu TikTok (vd. Thuần Podcast,
# 2,4 triệu lượt xem): văn nói xưng "mình", tiếng đệm, một ý cảm xúc, ~210 tiếng/phút, ngắt nghỉ ngắn, nhạc nền nhẹ.
PODCAST_PROMPT = """Rewrite this Vietnamese educational video script as a short Vietnamese TikTok podcast monologue
("podcast tâm sự") in the style of the top Vietnamese podcast creators:
{script}

Rules:
- Spoken Vietnamese (văn nói), first person "mình", speak to the listener as "bạn" now and then. Use natural particles and
  fillers such as "ấy", "nhỉ", "đúng không", "thật ra thì", "nhưng mà", "rất là"; long flowing sentences joined like real speech.
- Build ONE emotional insight from the script. Keep the facts correct, but use at most one number and at most one researcher
  name; no lists, no "thứ nhất / thứ hai", no headings.
- Start with a relatable feeling or situation in the very first sentence (no greetings). End with a soft reflective line and a
  gentle invitation to save the video or share in the comments.
- About {syllables} Vietnamese syllables (about {seconds} seconds at 210 syllables per minute). Write numbers as digits and do
  not use the symbols / % & + (write "phần trăm").
Return ONLY JSON: {{"title": "short feeling-driven title shown on screen, <= 60 chars",
  "say": "the monologue",
  "stock_terms": ["5 English stock-footage searches for moody podcast B-roll a camera can film, e.g. 'woman looking out rainy window', 'city lights at night', 'couple walking from behind'"]}}"""


def podcast_version(spec: dict, log=print, seconds: int = 70) -> dict:
    """Viết thêm lời thoại kiểu podcast tâm sự (chỉ bản MoneyPrinterTurbo dùng)."""
    script = "\n".join(s["say"] for s in spec["scenes"])
    data = _json(_call_gemini(PODCAST_PROMPT.format(script=script, syllables=seconds * 210 // 60, seconds=seconds), log=log))
    say = " ".join(str(data.get("say", "")).split())
    if len(say.split()) < 60:
        raise RuntimeError("Gemini trả bản podcast quá ngắn")
    terms = [str(t).strip() for t in data.get("stock_terms", []) if str(t).strip()][:6]
    return {"title": str(data.get("title") or spec.get("title", ""))[:80], "say": say, "stock_terms": terms}


FALLBACK_MODELS = ["gemini-flash-latest", "gemini-3.7-flash", "gemini-3.5-flash", "gemini-flash-lite-latest"]


def _quota_info(r: httpx.Response) -> tuple[bool, float]:
    """(hết hạn mức trong ngày?, số giây nên chờ) từ lỗi 429 của Gemini."""
    try:
        details = r.json().get("error", {}).get("details", [])
    except ValueError:
        return False, 30.0
    per_day = any("PerDay" in v.get("quotaId", "") for d in details for v in d.get("violations", []))
    delay = next((d.get("retryDelay") for d in details if "RetryInfo" in d.get("@type", "")), "30s")
    try:
        wait = float(str(delay).rstrip("s"))
    except ValueError:
        wait = 30.0
    return per_day, min(max(wait, 5.0), 65.0)


def _call_gemini(prompt: str, json_mode: bool = True, search: bool = False, log=print,
                 images: list[bytes] | None = None) -> str:
    """images: ảnh JPEG gửi kèm (đánh số "Image 1", "Image 2"… trước lời nhắn) — dùng để Gemini soát ảnh vẽ."""
    key = gemini_api_key()
    if not key:
        raise RuntimeError("chưa có key Gemini (đặt GEMINI_API_KEY trong video-factory/.env hoặc nhập trong MoneyPrinterTurbo)")
    errors = []
    # Gói miễn phí hay quá tải (503) và giới hạn theo phút (429): chờ đúng retryDelay rồi thử lại;
    # hết hạn mức trong ngày thì chuyển model dự phòng.
    for model in dict.fromkeys([gemini_model(), *FALLBACK_MODELS]):
        thinking = "low"
        for attempt in range(4):
            gc = {"temperature": 0.7}
            if json_mode:
                gc["responseMimeType"] = "application/json"
            if thinking:
                gc["thinkingConfig"] = {"thinkingLevel": thinking}
            parts = [p for k, img in enumerate(images or [], 1)
                     for p in ({"text": f"Image {k}:"},
                               {"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(img).decode()}})]
            body = {"contents": [{"role": "user", "parts": parts + [{"text": prompt}]}], "generationConfig": gc}
            if search:
                body["tools"] = [{"google_search": {}}]
            try:
                r = httpx.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                               headers={"x-goog-api-key": key}, json=body, timeout=240)
            except httpx.HTTPError as exc:
                errors.append(f"{model}: {exc}")
                time.sleep(5)
                continue
            if r.status_code == 200:
                cand = (r.json().get("candidates") or [{}])[0]
                parts = (cand.get("content") or {}).get("parts", [])
                text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
                if text.strip():
                    return text
                errors.append(f"{model}: phản hồi rỗng ({cand.get('finishReason')})")
                break
            errors.append(f"{model}: HTTP {r.status_code} {r.text[:160]}")
            if r.status_code == 400 and thinking and "thinking" in r.text.lower():
                thinking = None           # model không nhận thinkingLevel: gửi lại không kèm
                continue
            if r.status_code == 429:
                per_day, wait = _quota_info(r)
                if per_day or search:
                    log(f"{model} hết hạn mức{' tìm kiếm' if search else ' trong ngày'}, chuyển model khác")
                    break
                log(f"Gemini giới hạn số yêu cầu mỗi phút, chờ {wait:.0f} giây")
                time.sleep(wait)
                continue
            if r.status_code in (500, 502, 503, 504) and attempt < 1:
                log(f"{model} đang quá tải, thử lại sau 6 giây")
                time.sleep(6)
                continue
            if r.status_code in (500, 502, 503, 504):
                log(f"{model} vẫn quá tải, chuyển model khác")
            break
    raise RuntimeError(" | ".join(errors[-3:]))


def _json(text: str):
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if m:
        text = m.group(1)
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start:end + 1] if start >= 0 else text)


def _validated(prompt: str, log) -> Spec:
    error = ""
    for attempt in range(3):
        text = _call_gemini(prompt + (f"\n\nYour previous answer was invalid: {error}\nFix it and return the full JSON again." if error else ""), log=log)
        try:
            return Spec.model_validate(_json(text))
        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            error = str(exc)[:900]
            log(f"kịch bản chưa hợp lệ (lần {attempt + 1}): {error[:160]}")
    raise RuntimeError(f"kịch bản không hợp lệ sau 3 lần thử: {error[:300]}")


# Chọn góc nhìn nhiều vòng (học từ reels-af): 4 "thợ săn" tìm 12 góc → biên tập chấm điểm, giữ 3 góc và viết 3 đoạn
# mở đầu cạnh tranh → giám khảo so từng cặp. Gộp còn 3 lần gọi Gemini cho vừa hạn mức gói miễn phí.
HUNT_PROMPT = """Topic for a Vietnamese TikTok knowledge video: {topic}
{notes}Find 12 candidate angles, 3 from each "hunter":
- "con_so": a surprising, specific, verifiable number or measurement
- "dao_nguoc": a reversal of something most people believe
- "khoanh_khac": a vivid everyday moment or time-boxed scenario ("lúc nửa đêm…", "trong 1 giây khi…")
- "lien_nganh": an insight borrowed from another field (biology, economics, physics…)
For each: hunter, angle (Vietnamese, one sentence), hook_line (Vietnamese, <= 18 words, spoken, no greeting),
fact (the verifiable fact it rests on, with researcher or source and year), risk (what might be inaccurate).
Return ONLY JSON: {{"angles": [{{"hunter": "...", "angle": "...", "hook_line": "...", "fact": "...", "risk": "..."}}]}}"""

CRITIC_PROMPT = """You are a strict editor of a Vietnamese TikTok knowledge channel. Score each angle 1-10 on: hook (would a
scrolling viewer stop within 2 seconds?), truth (is the fact verifiable and used correctly?), fit (topic and audience), fresh
(not the obvious take). Never pick an angle with truth < 7. For the 3 best angles write a competing opening each: 3 spoken
Vietnamese sentences (hook, tension, promise of a payoff).
Angles:
{angles}
Return ONLY JSON: {{"scores": [{{"i": 0, "hook": 0, "truth": 0, "fit": 0, "fresh": 0}}],
  "finalists": [{{"i": 0, "opening": "..."}}]}}  (exactly 3 finalists, i = angle index)"""

JUDGE_PROMPT = """Three openings compete for a Vietnamese TikTok video about: {topic}
{openings}
Compare them pairwise as a typical Vietnamese viewer scrolling TikTok at night: which one makes you stop and keep watching
while staying truthful? Return ONLY JSON: {{"winner": 0, "why": "one Vietnamese sentence"}} (winner = index 0-2)."""


def angle_tournament(topic: str, notes: str = "", log=print) -> dict:
    log("chọn góc nhìn 1/3: 4 hướng tìm 12 góc")
    hunt = _json(_call_gemini(HUNT_PROMPT.format(topic=topic, notes=notes), log=log))
    angles = [a for a in hunt.get("angles", []) if a.get("angle") and a.get("hook_line")][:16]
    if len(angles) < 3:
        raise RuntimeError("Gemini trả quá ít góc nhìn")
    log("chọn góc nhìn 2/3: chấm điểm, giữ 3 góc mạnh nhất, viết 3 đoạn mở đầu")
    listing = "\n".join(f"{i}. [{a.get('hunter', '')}] {a['angle']} | mở đầu: {a['hook_line']} | dữ kiện: {a.get('fact', '')}"
                        f" | rủi ro: {a.get('risk', '')}" for i, a in enumerate(angles))
    crit = _json(_call_gemini(CRITIC_PROMPT.format(angles=listing), log=log))
    fin = [f for f in crit.get("finalists", []) if isinstance(f.get("i"), int) and 0 <= f["i"] < len(angles) and f.get("opening")][:3]
    if not fin:
        raise RuntimeError("biên tập không giữ được góc nào")
    log("chọn góc nhìn 3/3: giám khảo so từng cặp")
    judge = _json(_call_gemini(JUDGE_PROMPT.format(topic=topic, openings="\n".join(f"{k}. {f['opening']}" for k, f in enumerate(fin))), log=log))
    w = judge.get("winner", 0)
    w = w if isinstance(w, int) and 0 <= w < len(fin) else 0
    return {"winner": {**angles[fin[w]["i"]], "opening": fin[w]["opening"], "why": str(judge.get("why", ""))},
            "finalists": [{**angles[f["i"]], "opening": f["opening"]} for f in fin], "count": len(angles)}


def draft_spec(topic: str, level: str = "medium", hook: str = "auto", notes: str = "", check: bool = True,
               log=print, podcast: bool = False, tournament: bool = False) -> tuple[dict, str, list[str]]:
    scenes, words, minutes = LEVELS.get(level, LEVELS["medium"])
    hook_desc = HOOKS.get(hook, HOOKS["auto"]) + ("" if hook != "auto" else ": " + " | ".join(v for k, v in HOOKS.items() if k != "auto"))
    note_line = f"Author notes: {notes}\n" if notes else ""
    contest = None
    if tournament:
        try:
            contest = angle_tournament(topic, note_line, log)
            w = contest["winner"]
            note_line += (f"Chosen angle (winner of an angle tournament — build the whole video around it): {w['angle']}\n"
                          f"The first spoken sentence must be: {w['hook_line']}\nKey fact: {w.get('fact', '')}\n"
                          f"Opening to follow closely: {w['opening']}\n")
        except Exception as exc:
            log(f"chọn góc nhìn chưa được ({str(exc)[:100]}) → viết theo cách thường")

    log("1/3 lập dàn ý")
    outline = _json(_call_gemini(OUTLINE_PROMPT.format(topic=topic, notes=note_line, minutes=minutes, words=words,
                                                       scenes=scenes, hook=hook_desc), log=log))
    log("2/3 viết kịch bản")
    spec = _validated(SCRIPT_PROMPT.format(outline=json.dumps(outline, ensure_ascii=False, indent=1), minutes=minutes,
                                           words=words, scenes=scenes, notes=note_line,
                                           aws_icons=", ".join(sorted(aws_icons()))), log)
    issues: list[str] = []
    if check:
        log("3/3 rà soát kiến thức")
        review = REVIEW_PROMPT.format(topic=topic, script=json.dumps(spec.dump(), ensure_ascii=False))
        for search in (True, False):   # Google Search nếu gói cho phép, không thì rà bằng kiến thức của model
            try:
                data = _json(_call_gemini(review, json_mode=not search, search=search, log=log))
                fixed = Spec.model_validate(data.get("script") or {})
                spec, issues = fixed, [str(i) for i in data.get("issues", [])][:12]
                issues.insert(0, "đã rà soát có Google Search" if search else "đã rà soát (không có Google Search)")
                break
            except Exception as exc:  # rà soát lỗi thì giữ bản đã viết
                log(f"rà soát {'có' if search else 'không có'} Google Search chưa được: {str(exc)[:160]}")
    issues += [f'sơ đồ "{s.model_extra.get("heading")}" chỉ có {len(s.model_extra["nodes"])} nút — nên bổ sung trước khi tạo video'
               for s in spec.scenes if s.type == "flow" and len(s.model_extra["nodes"]) < 4]
    out = spec.dump()
    out["angle"] = outline.get("angle", "")
    if contest:
        out["angle_tournament"] = contest
        w = contest["winner"]
        issues.insert(0, f"góc nhìn thắng ({w.get('hunter', '')}): {w['angle']} — {w.get('why', '')}")
        issues[1:1] = [f"vào chung kết: {f['angle']}" for f in contest["finalists"] if f["angle"] != w["angle"]]
    if podcast:
        log("viết thêm bản podcast (văn nói) cho MoneyPrinterTurbo")
        try:
            out["podcast"] = podcast_version(out, log)
        except Exception as exc:   # thiếu bản podcast thì MoneyPrinterTurbo đọc kịch bản thường
            issues.append(f"chưa viết được bản podcast: {str(exc)[:120]}")
    name = f"{slugify(spec.id or topic, 40)}-{datetime.now():%m%d-%H%M}.json"
    path = CONTENT_DIR / "drafts" / name
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return out, f"drafts/{name}", issues
