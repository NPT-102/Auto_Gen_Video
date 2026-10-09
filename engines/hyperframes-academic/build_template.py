"""Sinh template.html cho engine HyperFrames từ template studio của series AWS.

Thêm: khai báo composition cho HyperFrames, thẻ audio, lớp bọc timeline quanh renderAt(t),
và 3 loại cảnh mới (bullets, compare, stat). Chạy lại khi template studio thay đổi:
    python build_template.py
"""

import pathlib

HERE = pathlib.Path(__file__).resolve().parent
SRC = next((p for p in (HERE.parents[1] / "examples" / "aws-saa-series" / "studio" / "template.html",
                        HERE.parents[2] / "aws-saa-series" / "studio" / "template.html") if p.exists()),
           HERE.parents[2] / "aws-saa-series" / "studio" / "template.html")
DST = HERE / "template.html"


def rep(s: str, a: str, b: str) -> str:
    assert s.count(a) == 1, (a[:70], s.count(a))
    return s.replace(a, b)


CSS_NEW = """/* bullets */
.blist { position: absolute; left: 0; right: 0; top: 260px; bottom: 90px; display: flex; flex-direction: column; justify-content: center; gap: 28px; }
.bitem { display: flex; align-items: center; gap: 28px; padding: 34px 38px; border-radius: 28px; background: #fff; border: 2.5px solid var(--line);
  box-shadow: 0 12px 30px rgba(15,27,45,.07); opacity: 0; }
.bitem .num { flex: none; display: grid; place-items: center; width: 78px; height: 78px; border-radius: 20px; background: var(--accent-soft);
  color: var(--accent); font-weight: 700; font-size: 38px; }
.bitem .bt { font-weight: 700; font-size: 46px; line-height: 1.25; }
.bitem.on { border-color: var(--accent); box-shadow: 0 18px 44px rgba(238,138,0,.18); }
.bitem.on .num { background: var(--accent); color: #fff; }
/* compare */
.cmp { position: absolute; left: 0; right: 0; top: 260px; bottom: 90px; display: flex; flex-direction: column; justify-content: center; }
.cside { padding: 40px 44px 34px; border-radius: 30px; background: #fff; border: 2.5px solid var(--line); box-shadow: 0 14px 36px rgba(15,27,45,.07); opacity: 0; }
.cside.a { border-top: 12px solid var(--pri); } .cside.b { border-top: 12px solid var(--accent); }
.cside h3 { font-weight: 700; font-size: 54px; line-height: 1.15; } .cside.a h3 { color: var(--pri); } .cside.b h3 { color: var(--accent); }
.cside ul { margin-top: 14px; list-style: none; }
.cside li { position: relative; padding: 8px 0 8px 42px; font-size: 40px; line-height: 1.32; color: var(--ink2); }
.cside li::before { content: ""; position: absolute; left: 8px; top: 27px; width: 14px; height: 14px; border-radius: 50%; background: #B8C2D0; }
.vs { align-self: center; margin: -26px 0; z-index: 2; width: 100px; height: 100px; border-radius: 50%; background: var(--ink); color: #fff;
  display: grid; place-items: center; font-weight: 700; font-size: 36px; letter-spacing: .04em; box-shadow: 0 10px 26px rgba(15,27,45,.25); opacity: 0; }
/* stat */
.stats { position: absolute; left: 0; right: 0; top: 260px; bottom: 90px; display: flex; flex-direction: column; justify-content: center; gap: 32px; }
.stats.one .stat { padding: 56px 56px 60px; } .stats.one .sv { font-size: 260px; } .stats.one .sl { font-size: 52px; }
.stat { padding: 36px 46px 38px; border-radius: 30px; background: #fff; border: 2.5px solid var(--line); box-shadow: 0 14px 36px rgba(15,27,45,.07); opacity: 0; }
.stat .sv { font-weight: 700; font-size: 150px; line-height: 1; color: var(--accent); letter-spacing: -.03em; }
.stat .sl { margin-top: 14px; font-size: 42px; line-height: 1.3; color: var(--ink2); font-weight: 700; }

/* captions */"""

JS_BUILDERS = r"""function buildBullets(s, sec) {
  buildDiagramHead(s, sec);
  const list = el('<div class="blist"></div>'); sec.appendChild(list);
  const items = s.items || [];
  const times = items.map((it, i) => it.t ?? (s.start + 0.5 + i * 0.9));
  items.forEach((it, i) => {
    const row = el(`<div class="bitem"><div class="num">${i + 1}</div><div class="bt">${esc(it.text)}</div></div>`);
    list.appendChild(row); anim(row, times[i], 'up');
    activeRanges.push({ node: row, from: times[i], to: i + 1 < items.length ? times[i + 1] : s.end });
  });
}

function buildCompare(s, sec) {
  buildDiagramHead(s, sec);
  const box = el('<div class="cmp"></div>'); sec.appendChild(box);
  const side = (d, cls) => el(`<div class="cside ${cls}"><h3>${esc(d.title || '')}</h3><ul>${(d.points || []).map(p => `<li>${esc(p)}</li>`).join('')}</ul></div>`);
  const a = side(s.left || {}, 'a'), vs = el('<div class="vs">VS</div>'), b = side(s.right || {}, 'b');
  box.append(a, vs, b);
  const ta = (s.left && s.left.t) ?? (s.start + 0.4), tb = (s.right && s.right.t) ?? (ta + 1.2);
  anim(a, ta, 'up'); anim(vs, (ta + tb) / 2, 'pop2', 0.45); anim(b, tb, 'up');
}

function buildStat(s, sec) {
  buildDiagramHead(s, sec);
  const box = el(`<div class="stats${(s.stats || []).length === 1 ? ' one' : ''}"></div>`); sec.appendChild(box);
  (s.stats || []).forEach((st, i) => {
    const at = st.t ?? (s.start + 0.5 + i * 0.9);
    const node = el(`<div class="stat"><div class="sv">${esc(st.value)}</div><div class="sl">${esc(st.label || '')}</div></div>`);
    box.appendChild(node); anim(node, at, 'up');
    const m = /^(\d{1,6})(\D*)$/.exec(String(st.value).trim());
    if (m) countUps.push({ node: node.querySelector('.sv'), at, target: +m[1], suffix: m[2] });
  });
}

function buildTip(s, sec) {"""

HF_TAIL = """window.setup = setup; window.renderAt = renderAt;
</script>
<script>window.__DATA = __DATA_JSON__;</script>
<script>
(function () {
  const D = window.__DATA;
  setup(D);
  let cur = 0;
  const tl = {
    duration: () => D.duration, totalDuration: () => D.duration,
    seek(t) { cur = Math.max(0, Math.min(+t || 0, D.duration)); renderAt(cur); return tl; },
    time(v) { return v === undefined ? cur : tl.seek(v); },
    totalTime(v) { return v === undefined ? cur : tl.seek(v); },
    progress(v) { return v === undefined ? cur / D.duration : tl.seek(v * D.duration); },
    pause() { return tl; }, play() { return tl; }, paused() { return true; },
    timeScale(v) { return v === undefined ? 1 : tl; }, getChildren() { return []; },
    isActive() { return false; }, invalidate() { return tl; }, kill() {},
  };
  window.__timelines = window.__timelines || {};
  window.__timelines.main = tl;
  renderAt(0);
})();
</script>"""


CSS_FLOW = """/* flow: icon ảnh / emoji, nhãn xuống dòng, nhóm theo tông, khung camera */
.dnode .ic img { width: 74px; height: 74px; object-fit: contain; }
.dnode .ic .emo { font-size: 60px; line-height: 1; font-family: "Segoe UI Emoji", "Noto Color Emoji", sans-serif; }
.dnode.wrap .nl { white-space: normal; width: 214px; text-align: center; line-height: 1.16; }
.dbox.group { border: 2.5px solid #C9D2DE; background: rgba(255,255,255,.6); }
.dbox.group .dl { color: #6B7686; }
.dbox.group.tone-blue { border-color: var(--pri); background: var(--pri-soft); } .dbox.group.tone-blue .dl { color: var(--pri); }
.dbox.group.tone-green { border-color: var(--pub); background: var(--pub-soft); } .dbox.group.tone-green .dl { color: var(--pub); }
.dbox.group.tone-purple { border-color: var(--db); background: var(--db-soft); } .dbox.group.tone-purple .dl { color: var(--db); }
.dbox.group.tone-orange { border-color: var(--accent); background: var(--accent-soft); } .dbox.group.tone-orange .dl { color: var(--accent); }
.dbox.group.tone-red { border-color: var(--danger); background: var(--danger-soft); } .dbox.group.tone-red .dl { color: var(--danger); }
.dlayer.cam { overflow: hidden; border-radius: 28px; }

/* captions */"""

CAMERA_JS = r"""
// Camera cho sơ đồ tự dàn: zoom vào phần vừa được giảng, cuối cảnh lùi ra toàn cảnh.
let cams = [];
function camView(c, b) {
  const VW = 940, VH = 1050;
  if (!b) { const s = c.base; return { s, x: (VW - c.W * s) / 2, y: (VH - c.H * s) / 2 }; }
  const bw = Math.max(b[2] + 160, c.W * 0.5), bh = Math.max(b[3] + 160, c.H * 0.42);
  let s = Math.min(VW / bw, VH / bh);
  s = clamp(s, c.base, Math.max(c.base, Math.min(c.base * 1.9, 1.3)));
  const cx = b[0] + b[2] / 2, cy = b[1] + b[3] / 2;
  const fit = (v, size, V) => size <= V ? (V - size) / 2 : clamp(v, V - size, 0);
  return { s, x: fit(VW / 2 - cx * s, c.W * s, VW), y: fit(VH / 2 - cy * s, c.H * s, VH) };
}
const lerpView = (a, b, p) => ({ s: a.s + (b.s - a.s) * p, x: a.x + (b.x - a.x) * p, y: a.y + (b.y - a.y) * p });
function renderCams(t) {
  for (const g of cams) {
    const c = g.cam, full = camView(c, null);
    let prev = full, state = full, startT = -1;
    for (const k of c.keys) if (t >= k.t) { prev = state; state = camView(c, k.bbox); startT = k.t; }
    let view = startT < 0 ? full : lerpView(prev, state, out3(clamp((t - startT) / 0.9)));
    const outAt = g.end - 1.5;
    if (c.keys.length && t > outAt) view = lerpView(view, full, out3(clamp((t - outAt) / 1.0)));
    c.inner.style.transform = `translate(${view.x}px, ${view.y}px) scale(${view.s})`;
  }
}
"""


CSS_PHOTO = """/* ảnh theo câu kể (data.beats): mỗi ảnh mang sẵn lớp phủ tối, chữ nằm thẳng trên nền chuyển sang trắng */
#bgl { position: absolute; inset: 0; overflow: hidden; }
#bgl .bimg { position: absolute; inset: 0; background-size: cover; background-position: center; opacity: 0; will-change: transform, opacity; filter: brightness(.84); }
#stage.photo #dots, #stage.photo #floor { opacity: 0; }
#stage.photo .dhead h2, #stage.photo .headline, #stage.photo .ntitle { color: #fff; text-shadow: 0 6px 30px rgba(0,0,0,.5); }
#stage.photo .headline .acc { color: var(--accent); }
#stage.photo .sub, #stage.photo .nsub { color: #E6EAF1; text-shadow: 0 4px 20px rgba(0,0,0,.45); }
#stage.photo #cap { color: #fff; text-shadow: 0 2px 3px rgba(0,0,0,.9), 0 0 6px rgba(0,0,0,.7), 0 3px 18px rgba(0,0,0,.75); }
#stage.photo #cap .on { color: #FFB547; }
#stage.photo #epno { color: #E6EAF1; } #stage.photo #epno b { color: #fff; }

/* captions */"""

JS_BEATS = r"""
// Ảnh theo câu kể: mờ chuyển 0,45 s, zoom chậm trong suốt câu; khi có ảnh thì chữ nằm trên nền chuyển sang trắng.
let beatNodes = [];
const SCRIM = 'linear-gradient(180deg, rgba(9,14,30,.74) 0%, rgba(9,14,30,.36) 30%, rgba(9,14,30,.44) 62%, rgba(9,14,30,.86) 100%)';
function buildBeats(data) {
  const bgl = document.getElementById('bgl');
  const loads = [];
  beatNodes = (data.beats || []).map(b => {
    const d = document.createElement('div'); d.className = 'bimg';
    d.style.backgroundImage = `${SCRIM}, url("${b.src}")`;
    bgl.appendChild(d);
    loads.push(new Promise(ok => { const im = new Image(); im.onload = im.onerror = ok; im.src = b.src; }));
    return { node: d, t0: b.t0, t1: b.t1 };
  });
  return Promise.all(loads);
}
function renderBeats(t) {
  let photo = false;
  for (const b of beatNodes) {
    const fin = b.t0 <= 0.01 ? 1 : clamp((t - b.t0) / 0.45);
    const a = fin * (1 - clamp((t - b.t1) / 0.45));
    b.node.style.opacity = a;
    b.node.style.transform = `scale(${1.03 + 0.07 * clamp((t - b.t0) / Math.max(1, b.t1 - b.t0))})`;
    if (a > 0.4) photo = true;
  }
  document.getElementById('stage').classList.toggle('photo', photo);
}
"""


def patch_beats(s: str) -> str:
    s = rep(s, "/* captions */", CSS_PHOTO)
    s = rep(s, 'data-track-index="2"></audio>', 'data-track-index="2"></audio>\n  <div id="bgl"></div>')
    s = rep(s, "let activeRanges = [], countUps = [];", "let activeRanges = [], countUps = [];" + JS_BEATS)
    s = rep(s, "function setup(data) {\n  DATA = data;", "function setup(data) {\n  DATA = data;\n  const beatsReady = buildBeats(data);")
    s = rep(s, "  return document.fonts.ready.then(() => true);\n}", "  return Promise.all([document.fonts.ready, beatsReady]).then(() => true);\n}")
    s = rep(s, "function renderAt(t) {\n", "function renderAt(t) {\n  renderBeats(t);\n")
    return s


def patch_flow(s: str) -> str:
    s = rep(s, "/* captions */", CSS_FLOW)
    # nút: icon ảnh (AWS) / emoji / svg có sẵn; nhãn xuống dòng
    s = rep(s, "const esc = s => String(s)", "const nodeIcon = e => e.img ? `<img src=\"${e.img}\">` : e.emoji ? `<span class=\"emo\">${esc(e.emoji)}</span>` : svg(e.icon);\nconst esc = s => String(s)")
    s = rep(s, "<div class=\"ic\">${svg(e.icon)}</div>", "<div class=\"ic\">${nodeIcon(e)}</div>")
    s = rep(s, "${e.layout || ''} ${e.style || ''}\" style=\"left:${e.x}px;top:${e.y}px\">",
            "${e.layout || ''} ${e.style || ''} ${e.wrap ? 'wrap' : ''}\" style=\"left:${e.x}px;top:${e.y}px\">")
    # camera
    s = rep(s, "let activeRanges = [], countUps = [];", "let activeRanges = [], countUps = [];" + CAMERA_JS)
    s = rep(s, "  layer.appendChild(inner);",
            "  layer.appendChild(inner);\n"
            "  if (d.camera) {\n"
            "    layer.classList.add('cam'); layer.style.left = '70px'; layer.style.width = maxW + 'px'; layer.style.height = maxH + 'px';\n"
            "    g.cam = { W: d.w, H: d.h, base: scale, inner, keys: [] }; cams.push(g);\n"
            "  }")
    s = rep(s, "function registerDiagramEvents(s, g) {\n  for (const ev of s.events || []) {",
            "function registerDiagramEvents(s, g) {\n  for (const ev of s.events || []) {\n"
            "    if (g.cam && ev.bbox) g.cam.keys.push({ t: ev.t, bbox: ev.bbox });")
    s = rep(s, "  for (const r of activeRanges)", "  renderCams(t);\n  for (const r of activeRanges)")
    # nhãn cảnh mẹo / kết lấy từ kịch bản (mặc định giữ chữ cho series ôn thi)
    s = rep(s, "${svg('bulb')}MẸO THI", "${svg('bulb')}${esc(s.label || 'MẸO THI')}")
    s = rep(s, "<div class=\"klabel\">ĐỀ HỎI</div>", "<div class=\"klabel\">${esc(s.q_label || 'ĐỀ HỎI')}</div>")
    s = rep(s, "<div class=\"klabel\">CHỌN</div>", "<div class=\"klabel\">${esc(s.a_label || 'CHỌN')}</div>")
    s = rep(s, "const lab = el('<div class=\"nlabel\">TẬP SAU</div>');", "const lab = el(`<div class=\"nlabel\">${esc(s.label || 'TẬP SAU')}</div>`);")
    # cảnh mở đầu hiện ngay khung đầu tiên (móc câu trong giây đầu)
    s = rep(s, "function buildTitle(s, sec) {\n  sec.classList.add('center');",
            "function buildTitle(s, sec) {\n  sec.classList.add('center');\n  const b0 = s.start <= 0.001 ? -1 : s.start;")
    s = rep(s, "anim(tok, s.start + 0.25 + i * 0.12, 'up', 0.55);", "anim(tok, b0 + 0.25 + i * 0.12, 'up', 0.55);")
    s = rep(s, "sec.append(tag, h); anim(tag, s.start + 0.05, 'up');", "sec.append(tag, h); anim(tag, b0 + 0.05, 'up');")
    s = rep(s, "anim(sub, s.start + 0.6, 'up');", "anim(sub, b0 + 0.6, 'up');")
    s = rep(s, "const pin = out3(clamp((t - s.start) / 0.4)), pout",
            "const pin = s.start <= 0.001 ? 1 : out3(clamp((t - s.start) / 0.4)), pout")
    return s


def main() -> None:
    s = SRC.read_text(encoding="utf-8")
    s = rep(s, "<title>AWS SAA studio</title>", "<title>Academic composition</title>")
    # chữ hoa tiếng Việt có dấu trên (Ã, Ú) lẫn dấu dưới (Ị, Ộ): 1.02 làm dấu hai dòng dính vào nhau
    s = rep(s, ".headline { margin-top: 44px; font-weight: 700; line-height: 1.02;",
            ".headline { margin-top: 44px; font-weight: 700; line-height: 1.14;")
    s = rep(s, "/* captions */", CSS_NEW)
    s = rep(s, '<div id="stage">',
            '<div id="stage" data-composition-id="main" data-start="0" data-duration="__DURATION__" data-width="1080" data-height="1920">\n'
            '  <audio class="clip" src="narration.wav" data-start="0" data-duration="__DURATION__" data-media-start="0" data-track-index="2"></audio>')
    s = rep(s, "<div class=\"step\"><b>${esc(s.step || '')}</b>${esc(s.kicker || '')}</div>",
            "<div class=\"step\">${s.step ? `<b>${esc(s.step)}</b>` : ''}${esc(s.kicker || '')}</div>")
    s = rep(s, "function buildTip(s, sec) {", JS_BUILDERS)
    s = rep(s, "let DATA, anims = [], classEvents = [], focusEvents = [], sections = [], capState = { idx: -2, spans: [] };",
            "let DATA, anims = [], classEvents = [], focusEvents = [], sections = [], capState = { idx: -2, spans: [] };\n"
            "let activeRanges = [], countUps = [];")
    s = rep(s, "    else if (s.type === 'tip') buildTip(s, sec);",
            "    else if (s.type === 'bullets') buildBullets(s, sec);\n"
            "    else if (s.type === 'compare') buildCompare(s, sec);\n"
            "    else if (s.type === 'stat') buildStat(s, sec);\n"
            "    else if (s.type === 'tip') buildTip(s, sec);")
    s = rep(s, "  document.getElementById('series').textContent = data.meta.series;\n"
               "  document.getElementById('epno').innerHTML = `TẬP <b>${String(data.meta.ep).padStart(2, '0')}</b> / ${data.meta.total}`;",
            "  document.getElementById('series').textContent = data.meta.series || 'HỌC NHANH';\n"
            "  document.getElementById('epno').innerHTML = data.meta.ep ? `TẬP <b>${String(data.meta.ep).padStart(2, '0')}</b>"
            "${data.meta.total ? ` / ${data.meta.total}` : ''}` : '';")
    s = rep(s, "      case 'fade': n.style.opacity = e; break;",
            "      case 'fade': n.style.opacity = e; break;\n"
            "      case 'pop2': { const b = p <= 0 ? 0 : back(p); n.style.opacity = clamp(p * 2.5); n.style.transform = `scale(${0.4 + 0.6 * b})`; break; }")
    s = rep(s, "  renderCaption(t);\n  return true;",
            "  for (const r of activeRanges) r.node.classList.toggle('on', t >= r.from && t < r.to);\n"
            "  for (const c of countUps) { const p = out3(clamp((t - c.at) / 0.9)); c.node.textContent = Math.round(c.target * p) + c.suffix; }\n"
            "  renderCaption(t);\n  return true;")
    s = patch_flow(s)
    s = patch_beats(s)
    s = rep(s, "window.setup = setup; window.renderAt = renderAt;\n</script>", HF_TAIL)
    DST.write_text(s, encoding="utf-8")
    print(f"đã ghi {DST} ({len(s)} ký tự)")


if __name__ == "__main__":
    main()
