import { loadFont } from "@remotion/fonts";
import React from "react";
import { AbsoluteFill, Audio, Img, OffthreadVideo, Sequence, interpolate, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { C, FONT, Props, WhiteboardLayer, clamp } from "./lib";
import { Captions } from "./Scenes";

loadFont({ family: "BVP", url: staticFile("fonts/BeVietnamPro-Medium.ttf"), weight: "500" });
loadFont({ family: "BVP", url: staticFile("fonts/BeVietnamPro-Bold.ttf"), weight: "700" });

const Paper: React.FC = () => (
  // Match the paper colour emitted by Whiteboard Lab. A textured background
  // makes the opaque drawing clip look like a visible rectangle while a hand
  // is moving across it.
  <AbsoluteFill style={{ background: "#fbfdfa" }} />
);

const WhiteboardClips: React.FC<{ data: Props["data"] }> = ({ data }) => {
  const { fps } = useVideoConfig();
  const pages = data.whiteboard_pages ?? (data.beats || []).map((beat) => ({
    t0: beat.t0, t1: beat.t1, layers: beat.layers || [], motion: beat.motion,
  }));
  return (
    <>
      {pages.map((page, index) => {
        if (page.layers?.length) {
          const from = Math.max(0, Math.round(page.t0 * fps));
          const duration = Math.max(1, Math.round((page.t1 - page.t0) * fps));
          return (
            <Sequence key={index} from={from} durationInFrames={duration} layout="none">
              <LayeredBoard layers={page.layers} sceneStart={page.t0} motion={page.motion} />
            </Sequence>
          );
        }
        return null;
      })}
    </>
  );
};

const LayeredBoard: React.FC<{
  layers: WhiteboardLayer[];
  sceneStart: number;
  motion?: NonNullable<Props["data"]["beats"]>[number]["motion"];
}> = ({ layers, sceneStart, motion }) => {
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
        {layers.map((layer, index) => <BoardLayer key={index} layer={layer} sceneStart={sceneStart} zIndex={index} />)}
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

const BoardLayer: React.FC<{ layer: WhiteboardLayer; sceneStart: number; zIndex: number }> = ({ layer, sceneStart, zIndex }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const from = Math.max(0, Math.round((layer.t0 - sceneStart) * fps));
  const drawDuration = Math.max(1, Math.round((layer.draw_t1 - layer.t0) * fps));
  const total = Math.max(drawDuration, Math.round((layer.hold_t1 - layer.t0) * fps));
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
