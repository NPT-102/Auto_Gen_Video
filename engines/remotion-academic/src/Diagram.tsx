import React from "react";
import { C, Diagram as D, DiagramEl, FONT, Icon, Scene, clamp, glow, out3, pop, prog } from "./lib";

type Timing = { show: Record<string, number>; add: { id: string; cls: string; t: number }[]; focus: { id: string; t: number }[] };

/** Gom mọi sự kiện của các cảnh dùng chung sơ đồ này thành mốc thời gian theo id phần tử. */
export function diagramTiming(scenes: Scene[], id: string): Timing {
  const out: Timing = { show: {}, add: [], focus: [] };
  for (const s of scenes) {
    if (s.type !== "diagram" || s.diagram !== id) continue;
    for (const ev of s.events || []) {
      for (const el of ev.show || []) if (out.show[el] === undefined) out.show[el] = ev.t;
      for (const a of [].concat(ev.add || [])) out.add.push({ ...(a as any), t: ev.t });
      for (const f of ev.focus || []) out.focus.push({ id: f, t: ev.t });
    }
  }
  return out;
}

const TINT: Record<string, { border: string; bg: string; label: string }> = {
  pub: { border: C.green, bg: "rgba(34,197,94,.13)", label: "#4ADE80" },
  pri: { border: C.blue, bg: "rgba(59,130,246,.15)", label: "#93C5FD" },
  db: { border: C.purple, bg: "rgba(168,85,247,.15)", label: "#D8B4FE" },
  "tone-blue": { border: C.blue, bg: "rgba(59,130,246,.15)", label: "#93C5FD" },
  "tone-green": { border: C.green, bg: "rgba(34,197,94,.13)", label: "#4ADE80" },
  "tone-purple": { border: C.purple, bg: "rgba(168,85,247,.15)", label: "#D8B4FE" },
  "tone-orange": { border: C.amber, bg: "rgba(245,158,11,.14)", label: "#FBBF24" },
  "tone-red": { border: C.red, bg: "rgba(239,68,68,.14)", label: "#FCA5A5" },
  "tone-gray": { border: "rgba(255,255,255,.3)", bg: "rgba(255,255,255,.05)", label: "#CBD5E1" },
};

// ---- camera cho sơ đồ tự dàn: zoom vào phần vừa giảng, cuối cảnh lùi ra toàn cảnh ----
type View = { s: number; x: number; y: number };
const VW = 940, VH = 1050;
function camView(W: number, H: number, base: number, b: number[] | null): View {
  if (!b) return { s: base, x: (VW - W * base) / 2, y: (VH - H * base) / 2 };
  const bw = Math.max(b[2] + 160, W * 0.5), bh = Math.max(b[3] + 160, H * 0.42);
  const s = clamp(Math.min(VW / bw, VH / bh), base, Math.max(base, Math.min(base * 1.9, 1.3)));
  const cx = b[0] + b[2] / 2, cy = b[1] + b[3] / 2;
  const fit = (v: number, size: number, V: number) => (size <= V ? (V - size) / 2 : clamp(v, V - size, 0));
  return { s, x: fit(VW / 2 - cx * s, W * s, VW), y: fit(VH / 2 - cy * s, H * s, VH) };
}
const lerpView = (a: View, b: View, p: number): View => ({ s: a.s + (b.s - a.s) * p, x: a.x + (b.x - a.x) * p, y: a.y + (b.y - a.y) * p });
function cameraAt(t: number, W: number, H: number, base: number, keys: { t: number; bbox: number[] }[], end: number): View {
  const full = camView(W, H, base, null);
  let prev = full, state = full, startT = -1;
  for (const k of keys) if (t >= k.t) { prev = state; state = camView(W, H, base, k.bbox); startT = k.t; }
  let view = startT < 0 ? full : lerpView(prev, state, out3(clamp((t - startT) / 0.9)));
  if (keys.length && t > end - 1.5) view = lerpView(view, full, out3(clamp((t - (end - 1.5)) / 1.0)));
  return view;
}
const NODE: Record<string, { border: string; bg: string; stroke: string }> = {
  "": { border: "rgba(255,255,255,.22)", bg: "rgba(15,23,42,.92)", stroke: "#E2E8F0" },
  accent: { border: C.amber, bg: "rgba(245,158,11,.14)", stroke: C.amber },
  blue: { border: "#60A5FA", bg: "rgba(15,23,42,.92)", stroke: "#60A5FA" },
  purple: { border: "#C084FC", bg: "rgba(15,23,42,.92)", stroke: "#C084FC" },
  dark: { border: "#F8FAFC", bg: "#F8FAFC", stroke: "#0F172A" },
};

function polyLength(pts: number[][]) {
  let L = 0;
  for (let i = 1; i < pts.length; i++) L += Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]);
  return L;
}

const Arrow: React.FC<{ e: DiagramEl; t: number; at: number }> = ({ e, t, at }) => {
  const pts: number[][] = e.points;
  const d = "M" + pts.map((p) => p.join(" ")).join(" L");
  const style = e.style || "solid";
  const color = style === "flow" ? C.amber : style === "blocked" ? C.red : "#94A3B8";
  const p = prog(t, at, style === "solid" ? 0.7 : 0.5);
  if (p <= 0) return null;
  const L = polyLength(pts);
  const [a, b] = [pts[pts.length - 2], pts[pts.length - 1]];
  const ang = (Math.atan2(b[1] - a[1], b[0] - a[0]) * 180) / Math.PI;
  const showHead = e.head !== false && (style !== "solid" || p >= 0.92);
  const dash = style === "flow" ? "16 14" : style === "blocked" ? "10 10" : `${L} ${L}`;
  const offset = style === "flow" ? -(t - at) * 70 : style === "solid" ? L * (1 - out3(p)) : 0;
  return (
    <g opacity={style === "solid" ? 1 : out3(p)}>
      <path d={d} fill="none" stroke={color} strokeWidth={style === "flow" ? 6 : 4} strokeLinecap="round" strokeLinejoin="round"
        strokeDasharray={dash} strokeDashoffset={offset} style={style === "flow" ? { filter: `drop-shadow(0 0 6px ${C.amber})` } : undefined} />
      {showHead && <path d="M-12 -9 L4 0 L-12 9 z" fill={color} transform={`translate(${b[0]} ${b[1]}) rotate(${ang})`} />}
    </g>
  );
};

export const DiagramLayer: React.FC<{ diagram: D; scenes: Scene[]; id: string; t: number; opacity: number }> = ({ diagram, scenes, id, t, opacity }) => {
  const tm = diagramTiming(scenes, id);
  const scale = Math.min(940 / diagram.w, 1050 / diagram.h);
  const cls = (elId: string) => tm.add.filter((a) => a.id === elId && t >= a.t).map((a) => a.cls);
  const focusK = (elId: string) => Math.max(0, ...tm.focus.filter((f) => f.id === elId).map((f) => glow(t, f.t)));
  const glowCss = (k: number, color = C.violet) =>
    k > 0.001 ? `0 0 0 ${12 * k}px ${color}33, 0 0 ${50 * k}px ${color}99` : undefined;

  const boxes: React.ReactNode[] = [], arrows: React.ReactNode[] = [], over: React.ReactNode[] = [];
  for (const e of diagram.elements) {
    const at = tm.show[e.id];
    if (at === undefined || t < at) continue;
    if (e.kind === "box") {
      const parts: string[] = String(e.style || "").split(/\s+/);
      const tint = [...cls(e.id), ...parts].map((c) => TINT[c]).find(Boolean);
      const st = parts[0] === "group" ? "subnet" : parts[0];
      const base: React.CSSProperties = {
        position: "absolute", left: e.x, top: e.y, width: e.w, height: e.h, borderRadius: 22,
        border: st === "region" || st === "az" ? "3px dashed rgba(148,163,184,.45)" : st === "vpc" ? "3.5px solid #E2E8F0" : `2.5px solid ${tint ? tint.border : "rgba(255,255,255,.16)"}`,
        background: st === "subnet" ? (tint ? tint.bg : "rgba(255,255,255,.04)") : st === "vpc" ? "rgba(255,255,255,.03)" : "transparent",
        boxShadow: glowCss(focusK(e.id)), opacity: out3(prog(t, at, 0.5)), transform: `scale(${0.96 + 0.04 * out3(prog(t, at, 0.5))})`,
      };
      const label = tint && e.label_on ? e.label_on : e.label;
      const lpos: React.CSSProperties = st === "region" ? { left: 6, top: -40 } : st === "az" ? { right: 16, top: 10 } : { left: 18, top: 12 };
      boxes.push(
        <div key={e.id} style={base}>
          <div style={{ position: "absolute", ...lpos, fontWeight: 700, fontSize: st === "vpc" ? 30 : 27, letterSpacing: ".05em", whiteSpace: "nowrap",
            color: st === "vpc" ? "#F8FAFC" : tint ? tint.label : "#94A3B8" }}>{label}</div>
        </div>,
      );
    } else if (e.kind === "arrow") {
      arrows.push(<Arrow key={e.id} e={e} t={t} at={at} />);
    } else if (e.kind === "node") {
      const small = e.size === "sm";
      const half = small ? 38 : 50;
      const pal = NODE[e.style || ""] || NODE[""];
      const row = e.layout === "row";
      const pp = pop(t, at, 0.55);
      over.push(
        <div key={e.id} style={{ position: "absolute", left: e.x, top: e.y, display: "flex", flexDirection: row ? "row" : "column", alignItems: "center", gap: row ? 14 : 8,
          opacity: pp.opacity, transform: `translate(${row ? `-${half}px` : "-50%"}, -${half}px) ${pp.transform}` }}>
          <div style={{ width: half * 2, height: half * 2, flex: "none", borderRadius: small ? 19 : 22, background: e.img ? "#F8FAFC" : pal.bg, border: `2.5px solid ${pal.border}`,
            display: "grid", placeItems: "center", boxShadow: glowCss(focusK(e.id), C.amber) ?? "0 10px 26px rgba(0,0,0,.45)" }}>
            {e.img ? <img src={e.img} style={{ width: small ? 52 : 74, height: small ? 52 : 74, objectFit: "contain" }} />
              : e.emoji ? <span style={{ fontSize: small ? 44 : 60, lineHeight: 1, fontFamily: "'Segoe UI Emoji', 'Noto Color Emoji', sans-serif" }}>{e.emoji}</span>
              : <Icon name={e.icon} size={small ? 44 : 58} color={pal.stroke} />}
          </div>
          {e.label && <div style={{ fontWeight: 700, fontSize: small ? 24 : 27, color: "#F1F5F9", padding: "3px 12px", borderRadius: 10,
            background: "rgba(6,10,24,.85)", ...(e.wrap ? { whiteSpace: "normal", width: 214, textAlign: "center", lineHeight: 1.16 } : { whiteSpace: "nowrap" }) }}>{e.label}</div>}
        </div>,
      );
    } else if (e.kind === "bar") {
      over.push(
        <div key={e.id} style={{ position: "absolute", left: e.x, top: e.y, width: e.w, height: e.h, borderRadius: 14, display: "flex", alignItems: "center",
          justifyContent: "center", gap: 14, color: "#fff", fontWeight: 700, fontSize: 27, background: "linear-gradient(90deg,#7C3AED,#4F46E5)",
          boxShadow: "0 10px 30px rgba(124,58,237,.45)", opacity: out3(prog(t, at, 0.45)) }}>
          {e.icon && <Icon name={e.icon} size={34} color="#fff" />}<span>{e.label}</span>
        </div>,
      );
    } else if (e.kind === "text") {
      over.push(
        <div key={e.id} style={{ position: "absolute", left: e.x, top: e.y, padding: "4px 14px", borderRadius: 10, background: "rgba(245,158,11,.16)",
          color: "#FBBF24", fontWeight: 700, fontSize: 27, whiteSpace: "nowrap", opacity: out3(prog(t, at, 0.45)) }}>{e.text}</div>,
      );
    } else if (e.kind === "badge") {
      const left = e.style === "left";
      over.push(
        <div key={e.id} style={{ position: "absolute", left: e.x, top: e.y, display: "flex", flexDirection: left ? "row-reverse" : "row", alignItems: "center",
          gap: 10, transform: left ? "translate(calc(-100% + 26px), -26px)" : "translate(-26px, -26px)", opacity: out3(prog(t, at, 0.45)) }}>
          <div style={{ width: 52, height: 52, borderRadius: "50%", background: C.red, display: "grid", placeItems: "center", boxShadow: "0 0 24px rgba(239,68,68,.6)" }}>
            <Icon name="x" size={24} color="#fff" width={3.2} />
          </div>
          {e.label && <span style={{ fontWeight: 700, fontSize: 25, color: "#FCA5A5", background: "rgba(6,10,24,.9)", padding: "3px 10px", borderRadius: 8, whiteSpace: "nowrap" }}>{e.label}</span>}
        </div>,
      );
    }
  }
  if ((diagram as any).camera) {
    const keys: { t: number; bbox: number[] }[] = [];
    let end = 0;
    for (const s of scenes) {
      if (s.type !== "diagram" || s.diagram !== id) continue;
      end = Math.max(end, s.end);
      for (const ev of s.events || []) if (ev.bbox) keys.push({ t: ev.t, bbox: ev.bbox });
    }
    const v = cameraAt(t, diagram.w, diagram.h, scale, keys, end);
    return (
      <div style={{ position: "absolute", left: 70, top: 385, width: VW, height: VH, overflow: "hidden", borderRadius: 28, opacity, fontFamily: FONT }}>
        <div style={{ position: "absolute", left: 0, top: 0, width: diagram.w, height: diagram.h, transform: `translate(${v.x}px, ${v.y}px) scale(${v.s})`, transformOrigin: "0 0" }}>
          {boxes}
          <svg width={diagram.w} height={diagram.h} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>{arrows}</svg>
          {over}
        </div>
      </div>
    );
  }
  return (
    <div style={{ position: "absolute", left: 70 + (940 - diagram.w * scale) / 2, top: 385, width: diagram.w * scale, height: diagram.h * scale, opacity, fontFamily: FONT }}>
      <div style={{ position: "absolute", left: 0, top: 0, width: diagram.w, height: diagram.h, transform: `scale(${scale})`, transformOrigin: "0 0" }}>
        {boxes}
        <svg width={diagram.w} height={diagram.h} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>{arrows}</svg>
        {over}
      </div>
    </div>
  );
};

export const sceneAlpha = (t: number, start: number, end: number) =>
  Math.min(start <= 0.001 ? 1 : out3(clamp((t - start) / 0.4)), clamp((end - t) / 0.3));
