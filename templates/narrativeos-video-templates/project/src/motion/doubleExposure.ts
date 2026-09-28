import type React from 'react';
import {Easing, interpolate, useCurrentFrame} from 'remotion';

export type DoubleExposureMask = 'none' | 'radial-vignette' | 'bottom-fade';

export interface DoubleExposureSpec {
	blendMode?: React.CSSProperties['mixBlendMode']; // default 'screen'
	/** Static opacity, or an animated [from, to] over durationInFrames */
	opacity?: number | [number, number];
	/** Overlay's own translate offset, percent of its own box (matches this project's existing translate% convention) */
	position?: {xPercent: number; yPercent: number};
	/** Static scale, or an animated [from, to] over durationInFrames */
	scale?: number | [number, number];
	mask?: DoubleExposureMask;
}

export interface DoubleExposureResult {
	/** Apply to the overlay (secondary media) element/wrapper */
	overlayStyle: React.CSSProperties;
	/** Apply alongside overlayStyle when a mask is requested — kept
	 * separate so a component can compose it with its own mask if needed */
	maskStyle: React.CSSProperties;
}

const MASKS: Record<DoubleExposureMask, string> = {
	none: '',
	'radial-vignette': 'radial-gradient(ellipse 70% 70% at 50% 50%, #000 40%, transparent 90%)',
	'bottom-fade': 'linear-gradient(to bottom, #000 0%, #000 55%, transparent 100%)',
};

/**
 * The actual test this exists for: can the primitive system compose two
 * independent media sources into one treatment, the same way useKenBurns
 * and containFit compose onto a single source? This returns styles only —
 * it doesn't render anything itself, the same shape as every other
 * primitive in this project, so an editorial component decides how to lay
 * out the two media elements and just spreads these styles onto the
 * overlay one.
 */
export function useDoubleExposure(spec: DoubleExposureSpec, durationInFrames: number): DoubleExposureResult {
	const frame = useCurrentFrame();
	const p = interpolate(frame, [0, durationInFrames], [0, 1], {
		extrapolateLeft: 'clamp',
		extrapolateRight: 'clamp',
		easing: Easing.inOut(Easing.sin),
	});

	const opacity = Array.isArray(spec.opacity) ? spec.opacity[0] + (spec.opacity[1] - spec.opacity[0]) * p : (spec.opacity ?? 0.5);
	const scale = Array.isArray(spec.scale) ? spec.scale[0] + (spec.scale[1] - spec.scale[0]) * p : (spec.scale ?? 1);
	const pos = spec.position ?? {xPercent: 0, yPercent: 0};

	const maskImage = spec.mask && spec.mask !== 'none' ? MASKS[spec.mask] : undefined;

	return {
		overlayStyle: {
			opacity,
			transform: `scale(${scale}) translate(${pos.xPercent}%, ${pos.yPercent}%)`,
			mixBlendMode: spec.blendMode ?? 'screen',
		},
		maskStyle: maskImage
			? {WebkitMaskImage: maskImage, maskImage, WebkitMaskSize: 'cover', maskSize: 'cover'}
			: {},
	};
}

export const DEFAULT_DOUBLE_EXPOSURE: DoubleExposureSpec = {
	blendMode: 'screen',
	opacity: [0, 0.42],
	position: {xPercent: 7, yPercent: -4},
	scale: 1.35,
	mask: 'none',
};
