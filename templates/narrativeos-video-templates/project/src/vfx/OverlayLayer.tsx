import React from 'react';
import {AbsoluteFill, Loop, OffthreadVideo, Sequence} from 'remotion';
import type {VfxAsset, VfxBlend} from './catalog';

const CSS_BLEND: Record<VfxBlend, React.CSSProperties['mixBlendMode']> = {
	screen: 'screen',
	add: 'plus-lighter',
	overlay: 'overlay',
	multiply: 'multiply',
	normal: 'normal',
};

export interface OverlayLayerProps {
	/** Resolved URL (staticFile / vfxSrc). */
	src: string;
	blendMode?: VfxBlend;
	/** Opacity for the current frame; the caller owns the envelope. */
	opacity: number;
	/** Frame the clip starts playing at (may be negative: starts partway in). Omit to play from frame 0. */
	from?: number;
	durationInFrames?: number;
	playbackRate?: number;
	/** Loop the clip every N frames (grain/dust beds). */
	loopFrames?: number;
	/** Extra CSS filter, e.g. a style's hue-rotate/saturate tint. */
	filter?: string;
	/** Clip has an alpha channel (ProRes 4444, VP9 alpha): decode it as transparent. */
	transparent?: boolean;
}

/**
 * The one component for every footage overlay: light leaks, film burns,
 * dust, flares. It is the editors' technique (drop the clip over the cut,
 * Screen blend, lower the opacity, kill its sound) as a reusable layer.
 * Always muted: transition sound comes from the recipe's SFX cues.
 */
export const OverlayLayer: React.FC<OverlayLayerProps> = ({
	src,
	blendMode = 'screen',
	opacity,
	from,
	durationInFrames,
	playbackRate = 1,
	loopFrames,
	filter,
	transparent,
}) => {
	let video: React.ReactNode = (
		<OffthreadVideo
			src={src}
			style={{width: '100%', height: '100%', objectFit: 'cover'}}
			muted
			transparent={transparent || undefined}
			playbackRate={playbackRate === 1 ? undefined : playbackRate}
		/>
	);
	if (loopFrames) video = <Loop durationInFrames={loopFrames}>{video}</Loop>;
	if (from !== undefined) {
		video = (
			<Sequence from={from} durationInFrames={durationInFrames} layout="none">
				{video}
			</Sequence>
		);
	}
	return (
		<AbsoluteFill style={{mixBlendMode: CSS_BLEND[blendMode], opacity, pointerEvents: 'none', ...(filter ? {filter} : {})}}>
			{video}
		</AbsoluteFill>
	);
};

/**
 * Where to start a clip so its brightest frame (measured at ingest) lands
 * exactly on `cutFrame`. Remotion plays a clip at media time
 * (frame - from) * playbackRate / fps, so from = cut - peak * fps / rate.
 */
export function peakAlignedPlacement(asset: VfxAsset, cutFrame: number, fps: number, playbackRate = 1) {
	const from = Math.round(cutFrame - (asset.analysis.peak_time_sec * fps) / playbackRate);
	const clipFrames = asset.technical.duration_sec ? Math.floor((asset.technical.duration_sec * fps) / playbackRate) - 1 : undefined;
	return {from, durationInFrames: clipFrames && clipFrames > 0 ? clipFrames : undefined};
}
