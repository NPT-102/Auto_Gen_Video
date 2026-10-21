import { loadFont } from "@remotion/fonts";
import React from "react";
import { AbsoluteFill, Audio, Freeze, OffthreadVideo, Sequence, interpolate, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { C, FONT, Props, WhiteboardLayer, clamp } from "./lib";
import { Captions } from "./Scenes";

loadFont({ family: "BVP", url: staticFile("fonts/BeVietnamPro-Medium.ttf"), weight: "500" });
loadFont({ family: "BVP", url: staticFile("fonts/BeVietnamPro-Bold.ttf"), weight: "700" });

const Paper: React.FC = () => (
  <AbsoluteFill style={{ background: "#f8f6ef" }}>
    <AbsoluteFill style={{ opacity: 0.28, backgroundImage: "radial-gradient(rgba(68,59,45,.18) .75px, transparent .75px)", backgroundSize: "7px 7px" }} />
  </AbsoluteFill>
);

const WhiteboardClips: React.FC<{ beats: NonNullable<Props["data"]["beats"]> }> = ({ beats }) => {
  const { fps } = useVideoConfig();
  return (
    <>
      {beats.map((beat, index) => {
        if (beat.layers?.length) {
          const from = Math.max(0, Math.round(beat.t0 * fps));
          const duration = Math.max(1, Math.round((beat.t1 - beat.t0) * fps));
          return (
            <Sequence key={index} from={from} durationInFrames={duration} layout="none">
              <LayeredBoard layers={beat.layers} sceneStart={beat.t0} motion={beat.motion} />
            </Sequence>
          );
        }
        if (!beat.clip) return null;
        const from = Math.max(0, Math.round(beat.t0 * fps));
        const drawDuration = Math.max(1, Math.round(((beat.draw_t1 ?? beat.t1) - beat.t0) * fps));
        const holdUntil = beat.hold_t1 ?? beat.t1;
        const totalDuration = Math.max(drawDuration, Math.round((holdUntil - beat.t0) * fps));
        return (
          <Sequence key={index} from={from} durationInFrames={totalDuration} layout="none">
            <Sequence durationInFrames={drawDuration} layout="none">
              <Clip src={beat.clip} duration={drawDuration} motion={beat.motion} />
            </Sequence>
            {totalDuration > drawDuration ? (
              <Sequence from={drawDuration} durationInFrames={totalDuration - drawDuration} layout="none">
                <Freeze frame={drawDuration - 1}>
                  <Clip src={beat.clip} duration={drawDuration} motion={beat.motion} />
                </Freeze>
              </Sequence>
            ) : null}
          </Sequence>
        );
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
  if (motion?.accent === "pulse") scale += Math.sin(focus * Math.PI) * 0.012;
  if (motion?.accent === "follow") x += Math.sin(focus * Math.PI) * width * 0.012;
  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      <AbsoluteFill style={{ transform: `translate(${x}px, ${y}px) scale(${scale})`, transformOrigin: "center center" }}>
        {layers.map((layer, index) => <BoardLayer key={index} layer={layer} sceneStart={sceneStart} />)}
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

const BoardLayer: React.FC<{ layer: WhiteboardLayer; sceneStart: number }> = ({ layer, sceneStart }) => {
  const { fps } = useVideoConfig();
  const from = Math.max(0, Math.round((layer.t0 - sceneStart) * fps));
  const drawDuration = Math.max(1, Math.round((layer.draw_t1 - layer.t0) * fps));
  const total = Math.max(drawDuration, Math.round((layer.hold_t1 - layer.t0) * fps));
  const video = <OffthreadVideo src={staticFile(layer.clip)} style={{ width: "100%", height: "100%", objectFit: "cover", mixBlendMode: layer.blend === "multiply" ? "multiply" : "normal" }} />;
  return (
    <Sequence from={from} durationInFrames={total} layout="none">
      <Sequence durationInFrames={drawDuration} layout="none">{video}</Sequence>
      {total > drawDuration ? (
        <Sequence from={drawDuration} durationInFrames={total - drawDuration} layout="none">
          <Freeze frame={drawDuration - 1}>{video}</Freeze>
        </Sequence>
      ) : null}
    </Sequence>
  );
};

const Clip: React.FC<{ src: string; duration: number; motion?: NonNullable<Props["data"]["beats"]>[number]["motion"] }> = ({ src, duration, motion }) => {
  const frame = useCurrentFrame();
  const enterFrames = Math.min(12, Math.max(4, Math.round(duration * 0.08)));
  const enter = interpolate(frame, [0, enterFrames], [0, 1], { extrapolateRight: "clamp" });
  const cameraStart = Math.min(duration - 1, Math.max(1, Math.round(duration * 0.58)));
  const camera = interpolate(frame, [cameraStart, Math.max(cameraStart + 1, duration - 1)], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const cameraKind = motion?.camera ?? "zoom_in";
  const transition = motion?.transition ?? "clear";
  let scale = 1;
  let x = 0;
  let y = 0;
  if (cameraKind === "zoom_in") scale = 1 + camera * 0.075;
  if (cameraKind === "zoom_out") scale = 1.075 - camera * 0.075;
  if (cameraKind === "pan_right") { scale = 1.055; x = -34 * camera; }
  if (cameraKind === "pan_down") { scale = 1.055; y = -42 * camera; }
  if (motion?.accent === "pulse" && camera > 0) scale += Math.sin(camera * Math.PI) * 0.018;
  if (motion?.accent === "follow" && camera > 0) x += Math.sin(camera * Math.PI) * 18;
  const enterX = transition === "slide_left" ? (1 - enter) * 96 : transition === "slide_right" ? -(1 - enter) * 96 : 0;
  return (
    <AbsoluteFill style={{ opacity: enter, overflow: "hidden" }}>
      <OffthreadVideo src={staticFile(src)} style={{ width: "100%", height: "100%", objectFit: "cover", transform: `translate(${x + enterX}px, ${y}px) scale(${scale})`, transformOrigin: "center center" }} />
    </AbsoluteFill>
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
      <WhiteboardClips beats={props.data.beats || []} />
      <Header props={props} t={t} />
      <Captions data={props.data} t={t} />
      {props.audio ? <Audio src={staticFile(props.audio)} /> : null}
    </AbsoluteFill>
  );
};
