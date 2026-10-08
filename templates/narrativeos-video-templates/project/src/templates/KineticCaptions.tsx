import React from 'react';
import {AbsoluteFill, Easing, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import type {StyleProfile} from '../styles/StyleProfile';
import {registerTemplate} from '../registry/registry';

export interface CaptionWord {
	text: string;
	/** Seconds from the start of this caption segment (the compiler maps transcript times onto the timeline). */
	start: number;
	end: number;
	/** A firing moment (a number, a contrast, a list marker): drawn larger and in the highlight colour. */
	emphasis?: boolean;
}

export interface KineticCaptionsParams {
	words: CaptionWord[];
	/** Most words on screen at once. Short cells read faster on a phone. */
	maxWords?: number;
	/** A pause at least this long (s) starts a new cell. */
	breakOnPauseSec?: number;
	position?: 'lower' | 'center' | 'upper';
	/** Fractions of the frame kept clear for platform UI, injected by the compiler from canvas.platform. */
	safeArea?: {top: number; bottom: number; left: number; right: number};
	/** Colour of the spoken word and of emphasis. Defaults to the style's text colour (no invented palette). */
	highlightColor?: string;
	uppercase?: boolean;
	fontScale?: number;
}

type Cell = {words: CaptionWord[]; start: number; end: number};

/** Words into cells: a new cell at maxWords, after a pause, or after sentence-ending punctuation. */
export function captionCells(words: CaptionWord[], maxWords: number, breakOnPauseSec: number): Cell[] {
	const cells: Cell[] = [];
	let cur: CaptionWord[] = [];
	const flush = () => {
		if (cur.length) cells.push({words: cur, start: cur[0].start, end: cur[cur.length - 1].end});
		cur = [];
	};
	words.forEach((w, i) => {
		const prev = words[i - 1];
		if (cur.length && (cur.length >= maxWords || (prev && w.start - prev.end >= breakOnPauseSec) || /[.!?]$/.test(prev?.text ?? ''))) flush();
		cur.push(w);
	});
	flush();
	// Hold each cell until the next one starts when the gap is short, so captions do not flicker off between words.
	return cells.map((c, i) => ({...c, end: i + 1 < cells.length && cells[i + 1].start - c.end < 0.5 ? cells[i + 1].start : c.end + 0.25}));
}

const KineticCaptions: React.FC<{style: StyleProfile; params: KineticCaptionsParams}> = ({style, params}) => {
	const frame = useCurrentFrame();
	const {fps, width, height} = useVideoConfig();
	const t = frame / fps;
	const cells = captionCells(params.words ?? [], params.maxWords ?? 3, params.breakOnPauseSec ?? 0.35);
	const cell = cells.find((c) => t >= c.start && t < c.end);
	if (!cell) return null;
	const safe = params.safeArea ?? {top: 0.05, bottom: 0.08, left: 0.05, right: 0.05};
	const base = Math.min(width, height) * 0.088 * (params.fontScale ?? 1);
	const highlight = params.highlightColor ?? style.typography.boneColor;
	const zoneTop = safe.top * height;
	const zoneBottom = (1 - safe.bottom) * height;
	const y = {upper: zoneTop + (zoneBottom - zoneTop) * 0.18, center: (zoneTop + zoneBottom) / 2, lower: zoneTop + (zoneBottom - zoneTop) * 0.8}[params.position ?? 'lower'];
	const cellIn = interpolate(t - cell.start, [0, 0.12], [0.92, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.out(Easing.back(2))});
	return (
		<AbsoluteFill>
			<div
				style={{
					position: 'absolute',
					left: safe.left * width,
					right: safe.right * width,
					top: y,
					transform: `translateY(-50%) scale(${cellIn})`,
					display: 'flex',
					flexWrap: 'wrap',
					justifyContent: 'center',
					alignItems: 'baseline',
					columnGap: base * 0.28,
					rowGap: base * 0.05,
					textAlign: 'center',
				}}
			>
				{cell.words.map((w, i) => {
					const spoken = t >= w.start;
					const active = spoken && t < w.end + 0.06;
					const pop = interpolate(t - w.start, [0, 0.09, 0.2], [1, 1.12, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
					const size = base * (w.emphasis ? 1.32 : 1);
					return (
						<span
							key={`${w.start}-${i}`}
							style={{
								fontFamily: style.typography.sansFamily,
								fontWeight: 800,
								fontSize: size,
								lineHeight: 1.08,
								letterSpacing: -0.5,
								textTransform: params.uppercase === false ? 'none' : 'uppercase',
								color: active || w.emphasis ? highlight : style.typography.boneColor,
								opacity: spoken ? 1 : 0.38,
								transform: `scale(${active ? pop : 1})`,
								display: 'inline-block',
								textShadow: '0 3px 0 rgba(0,0,0,0.55), 0 0 18px rgba(0,0,0,0.55)',
								WebkitTextStroke: `${Math.max(1, base * 0.025)}px rgba(0,0,0,0.6)`,
								paintOrder: 'stroke fill',
							}}
						>
							{w.text}
						</span>
					);
				})}
			</div>
		</AbsoluteFill>
	);
};

registerTemplate<KineticCaptionsParams>({
	id: 'kinetic_captions',
	label: 'Kinetic captions (word by word)',
	pack: 'typography',
	aspects: ['16:9', '9:16', '1:1', '4:5'],
	durationInFrames: (params, fps) => Math.max(1, Math.ceil(((params.words ?? []).reduce((m, w) => Math.max(m, w.end), 0) + 0.5) * fps)),
	component: KineticCaptions,
	defaultParams: {
		words: [
			{text: 'This', start: 0.1, end: 0.35},
			{text: 'took', start: 0.35, end: 0.6},
			{text: 'three', start: 0.6, end: 0.95, emphasis: true},
			{text: 'years.', start: 0.95, end: 1.4},
		],
	},
});
