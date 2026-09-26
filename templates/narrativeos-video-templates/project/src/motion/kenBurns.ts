import {Easing, interpolate, useCurrentFrame} from 'remotion';

export interface KenBurnsSpec {
	fromScale: number;
	toScale: number;
	fromX: number; // percent
	toX: number;
	fromY: number;
	toY: number;
}

/**
 * The actual reusable primitive — was previously inlined directly inside
 * MediaReveal, which meant no other template could use the same motion
 * without copy-pasting the math. Any template applies this the same way:
 *
 *   const mediaStyle = { ...useKenBurns(spec, durationInFrames, ease), objectFit: 'cover' }
 *
 * and spreads the resulting transform onto whatever media element it's
 * animating (Img, OffthreadVideo, or even a div background).
 */
export function useKenBurns(
	spec: KenBurnsSpec,
	durationInFrames: number,
	ease: [number, number, number, number] = [0.37, 0.03, 0.63, 0.97],
): {transform: string} {
	const frame = useCurrentFrame();
	const p = interpolate(frame, [0, durationInFrames], [0, 1], {
		extrapolateLeft: 'clamp',
		extrapolateRight: 'clamp',
		easing: Easing.bezier(...ease),
	});
	const scale = spec.fromScale + (spec.toScale - spec.fromScale) * p;
	const tx = spec.fromX + (spec.toX - spec.fromX) * p;
	const ty = spec.fromY + (spec.toY - spec.fromY) * p;
	return {transform: `scale(${scale}) translate(${tx}%, ${ty}%)`};
}

export const DEFAULT_KEN_BURNS: KenBurnsSpec = {
	fromScale: 1.08,
	toScale: 1.22,
	fromX: 0,
	toX: -1.5,
	fromY: 1,
	toY: -1,
};
