import React from 'react';
import {AbsoluteFill, Easing, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import type {StyleProfile} from '../styles/StyleProfile';
import {registerTemplate} from '../registry/registry';

/** A face a lockup word can be drawn in. 'symbols' replaces the letters with glyph noise (a decode/scramble look). */
export type LockupFont = 'sans' | 'serif-italic' | 'script' | 'outline' | 'pixel' | 'symbols';

export interface LockupWord {
	text: string;
	/** Seconds from the start of the lockup, when the word is spoken: it appears then and stays. */
	start: number;
	/** Size relative to the base (function words ~0.45, content words 1, key words 1.4+). */
	size?: number;
	/** The face it settles in. Default 'sans'. */
	font?: LockupFont;
	/** Key word: it cycles through cycleFonts when it appears, and again every recycleSec while on screen. */
	cycle?: boolean;
}

export interface LockupBlock {
	words: LockupWord[];
	anchor: 'top-left' | 'top-right' | 'bottom-left' | 'bottom-right' | 'center';
	/** Text colour. Pick it from what is measured behind the block (dark text on a bright sky, white on dark ground). */
	color: string;
	/** Widest the block may grow, as a fraction of the frame width. */
	maxWidth?: number;
}

export interface TypographicLockupParams {
	blocks: LockupBlock[];
	/** Base word size as a fraction of the frame's shorter side. */
	base?: number;
	/** Faces a key word passes through while cycling, in order. */
	cycleFonts?: LockupFont[];
	/** How long one cycle lasts (s), and how long a key word rests between cycles. */
	cycleSec?: number;
	recycleSec?: number;
	/** Frames each face is held while cycling. */
	framesPerFace?: number;
	/** Fractions of the frame kept clear (platform UI). */
	safeArea?: {top: number; bottom: number; left: number; right: number};
}

const FAMILY: Record<Exclude<LockupFont, 'symbols'>, {family: string; weight: number; style?: string; scale: number}> = {
	sans: {family: "InterLocal, 'Helvetica Neue', Arial, sans-serif", weight: 900, scale: 1},
	'serif-italic': {family: "PlayfairItalicLocal, Georgia, serif", weight: 700, style: 'italic', scale: 1.05},
	script: {family: "PinyonLocal, 'Brush Script MT', cursive", weight: 400, scale: 1.25},
	outline: {family: "BungeeOutlineLocal, Impact, sans-serif", weight: 400, scale: 0.92},
	pixel: {family: "SilkscreenLocal, 'Courier New', monospace", weight: 400, scale: 0.9},
};
const GLYPHS = '≒↗☆♪✦∿⌘◊※¤§∞≈⊕⟡✕↯';

/** Deterministic glyph noise the same length as the word (no randomness: renders are reproducible). */
export function scramble(text: string, seed: number): string {
	return Array.from(text)
		.map((_, i) => GLYPHS[(seed * 7 + i * 13 + text.length) % GLYPHS.length])
		.join('');
}

/** The face a key word shows at time t (seconds since it appeared), or its settled face. */
export function faceAt(word: LockupWord, t: number, fps: number, cycleFonts: LockupFont[], cycleSec: number, recycleSec: number, framesPerFace: number): LockupFont {
	const settled = word.font ?? 'sans';
	if (!word.cycle || t < 0) return settled;
	const period = cycleSec + recycleSec;
	const phase = recycleSec > 0 ? t % period : t;
	if (phase >= cycleSec) return settled;
	const step = Math.floor((phase * fps) / framesPerFace);
	return cycleFonts[step % cycleFonts.length] ?? settled;
}

const ANCHOR: Record<LockupBlock['anchor'], React.CSSProperties> = {
	'top-left': {top: 0, left: 0, justifyContent: 'flex-start'},
	'top-right': {top: 0, right: 0, justifyContent: 'flex-end'},
	'bottom-left': {bottom: 0, left: 0, justifyContent: 'flex-start'},
	'bottom-right': {bottom: 0, right: 0, justifyContent: 'flex-end'},
	center: {top: '50%', left: '50%', justifyContent: 'center'},
};

const TypographicLockup: React.FC<{style: StyleProfile; params: TypographicLockupParams}> = ({params}) => {
	const frame = useCurrentFrame();
	const {fps, width, height} = useVideoConfig();
	const t = frame / fps;
	const base = Math.min(width, height) * (params.base ?? 0.075);
	const safe = params.safeArea ?? {top: 0.06, bottom: 0.08, left: 0.05, right: 0.05};
	const cycleFonts = params.cycleFonts ?? ['symbols', 'script', 'serif-italic', 'outline', 'pixel', 'symbols', 'serif-italic'];
	const cycleSec = params.cycleSec ?? 0.7;
	const recycleSec = params.recycleSec ?? 1.6;
	const fpf = params.framesPerFace ?? 3;
	return (
		<AbsoluteFill>
			<div style={{position: 'absolute', left: safe.left * width, right: safe.right * width, top: safe.top * height, bottom: safe.bottom * height}}>
				{params.blocks.map((block, bi) => (
					<div
						key={bi}
						style={{
							position: 'absolute',
							...ANCHOR[block.anchor],
							transform: block.anchor === 'center' ? 'translate(-50%, -50%)' : undefined,
							maxWidth: (block.maxWidth ?? 0.62) * width,
							display: 'flex',
							flexWrap: 'wrap',
							alignItems: 'flex-end',
							columnGap: base * 0.12,
							rowGap: 0,
							color: block.color,
						}}
					>
						{block.words.map((w, wi) => {
							const since = t - w.start;
							if (since < 0) return null;
							const face = faceAt(w, since, fps, cycleFonts, cycleSec, recycleSec, fpf);
							const settled = w.font ?? 'sans';
							const look = (fc: LockupFont): React.CSSProperties => {
								const f = FAMILY[fc === 'symbols' ? 'sans' : fc];
								const size = base * (w.size ?? 1) * f.scale;
								return {fontFamily: f.family, fontWeight: f.weight, fontStyle: f.style ?? 'normal', fontSize: size, lineHeight: 0.86,
									letterSpacing: fc === 'sans' ? -size * 0.045 : 0, textTransform: 'lowercase', whiteSpace: 'nowrap'};
							};
							const pop = interpolate(since, [0, 0.1], [0.82, 1], {extrapolateRight: 'clamp', easing: Easing.out(Easing.cubic)});
							const shown = face === 'symbols' ? scramble(w.text, Math.floor((since * fps) / fpf)) : w.text;
							// The word takes the space of its settled face; a cycling face is drawn over that space, so the
							// collage never reflows while a key word changes faces.
							return (
								<span key={wi} style={{position: 'relative', display: 'inline-block', transform: `scale(${pop})`, transformOrigin: 'bottom left'}}>
									<span style={{...look(settled), visibility: face === settled ? 'visible' : 'hidden', display: 'inline-block'}}>{w.text}</span>
									{face !== settled ? (
										<span style={{...look(face), position: 'absolute', left: '50%', bottom: 0, transform: 'translateX(-50%)'}}>{shown}</span>
									) : null}
								</span>
							);
						})}
					</div>
				))}
			</div>
		</AbsoluteFill>
	);
};

registerTemplate<TypographicLockupParams>({
	id: 'typographic_lockup',
	label: 'Typographic lockup (words build into a collage; key words cycle faces)',
	pack: 'typography',
	aspects: ['16:9', '9:16', '1:1', '4:5'],
	durationInFrames: (params, fps) =>
		Math.max(1, Math.ceil((Math.max(0, ...params.blocks.flatMap((b) => b.words.map((w) => w.start))) + 2) * fps)),
	component: TypographicLockup,
	defaultParams: {
		blocks: [
			{anchor: 'top-left', color: '#111', words: [
				{text: 'the', start: 0.0, size: 0.5}, {text: 'habits', start: 0.3, size: 1.2, cycle: true}, {text: 'you', start: 0.7, size: 0.5},
				{text: 'keep', start: 0.9, size: 1},
			]},
			{anchor: 'bottom-right', color: '#fff', words: [
				{text: 'decide', start: 1.4, size: 0.9}, {text: 'the', start: 1.8, size: 0.45}, {text: 'life', start: 2.0, size: 1.3, cycle: true},
				{text: 'you', start: 2.4, size: 0.5}, {text: 'live', start: 2.6, size: 1},
			]},
		],
	},
});
