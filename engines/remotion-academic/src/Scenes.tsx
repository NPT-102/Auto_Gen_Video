import React from "react";
import { C, Data, Icon, Scene, clamp, out3, pop, prog, up } from "./lib";

const glass: React.CSSProperties = {
  background: "linear-gradient(180deg, rgba(255,255,255,.09), rgba(255,255,255,.04))",
  border: "2px solid rgba(255,255,255,.13)", borderRadius: 30, boxShadow: "0 20px 50px rgba(0,0,0,.35)",
};
const gradText: React.CSSProperties = {
  background: `linear-gradient(90deg, ${C.cyan}, ${C.violet})`, WebkitBackgroundClip: "text", backgroundClip: "text", color: "transparent",
};

export const Head: React.FC<{ s: Scene; t: number }> = ({ s, t }) => (
  <div style={{ position: "absolute", left: 0, right: 0, top: 0, ...up(t, s.start + 0.05) }}>
    <div style={{ display: "flex", alignItems: "center", gap: 16, fontWeight: 700, fontSize: 28, letterSpacing: ".14em", color: C.cyan }}>
      {s.step && <span style={{ display: "grid", placeItems: "center", minWidth: 62, height: 48, padding: "0 14px", borderRadius: 999,
        background: `linear-gradient(135deg, ${C.violet}, #6366F1)`, color: "#fff", letterSpacing: 0, boxShadow: "0 0 24px rgba(139,92,246,.6)" }}>{s.step}</span>}
      {s.kicker}
    </div>
    <div style={{ marginTop: 18, fontWeight: 700, fontSize: 64, lineHeight: 1.12, color: C.ink }}>{s.heading}</div>
  </div>
);

export const TitleScene: React.FC<{ s: Scene; t: number; data: Data }> = ({ s, t, data }) => {
  const b0 = s.start <= 0.001 ? -1 : s.start;
  return (
  <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", justifyContent: "center", alignItems: "center", textAlign: "center" }}>
    {data.meta.ep ? (
      <div style={{ width: 150, height: 150, borderRadius: "50%", display: "grid", placeItems: "center", fontWeight: 700, fontSize: 76, color: "#fff",
        background: `radial-gradient(circle at 30% 30%, #A78BFA, ${C.violet} 55%, #5B21B6)`, boxShadow: "0 0 60px rgba(139,92,246,.7)", ...pop(t, b0, 0.6, 0.3) }}>
        {data.meta.ep}
      </div>
    ) : null}
    <div style={{ marginTop: 44, fontWeight: 700, fontSize: 30, letterSpacing: ".24em", color: C.cyan, ...up(t, b0 + 0.15) }}>{s.tag}</div>
    <div style={{ marginTop: 22, fontWeight: 700, fontSize: s.size ? Math.min(s.size, 200) : 150, lineHeight: 1.14, textTransform: "uppercase", letterSpacing: "-.02em" }}>
      {(s.headline || []).map(([text, acc]: [string, boolean], i: number) => (
        <span key={i} style={{ display: "inline-block", margin: "0 .12em", ...(acc ? gradText : { color: C.ink }), ...up(t, b0 + 0.3 + i * 0.12) }}>{text}</span>
      ))}
    </div>
    {s.sub && <div style={{ marginTop: 30, fontSize: 50, color: "#CBD5E1", lineHeight: 1.3, ...up(t, b0 + 0.55) }}>{s.sub}</div>}
    {s.chips && (
      <div style={{ marginTop: 60, display: "flex", flexWrap: "wrap", justifyContent: "center", gap: 18 }}>
        {s.chips.map((c: any, i: number) => (
          <div key={i} style={{ ...glass, borderRadius: 999, padding: "16px 30px", fontWeight: 700, fontSize: 34, color: C.ink, ...up(t, c.t ?? b0 + 0.9 + i * 0.15) }}>
            <span style={{ color: C.cyan, marginRight: 12 }}>{String(i + 1).padStart(2, "0")}</span>{c.text}
          </div>
        ))}
      </div>
    )}
  </div>
);
};

export const BulletsScene: React.FC<{ s: Scene; t: number }> = ({ s, t }) => {
  const items = s.items || [];
  const times: number[] = items.map((it: any, i: number) => it.t ?? s.start + 0.5 + i * 0.9);
  return (
    <>
      <Head s={s} t={t} />
      <div style={{ position: "absolute", left: 0, right: 0, top: 260, bottom: 90, display: "flex", flexDirection: "column", justifyContent: "center", gap: 26 }}>
        {items.map((it: any, i: number) => {
          const on = t >= times[i] && t < (i + 1 < items.length ? times[i + 1] : s.end);
          return (
            <div key={i} style={{ ...glass, display: "flex", alignItems: "center", gap: 28, padding: "32px 36px", ...up(t, times[i]),
              border: `2px solid ${on ? C.violet : "rgba(255,255,255,.13)"}`, boxShadow: on ? "0 0 0 6px rgba(139,92,246,.18), 0 0 50px rgba(139,92,246,.45)" : glass.boxShadow }}>
              <div style={{ flex: "none", width: 80, height: 80, borderRadius: "50%", display: "grid", placeItems: "center", fontWeight: 700, fontSize: 38,
                color: "#fff", background: on ? `linear-gradient(135deg, ${C.violet}, #6366F1)` : "rgba(255,255,255,.1)" }}>{i + 1}</div>
              <div style={{ fontWeight: 700, fontSize: 46, lineHeight: 1.25, color: C.ink }}>{it.text}</div>
            </div>
          );
        })}
      </div>
    </>
  );
};

export const CompareScene: React.FC<{ s: Scene; t: number }> = ({ s, t }) => {
  const ta = s.left?.t ?? s.start + 0.4, tb = s.right?.t ?? ta + 1.2;
  const side = (d: any, color: string, at: number) => (
    <div style={{ ...glass, padding: "40px 44px 34px", borderTop: `10px solid ${color}`, ...up(t, at) }}>
      <div style={{ fontWeight: 700, fontSize: 56, color }}>{d?.title}</div>
      {(d?.points || []).map((p: string, i: number) => (
        <div key={i} style={{ display: "flex", gap: 18, alignItems: "baseline", marginTop: 14, fontSize: 40, lineHeight: 1.32, color: "#CBD5E1" }}>
          <span style={{ width: 14, height: 14, flex: "none", borderRadius: "50%", background: color, transform: "translateY(-6px)" }} />{p}
        </div>
      ))}
    </div>
  );
  return (
    <>
      <Head s={s} t={t} />
      <div style={{ position: "absolute", left: 0, right: 0, top: 260, bottom: 90, display: "flex", flexDirection: "column", justifyContent: "center" }}>
        {side(s.left, C.cyan, ta)}
        <div style={{ alignSelf: "center", margin: "-26px 0", zIndex: 2, width: 104, height: 104, borderRadius: "50%", display: "grid", placeItems: "center",
          fontWeight: 700, fontSize: 36, color: "#fff", background: `linear-gradient(135deg, ${C.violet}, #EC4899)`, boxShadow: "0 0 40px rgba(236,72,153,.55)",
          ...pop(t, (ta + tb) / 2, 0.45, 0.4) }}>VS</div>
        {side(s.right, C.amber, tb)}
      </div>
    </>
  );
};

export const StatScene: React.FC<{ s: Scene; t: number }> = ({ s, t }) => (
  <>
    <Head s={s} t={t} />
    <div style={{ position: "absolute", left: 0, right: 0, top: 260, bottom: 90, display: "flex", flexDirection: "column", justifyContent: "center", gap: 30 }}>
      {(s.stats || []).map((st: any, i: number, all: any[]) => {
        const one = all.length === 1;
        const at = st.t ?? s.start + 0.5 + i * 0.9;
        const m = /^(\d{1,6})(\D*)$/.exec(String(st.value).trim());
        const value = m ? Math.round(+m[1] * out3(clamp((t - at) / 0.9))) + m[2] : st.value;
        return (
          <div key={i} style={{ ...glass, padding: one ? "56px 56px 60px" : "36px 46px 38px", ...up(t, at) }}>
            <div style={{ fontWeight: 700, fontSize: one ? 260 : 150, lineHeight: 1, letterSpacing: "-.03em", ...gradText }}>{value}</div>
            <div style={{ marginTop: 14, fontSize: one ? 52 : 42, fontWeight: 700, color: "#CBD5E1" }}>{st.label}</div>
          </div>
        );
      })}
    </div>
  </>
);

export const TipScene: React.FC<{ s: Scene; t: number }> = ({ s, t }) => (
  <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", justifyContent: "center" }}>
    <div style={{ alignSelf: "flex-start", display: "flex", alignItems: "center", gap: 16, padding: "16px 30px", borderRadius: 999, fontWeight: 700, fontSize: 34,
      letterSpacing: ".12em", color: "#1C1917", background: "linear-gradient(90deg,#FDE047,#F59E0B)", boxShadow: "0 0 40px rgba(245,158,11,.5)", ...up(t, s.start + 0.05) }}>
      <Icon name="bulb" size={40} color="#1C1917" /> {s.label || "MẸO THI"}
    </div>
    <div style={{ ...glass, marginTop: 54, padding: "44px 48px", ...up(t, s.start + 0.3) }}>
      <div style={{ fontWeight: 700, fontSize: 26, letterSpacing: ".16em", color: C.muted }}>{s.q_label || "ĐỀ HỎI"}</div>
      <div style={{ marginTop: 18, fontWeight: 700, fontSize: 48, lineHeight: 1.32, color: C.ink }}>{s.question}</div>
    </div>
    <div style={{ alignSelf: "center", margin: "26px 0", opacity: out3(prog(t, s.answer_t - 0.25, 0.3)) }}><Icon name="down" size={64} color={C.cyan} width={2.4} /></div>
    <div style={{ ...glass, padding: "40px 48px", border: `3px solid ${C.cyan}`, boxShadow: "0 0 60px rgba(34,211,238,.35)", ...up(t, s.answer_t) }}>
      <div style={{ fontWeight: 700, fontSize: 26, letterSpacing: ".16em", color: C.cyan }}>{s.a_label || "CHỌN"}</div>
      <div style={{ marginTop: 14, fontWeight: 700, fontSize: 76, color: C.ink }}>{s.answer}</div>
    </div>
  </div>
);

export const NextScene: React.FC<{ s: Scene; t: number }> = ({ s, t }) => (
  <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", justifyContent: "center", alignItems: "center", textAlign: "center" }}>
    <div style={{ fontWeight: 700, fontSize: 34, letterSpacing: ".32em", color: C.cyan, ...up(t, s.start + 0.05) }}>{s.label || "TẬP SAU"}</div>
    <div style={{ marginTop: 30, fontWeight: 700, fontSize: 88, lineHeight: 1.1, textTransform: "uppercase", color: C.ink, ...up(t, s.start + 0.25, 0.6) }}>{s.title}</div>
    <div style={{ marginTop: 44, width: 160 * out3(prog(t, s.start + 0.55, 0.6)), height: 8, borderRadius: 4, background: `linear-gradient(90deg, ${C.cyan}, ${C.violet})` }} />
    {s.sub && <div style={{ marginTop: 40, fontSize: 40, color: C.muted, lineHeight: 1.35, ...up(t, s.start + 0.8) }}>{s.sub}</div>}
  </div>
);

/** Phụ đề kiểu TikTok: cả cụm hiện trắng, từ đang đọc đổi màu và nảy nhẹ. */
export const Captions: React.FC<{ data: Data; t: number }> = ({ data, t }) => {
  const P = data.phrases, W = data.words;
  let idx = -1;
  for (let i = 0; i < P.length; i++) { if (P[i].start <= t) idx = i; else break; }
  if (idx >= 0 && t > P[idx].end + 0.5 && !(P[idx + 1] && P[idx + 1].start <= t)) idx = -1;
  if (idx < 0) return null;
  let cur = -1;
  for (let w = P[idx].from; w <= P[idx].to; w++) if (W[w].start <= t) cur = w;
  return (
    <div style={{ position: "absolute", left: 80, right: 80, top: 1470, textAlign: "center", fontWeight: 700, fontSize: 60, lineHeight: 1.3 }}>
      {Array.from({ length: P[idx].to - P[idx].from + 1 }, (_, k) => P[idx].from + k).map((w) => {
        const on = w === cur && t <= W[w].end + 0.35;
        const k = on ? out3(clamp((t - W[w].start) / 0.12)) : 0;
        return (
          <span key={w} style={{ display: "inline-block", margin: "0 .2em", color: on ? "#FDE047" : "#F8FAFC", transform: `scale(${1 + 0.1 * k})`,
            textShadow: "0 4px 18px rgba(0,0,0,.85), 0 0 2px rgba(0,0,0,.9)" }}>{W[w].display}</span>
        );
      })}
    </div>
  );
};
