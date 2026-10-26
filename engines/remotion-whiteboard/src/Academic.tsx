import { loadFont } from "@remotion/fonts";
import React from "react";
import { AbsoluteFill, Audio, Img, OffthreadVideo, Sequence, interpolate, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { C, FONT, Props, WhiteboardLayer, clamp } from "./lib";
import { Captions } from "./Scenes";

loadFont({ family: "BVP", url: staticFile("fonts/BeVietnamPro-Medium.ttf"), weight: "500" });
loadFont({ family: "BVP", url: staticFile("fonts/BeVietnamPro-Bold.ttf"), weight: "700" });

const Paper: React.FC = () => (
  // Drawings now arrive as transparent frames, so the board can have a little depth (a faint light falloff toward
  // the edges) without the old problem: an opaque clip on a textured board showed up as a visible rectangle.
  <AbsoluteFill style={{
    background: "radial-gradient(ellipse 85% 70% at 50% 42%, #fdfdfa 0%, #f9f9f4 62%, #f1f1ea 100%)",
  }} />
);

// Do not move an empty new board across the frame. Clear the completed board
// with a narrow left-to-right wipe just before the first new stroke. Fading
// every object at once looked like a browser refresh.
const PAGE_WIPE = 0.22;

const WhiteboardClips: React.FC<{ data: Props["data"] }> = ({ data }) => {
  const { fps } = useVideoConfig();
  const frame = useCurrentFrame();
  const pages = data.whiteboard_pages ?? (data.beats || []).map((beat) => ({
    t0: beat.t0, t1: beat.t1, layers: beat.layers || [], motion: beat.motion,
  }));
  const t = frame / fps;
  return (
    <>
      {pages.map((page, index) => {
        if (!page.layers?.length) return null;
        const next = pages[index + 1];
        const nextFirstStroke = next?.layers?.length
          ? Math.min(...next.layers.map((layer) => layer.t0)) : null;
        // A page may end before the narration reaches the first drawing on
        // the next page. Retain it through that pause so the viewer never
        // sees a blank board with a hand waiting in the middle.
        // Sequences are placed on integer frames.  Keep the old board for
        // the frame on which the next drawing first appears; otherwise its
        // clip reaches 100% one frame before the incoming stroke and the
        // result looks like a page refresh.
        const nextDrawFrame = nextFirstStroke === null ? null : Math.round(nextFirstStroke * fps);
        const visualEndFrame = nextDrawFrame === null
          ? Math.round(page.t1 * fps)
          : Math.max(Math.round(page.t1 * fps), nextDrawFrame + 1);
        const visualEnd = visualEndFrame / fps;
        const wipeStart = nextFirstStroke === null ? visualEnd : Math.max(page.t1, visualEnd - PAGE_WIPE);
        const from = Math.max(0, Math.round(page.t0 * fps));
        const duration = Math.max(1, visualEndFrame - from);
        const wiping = nextFirstStroke !== null && visualEnd - wipeStart > 0.01;
        const wipe = wiping ? interpolate(t, [wipeStart, visualEnd], [0, 100], {
          extrapolateLeft: "clamp", extrapolateRight: "clamp" }) : 1;
        return (
          <Sequence key={index} from={from} durationInFrames={duration} layout="none">
            <AbsoluteFill style={wiping ? { clipPath: `inset(0 0 0 ${wipe}%)` } : undefined}>
              <LayeredBoard layers={page.layers} sceneStart={page.t0} pageEnd={visualEnd} motion={page.motion} />
            </AbsoluteFill>
          </Sequence>
        );
      })}
    </>
  );
};

// ---- bàn tay cầm bút: một bàn tay cho cả trang, đi theo đường bút của từng lớp, lướt sang hình kế tiếp,
// ---- rời khung khi phải chờ lâu (lời đọc chưa tới hình sau) rồi quay lại đúng lúc
const HAND = { src: "whiteboard/hand-marker.png", size: 900, tip: [60, 60] as const, scale: 0.78 };
const OFFSTAGE = { x: 1.22, y: 1.08 };   // đầu bút ngoài khung, góc dưới bên phải
const HAND_MOVE = 0.42;                  // giây để vào / ra khung
const GLIDE_MAX = 1.6;                   // khoảng nghỉ ngắn hơn thế thì bút lướt thẳng sang hình sau

type Pen = { x: number; y: number; down: boolean; lift: number };

const easeInOut = (p: number) => (p < 0.5 ? 2 * p * p : 1 - Math.pow(-2 * p + 2, 2) / 2);
const mix = (a: Pen | typeof OFFSTAGE, b: Pen | typeof OFFSTAGE, p: number): Pen => ({
  x: a.x + (b.x - a.x) * p, y: a.y + (b.y - a.y) * p, down: false, lift: 1,
});
const point = (pen: [number, number, number][], i: number): Pen => {
  const k = Math.max(0, Math.min(pen.length - 1, i));
  const [x, y, d] = pen[k];
  // độ nhấc tay = tỉ lệ khung nhấc bút trong 5 khung quanh đó: giữa hai chữ cái bút chỉ rời giấy một chốc,
  // nhấc / hạ theo từng khung thì bàn tay rung lên xuống
  let up = 0, n = 0;
  for (let j = Math.max(0, k - 2); j <= Math.min(pen.length - 1, k + 2); j++) { n++; if (!pen[j][2]) up++; }
  return { x, y, down: d > 0, lift: up / n };
};

export const penAt = (layers: WhiteboardLayer[], second: number): Pen | null => {
  const drawn = layers.filter((l) => l.pen && l.pen.length);
  if (!drawn.length) return null;
  for (const l of drawn) {
    if (second >= l.t0 && second < l.draw_t1) {
      const n = l.pen!.length;
      return point(l.pen!, Math.floor(((second - l.t0) / Math.max(1e-6, l.draw_t1 - l.t0)) * n));
    }
  }
  const prev = [...drawn].reverse().find((l) => l.draw_t1 <= second);
  const next = drawn.find((l) => l.t0 > second);
  const end = prev ? point(prev.pen!, prev.pen!.length - 1) : null;
  const start = next ? point(next.pen!, 0) : null;
  if (end && start && next && prev) {
    const gap = next.t0 - prev.draw_t1;
    if (gap <= GLIDE_MAX) return mix(end, start, easeInOut(clamp((second - prev.draw_t1) / gap)));
    if (second < prev.draw_t1 + HAND_MOVE) return mix(end, OFFSTAGE, easeInOut((second - prev.draw_t1) / HAND_MOVE));
    // Do not show a hand hovering on an empty new page before it draws.
    if (second >= next.t0) return start;
    return null;
  }
  if (start && next) {
    return second < next.t0 ? null : start;
  }
  if (end && prev && second < prev.draw_t1 + HAND_MOVE) {
    return mix(end, OFFSTAGE, easeInOut((second - prev.draw_t1) / HAND_MOVE));
  }
  return null;
};

const Hand: React.FC<{ layers: WhiteboardLayer[]; second: number }> = ({ layers, second }) => {
  const { width, height } = useVideoConfig();
  const pen = penAt(layers, second);
  if (!pen) return null;
  const s = HAND.scale;
  // Cổ tay xoay nhẹ theo chỗ đang vẽ (vẽ bên trái thì cẳng tay nằm ngang hơn); nhấc bút thì tay nhích lên một chút.
  const angle = (0.5 - pen.x) * 9 + (pen.y - 0.45) * -5;
  const lift = 7 * pen.lift;
  const left = pen.x * width - HAND.tip[0] * s;
  const top = pen.y * height - HAND.tip[1] * s - lift;
  return (
    <Img src={staticFile(HAND.src)} style={{
      position: "absolute", left, top, width: HAND.size * s, height: HAND.size * s, zIndex: 1000,
      transform: `rotate(${angle}deg)`, transformOrigin: `${HAND.tip[0] * s}px ${HAND.tip[1] * s}px`,
    }} />
  );
};

const LayeredBoard: React.FC<{
  layers: WhiteboardLayer[];
  sceneStart: number;
  pageEnd?: number;
  motion?: NonNullable<Props["data"]["beats"]>[number]["motion"];
}> = ({ layers, sceneStart, pageEnd, motion }) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const second = sceneStart + frame / fps;
  const current = [...layers].reverse().find((layer) => second >= layer.t0);
  const box = current?.bbox;
  const localStart = current ? Math.max(0, Math.round((current.t0 - sceneStart) * fps)) : 0;
  const focus = interpolate(frame, [localStart, localStart + Math.max(8, Math.round(fps * 0.45))], [0, 1], {
    extrapolateLeft: "clamp", extrapolateRight: "clamp",
  });
  const isSmall = box && Math.max(box.w, box.h) < 0.58;
  const targetScale = isSmall ? 1.075 : 1.025;
  const cx = box ? box.x + box.w / 2 : 0.5;
  const cy = box ? box.y + box.h / 2 : 0.5;
  // Keep the camera gentle. The board remains readable and old layers retain
  // their relative positions while the new object gets a little more focus.
  let scale = 1 + (targetScale - 1) * focus;
  let x = clamp((0.5 - cx) * width * 0.28, -width * 0.10, width * 0.10) * focus;
  let y = clamp((0.5 - cy) * height * 0.20, -height * 0.08, height * 0.08) * focus;
  if (motion?.camera === "zoom_out") scale = 1.07 - (1.07 - scale) * focus;
  if (motion?.camera === "pan_right") x -= width * 0.025 * focus;
  if (motion?.camera === "pan_down") y -= height * 0.025 * focus;
  if (motion?.camera === "static") { scale = 1; x = 0; y = 0; }
  if (motion?.accent === "pulse") scale += Math.sin(focus * Math.PI) * 0.012;
  if (motion?.accent === "follow") x += Math.sin(focus * Math.PI) * width * 0.012;
  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      <AbsoluteFill style={{ transform: `translate(${x}px, ${y}px) scale(${scale})`, transformOrigin: "center center" }}>
        {layers.map((layer, index) => <BoardLayer key={index} layer={layer} sceneStart={sceneStart} zIndex={index} last={index === layers.length - 1} />)}
        {/* bàn tay nằm cùng hệ toạ độ với các lớp nên đầu bút luôn trùng nét đang vẽ, kể cả khi máy quay zoom;
            trang đã hết lượt (đang trượt ra) thì không còn tay */}
        {pageEnd === undefined || second < pageEnd ? <Hand layers={layers} second={second} /> : null}
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

const BoardLayer: React.FC<{ layer: WhiteboardLayer; sceneStart: number; zIndex: number; last?: boolean }> = ({ layer, sceneStart, zIndex, last }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const from = Math.max(0, Math.round((layer.t0 - sceneStart) * fps));
  const drawDuration = Math.max(1, Math.round((layer.draw_t1 - layer.t0) * fps));
  // Lớp cuối của trang giữ ảnh hoàn chỉnh tới hết Sequence của trang, kể cả lúc trang đang trượt ra.
  const total = last ? Infinity : Math.max(
    drawDuration,
    layer.hold_frame !== undefined
      ? layer.hold_frame - from
      : Math.round((layer.hold_t1 - layer.t0) * fps),
  );
  // `frame` belongs to the whole page.  Convert it to the layer's own
  // drawing interval; otherwise a later layer starts by showing a frame from
  // the middle/end of its drawing clip.
  const localFrame = Math.max(0, frame - from);
  const safeFrame = Math.max(0, Math.min(
    (layer.frame_count ?? 1) - 1,
    Math.floor(localFrame * (layer.frame_count ?? 1) / drawDuration),
  ));
  const video = layer.frames
    ? <Img src={staticFile(`${layer.frames}/frame-${String(safeFrame).padStart(5, "0")}.png`)} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
    : <OffthreadVideo src={staticFile(layer.clip)} style={{ width: "100%", height: "100%", objectFit: "cover" }} />;
  const still = layer.still ? <Img src={staticFile(layer.still)} style={{ width: "100%", height: "100%", objectFit: "cover" }} /> : video;
  return (
    <Sequence from={from} durationInFrames={total} layout="none">
      {/* Sequence timing does not define visual stacking. Give later planned
          objects a higher layer explicitly, otherwise a completed early
          object can cover every object drawn after it. */}
      <AbsoluteFill style={{ zIndex }}>
        <Sequence durationInFrames={drawDuration} layout="none">{video}</Sequence>
        {total > drawDuration ? (
          <Sequence from={drawDuration} durationInFrames={total - drawDuration} layout="none">
            {still}
          </Sequence>
        ) : null}
      </AbsoluteFill>
    </Sequence>
  );
};

const Header: React.FC<{ props: Props; t: number }> = ({ props, t }) => (
  <>
    <div style={{ position: "absolute", top: 0, left: 0, height: 8, width: 1080 * clamp(t / props.data.duration), background: "#e46f41" }} />
    <div style={{ position: "absolute", top: 64, left: 54, right: 54, display: "flex", justifyContent: "space-between", alignItems: "center",
      fontWeight: 700, fontSize: 24, letterSpacing: ".08em", color: "#382d23", textShadow: "0 1px 0 rgba(255,255,255,.8)" }}>
      <span>{props.data.meta.series || "GIẢI THÍCH NHANH"}</span>
      {props.data.meta.ep ? <span>TẬP {String(props.data.meta.ep).padStart(2, "0")}</span> : null}
    </div>
  </>
);

export const Academic: React.FC<Props> = (props) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame / fps;
  return (
    <AbsoluteFill style={{ fontFamily: FONT, overflow: "hidden" }}>
      <Paper />
      <WhiteboardClips data={props.data} />
      {props.data.whiteboard?.header ? <Header props={props} t={t} /> : null}
      {props.data.whiteboard?.captions ? <Captions data={props.data} t={t} /> : null}
      {props.audio ? <Audio src={staticFile(props.audio)} /> : null}
    </AbsoluteFill>
  );
};
