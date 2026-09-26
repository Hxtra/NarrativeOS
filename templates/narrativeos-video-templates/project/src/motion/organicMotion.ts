import {useCurrentFrame, random} from 'remotion';
import type {MotionSpec} from '../styles/StyleProfile';
import {useArchiveFlicker} from './archiveFlicker';

/**
 * The code-equivalent of the real rig found in Urban Slideshow.aep:
 *   wiggle(30, thisComp.layer("Null 1").effect("Slider Control 1")(...)[0], position[1])
 * — one Null's position wiggles; everything else parents to it.
 *
 * Here: one call per composition, its output style spread onto a wrapping
 * element that everything else lives inside — same "one rig, many followers"
 * shape, deterministic (seeded hash, no Math.random) so it's frame-exact on
 * every render, matching the determinism constraints proven out in the
 * HyperFrames build.
 */
export function useOrganicWeave(motion: MotionSpec): React.CSSProperties {
	const frame = useCurrentFrame();
	const amount = motion.weaveAmount;
	if (amount <= 0) return {};

	const slot = Math.floor(frame / 2);
	const dx = (random(`weave-x-${slot}`) - 0.5) * 6 * amount;
	const dy = (random(`weave-y-${slot}`) - 0.5) * 5 * amount;
	const rot = (random(`weave-r-${slot}`) - 0.5) * 0.18 * amount;
	// Same exact seed prefix ("weave-f") as before extraction, so this
	// composition is behaviorally lossless — verified pixel-identical
	// with the bundle cache cleared first.
	const flicker = useArchiveFlicker(amount, 'weave-f');

	return {
		transform: `translate(${dx.toFixed(3)}px, ${dy.toFixed(3)}px) rotate(${rot.toFixed(4)}deg)`,
		filter: flicker.filter,
	};
}

/**
 * A generic wiggle, for anything that isn't the whole-frame weave — the
 * direct equivalent of applying wiggle() to a single property (position,
 * rotation, scale) the way the real template did on its Null.
 */
export function useWiggle(
	seed: string,
	frequencyPerSecond: number,
	amplitude: number,
	fps = 30,
): number {
	const frame = useCurrentFrame();
	const slot = Math.floor((frame / fps) * frequencyPerSecond);
	const a = random(`${seed}-a-${slot}`) - 0.5;
	const b = random(`${seed}-b-${slot + 1}`) - 0.5;
	const t = ((frame / fps) * frequencyPerSecond) % 1;
	// smoothstep between two random targets so it drifts rather than snaps
	const s = t * t * (3 - 2 * t);
	return (a + (b - a) * s) * 2 * amplitude;
}
