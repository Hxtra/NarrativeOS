import React from 'react';
import {AbsoluteFill, Audio, Freeze, Sequence, random, useCurrentFrame, useVideoConfig} from 'remotion';
import type {StyleProfile} from '../styles/StyleProfile';
import {resolveOverlay, useVfxCatalog, vfxSrc, type VfxBlend, type VfxSelector} from './catalog';
import {OverlayLayer, peakAlignedPlacement} from './OverlayLayer';
import {progress, pulse} from './envelope';

// ---------------------------------------------------------------------------
// Spec: plain data, so a recipe (or a future Director/CLI) can describe a
// transition as JSON. `attack` = frames before the cut the layer ramps up,
// `release` = frames after the cut it takes to fade out.
// ---------------------------------------------------------------------------

export type Side = 'out' | 'in' | 'both';
type Env = {attack: number; release: number};

export type VfxLayer =
	/** A real footage overlay from the VFX library, peak-aligned to the cut. */
	| ({kind: 'overlay'; select: VfxSelector; opacity: number; blend?: VfxBlend; rate?: number; fallback?: VfxLayer} & Env)
	| ({kind: 'flash'; color: string; opacity: number; blend?: VfxBlend; hold?: number} & Env)
	| ({kind: 'dip'; color: string; hold?: number} & Env)
	| ({kind: 'film_burn'; tone: 'warm' | 'cool'; opacity: number} & Env)
	| ({kind: 'zoom_punch'; scale: number; side?: Side} & Env)
	| ({kind: 'whip_pan'; direction: 'left' | 'right' | 'up' | 'down'; blurPx: number} & Env)
	| ({kind: 'directional_blur'; px: number; axis: 'x' | 'y'; side?: Side} & Env)
	| ({kind: 'blur'; px: number; side?: Side} & Env)
	| ({kind: 'rgb_split'; px: number; side?: Side} & Env)
	| ({kind: 'glitch_slices'; bands: number; maxOffsetPx: number; side?: Side} & Env)
	| ({kind: 'shake'; px: number; side?: Side} & Env)
	| ({kind: 'flicker'; amount: number; side?: Side} & Env)
	| ({kind: 'stutter'; holdFrames: number; side?: Side} & Env)
	| ({kind: 'desaturate'; amount: number; side?: Side} & Env);

export type CutSpec =
	| {type: 'hard'}
	| {type: 'crossfade'; frames: number}
	| {type: 'soft_wipe'; frames: number; direction: 'left' | 'right' | 'up' | 'down'}
	| {type: 'halftone'; frames: number; cellPx: number};

export type SfxCueName = 'whoosh' | 'impact' | 'shutter' | 'glitch_tick' | 'riser' | 'reverse_swell' | 'low_hit';
export interface SfxCue {
	cue: SfxCueName;
	/** Frames relative to the cut. */
	at?: number;
	volume?: number;
}

export interface TransitionSpec {
	cut: CutSpec;
	layers: VfxLayer[];
	/** Semantic sound cues. Played only when `sfxSources` maps the cue to a file. */
	sfx?: SfxCue[];
}

export interface TransitionStackProps {
	spec: TransitionSpec;
	/** Frame (in the current sequence) where A becomes B. */
	cutFrame: number;
	outgoing: React.ReactNode;
	incoming: React.ReactNode;
	style: StyleProfile;
	/** Seeds overlay selection and glitch randomness; the recipe id is a good default. */
	seed: string;
	sfxSources?: Partial<Record<SfxCueName, string>>;
}

const MEDIA_KINDS = new Set(['zoom_punch', 'whip_pan', 'directional_blur', 'blur', 'rgb_split', 'glitch_slices', 'shake', 'flicker', 'stutter', 'desaturate']);

const applies = (layer: VfxLayer, side: 'out' | 'in') => {
	const s = 'side' in layer && layer.side ? layer.side : 'both';
	return s === 'both' || s === side;
};

// ---------------------------------------------------------------------------
// Wrappers that need to draw the media more than once.
// ---------------------------------------------------------------------------

const CHANNEL_MATRIX = {
	r: '1 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 1 0',
	g: '0 0 0 0 0  0 1 0 0 0  0 0 0 0 0  0 0 0 1 0',
	b: '0 0 0 0 0  0 0 0 0 0  0 0 1 0 0  0 0 0 1 0',
};

/** Three channel-isolated copies, offset and Screen-blended back together (sums to the original when px = 0). */
const RgbSplit: React.FC<{px: number; id: string; children: React.ReactNode}> = ({px, id, children}) => {
	if (px < 0.5) return <>{children}</>;
	const offsets = {r: -px, g: 0, b: px};
	return (
		<AbsoluteFill style={{backgroundColor: '#000'}}>
			<svg width={0} height={0} style={{position: 'absolute'}}>
				<defs>
					{(['r', 'g', 'b'] as const).map((c) => (
						<filter key={c} id={`${id}-${c}`} colorInterpolationFilters="sRGB">
							<feColorMatrix type="matrix" values={CHANNEL_MATRIX[c]} />
						</filter>
					))}
				</defs>
			</svg>
			{(['r', 'g', 'b'] as const).map((c, i) => (
				<AbsoluteFill
					key={c}
					style={{transform: `translateX(${offsets[c].toFixed(2)}px)`, filter: `url(#${id}-${c})`, mixBlendMode: i === 0 ? 'normal' : 'screen'}}
				>
					{children}
				</AbsoluteFill>
			))}
		</AbsoluteFill>
	);
};

/** Horizontal bands of the frame, some shoved sideways: a digital tear. */
const GlitchSlices: React.FC<{bands: number; maxOffsetPx: number; strength: number; seed: string; frame: number; children: React.ReactNode}> = ({
	bands,
	maxOffsetPx,
	strength,
	seed,
	frame,
	children,
}) => {
	if (strength < 0.02) return <>{children}</>;
	const slot = Math.floor(frame / 2); // re-randomise every 2 frames, like a real glitch hold
	const edges = [0];
	for (let i = 1; i < bands; i++) edges.push(Math.min(99, edges[i - 1] + 4 + random(`${seed}-edge-${slot}-${i}`) * (200 / bands)));
	edges.push(100);
	return (
		<AbsoluteFill style={{backgroundColor: '#000'}}>
			{edges.slice(0, -1).map((top, i) => {
				const bottom = edges[i + 1];
				const shifted = random(`${seed}-on-${slot}-${i}`) > 0.45;
				const dx = shifted ? (random(`${seed}-dx-${slot}-${i}`) - 0.5) * 2 * maxOffsetPx * strength : 0;
				return (
					<AbsoluteFill key={i} style={{clipPath: `inset(${top.toFixed(2)}% 0 ${(100 - bottom).toFixed(2)}% 0)`, transform: `translateX(${dx.toFixed(1)}px)`}}>
						{children}
					</AbsoluteFill>
				);
			})}
		</AbsoluteFill>
	);
};

// ---------------------------------------------------------------------------
// One side (A or B) with its media-modifying layers applied.
// ---------------------------------------------------------------------------

const SideLayer: React.FC<{
	side: 'out' | 'in';
	rel: number;
	frame: number;
	cutFrame: number;
	layers: VfxLayer[];
	seed: string;
	width: number;
	height: number;
	opacity?: number;
	mask?: string;
	maskSize?: string;
	extraFilter?: string;
	children: React.ReactNode;
}> = ({side, rel, frame, cutFrame, layers, seed, width, height, opacity = 1, mask, maskSize, extraFilter, children}) => {
	const transforms: string[] = [];
	const filters: string[] = [];
	const svgFilters: React.ReactNode[] = [];
	let node: React.ReactNode = children;
	const id = `${seed}-${side}`.replace(/[^a-zA-Z0-9-]/g, '-');

	layers.forEach((layer, i) => {
		if (!MEDIA_KINDS.has(layer.kind) || !applies(layer, side)) return;
		if (layer.kind === 'whip_pan') {
			// A and B travel together as one strip (no black gap), blur peaking at mid-move.
			const s = progress(rel, -layer.attack, layer.release);
			if (s <= 0 || s >= 1) return;
			const horizontal = layer.direction === 'left' || layer.direction === 'right';
			const dir = layer.direction === 'left' || layer.direction === 'up' ? -1 : 1;
			const size = horizontal ? width : height;
			const offset = (side === 'out' ? dir * s : dir * (s - 1)) * size;
			transforms.push(horizontal ? `translateX(${offset.toFixed(1)}px)` : `translateY(${offset.toFixed(1)}px)`);
			const fid = `${id}-whip-${i}`;
			const sd = layer.blurPx * 4 * s * (1 - s);
			svgFilters.push(
				<filter key={fid} id={fid} x="-20%" y="-20%" width="140%" height="140%" colorInterpolationFilters="sRGB">
					<feGaussianBlur stdDeviation={horizontal ? `${sd.toFixed(2)} 0` : `0 ${sd.toFixed(2)}`} edgeMode="duplicate" />
				</filter>,
			);
			filters.push(`url(#${fid})`);
			return;
		}
		const a = pulse(rel, layer.attack, layer.release);
		if (a <= 0) return;
		switch (layer.kind) {
			case 'zoom_punch':
				transforms.push(`scale(${(1 + (layer.scale - 1) * a).toFixed(4)})`);
				break;
			case 'directional_blur': {
				const fid = `${id}-dblur-${i}`;
				const sd = layer.px * a;
				svgFilters.push(
					<filter key={fid} id={fid} x="-20%" y="-20%" width="140%" height="140%" colorInterpolationFilters="sRGB">
						<feGaussianBlur stdDeviation={layer.axis === 'x' ? `${sd.toFixed(2)} 0` : `0 ${sd.toFixed(2)}`} edgeMode="duplicate" />
					</filter>,
				);
				filters.push(`url(#${fid})`);
				break;
			}
			case 'blur':
				filters.push(`blur(${(layer.px * a).toFixed(2)}px)`);
				break;
			case 'shake': {
				const dx = (random(`${seed}-shx-${frame}`) - 0.5) * 2 * layer.px * a;
				const dy = (random(`${seed}-shy-${frame}`) - 0.5) * 2 * layer.px * a;
				transforms.push(`translate(${dx.toFixed(1)}px, ${dy.toFixed(1)}px)`);
				break;
			}
			case 'flicker':
				filters.push(`brightness(${(1 + (random(`${seed}-fl-${frame}`) - 0.5) * 0.5 * layer.amount * a).toFixed(4)})`);
				break;
			case 'desaturate':
				filters.push(`grayscale(${(layer.amount * a).toFixed(3)})`);
				break;
			case 'rgb_split':
				node = (
					<RgbSplit px={layer.px * a} id={`${id}-rgb-${i}`}>
						{node}
					</RgbSplit>
				);
				break;
			case 'glitch_slices':
				node = (
					<GlitchSlices bands={layer.bands} maxOffsetPx={layer.maxOffsetPx} strength={a} seed={`${seed}-${i}`} frame={frame}>
						{node}
					</GlitchSlices>
				);
				break;
			case 'stutter': {
				// Hold every Nth frame: the frame-hold "stutter" editors use in glitch montages.
				const held = frame - (((frame - cutFrame) % layer.holdFrames) + layer.holdFrames) % layer.holdFrames;
				node = <Freeze frame={held}>{node}</Freeze>;
				break;
			}
			default:
				break;
		}
	});

	if (extraFilter) filters.push(extraFilter);
	return (
		<AbsoluteFill
			style={{
				opacity,
				transform: transforms.join(' ') || undefined,
				filter: filters.join(' ') || undefined,
				...(mask ? {WebkitMaskImage: mask, maskImage: mask, WebkitMaskSize: maskSize, maskSize} : {}),
			}}
		>
			{svgFilters.length ? (
				<svg width={0} height={0} style={{position: 'absolute'}}>
					<defs>{svgFilters}</defs>
				</svg>
			) : null}
			{node}
		</AbsoluteFill>
	);
};

// ---------------------------------------------------------------------------
// Overlay layers composited on top of both sides.
// ---------------------------------------------------------------------------

const FilmBurn: React.FC<{rel: number; tone: 'warm' | 'cool'; strength: number}> = ({rel, tone, strength}) => {
	if (strength <= 0) return null;
	const c = tone === 'warm' ? ['255,244,214', '255,158,52', '196,52,12'] : ['228,244,255', '96,170,255', '24,52,160'];
	const blob = (x: number, y: number, size: number, k: number) =>
		`radial-gradient(ellipse ${size}% ${size * 0.8}% at ${x.toFixed(1)}% ${y.toFixed(1)}%, rgba(${c[0]},${(0.95 * k).toFixed(3)}) 0%, rgba(${c[1]},${(0.8 * k).toFixed(3)}) 30%, rgba(${c[2]},${(0.45 * k).toFixed(3)}) 60%, rgba(0,0,0,0) 100%)`;
	const drift = rel * 1.1;
	const layers = [blob(18 + drift, 38, 70, strength), blob(82 - drift * 0.6, 72, 55, strength * 0.8), blob(50 + drift * 0.3, 10, 45, strength * 0.6)];
	const hot = Math.max(0, (strength - 0.75) / 0.25);
	return (
		<>
			<AbsoluteFill style={{background: layers.join(','), mixBlendMode: 'screen', pointerEvents: 'none'}} />
			{hot > 0 ? <AbsoluteFill style={{backgroundColor: `rgba(${c[0]},${(hot * 0.9).toFixed(3)})`, mixBlendMode: 'screen'}} /> : null}
		</>
	);
};

const styleTint = (style: StyleProfile) => {
	const {hueRotate, saturate} = style.vfx.tint;
	return hueRotate === 0 && saturate === 1 ? undefined : `hue-rotate(${hueRotate}deg) saturate(${saturate})`;
};

const OverlayStackLayer: React.FC<{layer: VfxLayer; rel: number; cutFrame: number; fps: number; style: StyleProfile; seed: string; catalog: ReturnType<typeof useVfxCatalog>}> = ({
	layer,
	rel,
	cutFrame,
	fps,
	style,
	seed,
	catalog,
}) => {
	switch (layer.kind) {
		case 'overlay': {
			const asset = resolveOverlay(catalog, layer.select, seed);
			if (!asset) {
				return layer.fallback ? <OverlayStackLayer layer={layer.fallback} rel={rel} cutFrame={cutFrame} fps={fps} style={style} seed={seed} catalog={catalog} /> : null;
			}
			const rate = layer.rate ?? 1;
			const placement = peakAlignedPlacement(asset, cutFrame, fps, rate);
			// Asked for a cool leak but only warm ones exist (or vice versa): tint it, as an editor would.
			const opposite = layer.select.tone && asset.tone !== layer.select.tone && [asset.tone, layer.select.tone].every((t) => t === 'warm' || t === 'cool');
			const filter = [opposite ? 'hue-rotate(180deg)' : '', styleTint(style) ?? ''].filter(Boolean).join(' ') || undefined;
			return (
				<OverlayLayer
					src={vfxSrc(asset)}
					blendMode={layer.blend ?? asset.analysis.recommended_blend}
					opacity={layer.opacity * style.vfx.overlayOpacityScale * pulse(rel, layer.attack, layer.release)}
					from={placement.from}
					durationInFrames={placement.durationInFrames}
					playbackRate={rate}
					filter={filter}
					transparent={asset.technical.has_alpha}
				/>
			);
		}
		case 'flash': {
			const a = pulse(rel, layer.attack, layer.release, layer.hold ?? 0) * layer.opacity;
			if (a <= 0) return null;
			const blend = layer.blend === 'add' ? 'plus-lighter' : layer.blend ?? 'normal';
			return <AbsoluteFill style={{backgroundColor: layer.color, opacity: a, mixBlendMode: blend as React.CSSProperties['mixBlendMode']}} />;
		}
		case 'dip': {
			const a = pulse(rel, layer.attack, layer.release, layer.hold ?? 0);
			return a > 0 ? <AbsoluteFill style={{backgroundColor: layer.color, opacity: a}} /> : null;
		}
		case 'film_burn':
			return <FilmBurn rel={rel} tone={layer.tone} strength={layer.opacity * style.vfx.overlayOpacityScale * pulse(rel, layer.attack, layer.release)} />;
		default:
			return null;
	}
};

// ---------------------------------------------------------------------------

/**
 * A cut from A to B with any number of VFX layers stacked on it: the way
 * editors pile a leak, a flash and a whoosh onto one edit point. Media
 * layers (zoom, blur, RGB split, glitch...) modify the shots; overlay
 * layers (footage overlays, flash, dip, burn) composite on top in order.
 */
export const TransitionStack: React.FC<TransitionStackProps> = ({spec, cutFrame, outgoing, incoming, style, seed, sfxSources}) => {
	const frame = useCurrentFrame();
	const {fps, width, height} = useVideoConfig();
	const catalog = useVfxCatalog();
	const rel = frame - cutFrame;
	const {cut} = spec;
	const common = {rel, frame, cutFrame, layers: spec.layers, seed, width, height};

	let sides: React.ReactNode;
	const whip = spec.layers.find((l) => l.kind === 'whip_pan');
	const whipping = whip !== undefined && rel > -whip.attack && rel < whip.release;
	if (cut.type === 'hard' && whipping) {
		sides = (
			<>
				<SideLayer side="out" {...common}>{outgoing}</SideLayer>
				<SideLayer side="in" {...common}>{incoming}</SideLayer>
			</>
		);
	} else if (cut.type === 'hard') {
		sides = rel < 0 ? <SideLayer side="out" {...common}>{outgoing}</SideLayer> : <SideLayer side="in" {...common}>{incoming}</SideLayer>;
	} else if (cut.type === 'crossfade') {
		const p = progress(rel, -cut.frames / 2, cut.frames / 2);
		sides = (
			<>
				{p < 1 ? <SideLayer side="out" {...common}>{outgoing}</SideLayer> : null}
				{p > 0 ? <SideLayer side="in" {...common} opacity={p}>{incoming}</SideLayer> : null}
			</>
		);
	} else {
		const p = progress(rel, -cut.frames / 2, cut.frames / 2);
		let mask: string | undefined;
		let maskSize: string | undefined;
		let extraFilter: string | undefined;
		if (cut.type === 'soft_wipe') {
			const to = {left: 'to left', right: 'to right', up: 'to top', down: 'to bottom'}[cut.direction];
			const edge = p * 130 - 15; // soft 15% feather travelling across the frame
			mask = `linear-gradient(${to}, #000 ${edge.toFixed(2)}%, rgba(0,0,0,0) ${(edge + 15).toFixed(2)}%)`;
		} else {
			// Halftone dots grow until they merge; B resolves from grey to colour.
			mask = `radial-gradient(circle, #000 ${(p * 72).toFixed(2)}%, rgba(0,0,0,0) ${(p * 72 + 2).toFixed(2)}%)`;
			maskSize = `${cut.cellPx}px ${cut.cellPx}px`;
			extraFilter = `grayscale(${(1 - p).toFixed(3)}) contrast(${(1 + 0.4 * (1 - p)).toFixed(3)})`;
		}
		sides = (
			<>
				{p < 1 ? <SideLayer side="out" {...common}>{outgoing}</SideLayer> : null}
				{p > 0 ? (
					<SideLayer side="in" {...common} mask={p < 1 ? mask : undefined} maskSize={p < 1 ? maskSize : undefined} extraFilter={p < 1 ? extraFilter : undefined}>
						{incoming}
					</SideLayer>
				) : null}
			</>
		);
	}

	return (
		<AbsoluteFill style={{backgroundColor: '#000', overflow: 'hidden'}}>
			{sides}
			{spec.layers
				.filter((l) => !MEDIA_KINDS.has(l.kind))
				.map((layer, i) => (
					<OverlayStackLayer key={i} layer={layer} rel={rel} cutFrame={cutFrame} fps={fps} style={style} seed={`${seed}-${i}`} catalog={catalog} />
				))}
			{(spec.sfx ?? []).map((s, i) => {
				const src = sfxSources?.[s.cue];
				return src ? (
					<Sequence key={i} from={cutFrame + (s.at ?? 0)} layout="none">
						<Audio src={src} volume={s.volume ?? 1} />
					</Sequence>
				) : null;
			})}
		</AbsoluteFill>
	);
};
