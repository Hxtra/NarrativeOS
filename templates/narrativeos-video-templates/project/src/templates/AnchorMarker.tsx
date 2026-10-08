import React from 'react';
import {AbsoluteFill, Easing, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import type {StyleProfile} from '../styles/StyleProfile';
import {registerTemplate} from '../registry/registry';

export interface AnchorPoint {
	/** Seconds from the start of this graphic (the compiler maps measured fingertip positions onto it). */
	t: number;
	/** Position in the output frame, 0..1. */
	x: number;
	y: number;
}

export interface AnchorMarkerParams {
	anchors: AnchorPoint[];
	/** Optional words shown above the marker. No label is invented: without one only the marker shows. */
	label?: string;
	color?: string;
}

/** Position along the measured track at time t: linear between samples, held at the ends. */
export function anchorAt(anchors: AnchorPoint[], t: number): {x: number; y: number} | null {
	if (!anchors.length) return null;
	if (t <= anchors[0].t) return anchors[0];
	for (let i = 1; i < anchors.length; i++) {
		const a = anchors[i - 1];
		const b = anchors[i];
		if (t <= b.t) {
			const k = b.t > a.t ? (t - a.t) / (b.t - a.t) : 1;
			return {x: a.x + (b.x - a.x) * k, y: a.y + (b.y - a.y) * k};
		}
	}
	return anchors[anchors.length - 1];
}

const AnchorMarker: React.FC<{style: StyleProfile; params: AnchorMarkerParams}> = ({style, params}) => {
	const frame = useCurrentFrame();
	const {fps, width, height, durationInFrames} = useVideoConfig();
	const t = frame / fps;
	const p = anchorAt(params.anchors ?? [], t);
	if (!p) return null;
	const size = Math.min(width, height) * 0.075;
	const color = params.color ?? style.typography.boneColor;
	const enter = interpolate(frame, [0, 8], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.out(Easing.back(1.8))});
	const exit = interpolate(frame, [durationInFrames - 8, durationInFrames], [1, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
	const pulse = 1 + 0.08 * Math.sin((frame / fps) * Math.PI * 2 * 1.4);
	return (
		<AbsoluteFill style={{opacity: exit}}>
			<div style={{position: 'absolute', left: p.x * width, top: p.y * height, transform: `translate(-50%, -50%) scale(${enter * pulse})`}}>
				<div style={{width: size, height: size, borderRadius: '50%', border: `${size * 0.09}px solid ${color}`,
					boxShadow: `0 0 ${size * 0.4}px rgba(0,0,0,0.45), inset 0 0 ${size * 0.3}px rgba(0,0,0,0.25)`}} />
				<div style={{position: 'absolute', left: '50%', top: '50%', width: size * 0.2, height: size * 0.2, borderRadius: '50%',
					background: color, transform: 'translate(-50%, -50%)'}} />
				{params.label ? (
					<div style={{position: 'absolute', left: '50%', bottom: size * 1.2, transform: 'translateX(-50%)', whiteSpace: 'nowrap',
						fontFamily: style.typography.sansFamily, fontWeight: 800, fontSize: size * 0.55, color,
						textShadow: '0 3px 0 rgba(0,0,0,0.55), 0 0 16px rgba(0,0,0,0.5)'}}>
						{params.label}
					</div>
				) : null}
			</div>
		</AbsoluteFill>
	);
};

registerTemplate<AnchorMarkerParams>({
	id: 'anchor_marker',
	label: 'Anchor marker (follows a tracked point)',
	pack: 'typography',
	aspects: ['16:9', '9:16', '1:1', '4:5'],
	durationInFrames: (params, fps) => Math.max(1, Math.ceil(((params.anchors ?? []).reduce((m, a) => Math.max(m, a.t), 0) + 0.5) * fps)),
	component: AnchorMarker,
	defaultParams: {anchors: [{t: 0, x: 0.5, y: 0.5}, {t: 1, x: 0.6, y: 0.45}], label: 'this one'},
});
