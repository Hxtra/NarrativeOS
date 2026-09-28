import {Easing, interpolate} from 'remotion';

const clamp = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'} as const;

/**
 * 0 → 1 → 0 around the cut. `rel` is frames relative to the cut (negative
 * before it). `attack` frames to rise, `release` frames to fall, `hold`
 * frames at full strength after the cut. attack = 0 means the effect starts
 * exactly on the cut.
 */
export function pulse(rel: number, attack: number, release: number, hold = 0): number {
	if (rel < 0) {
		if (attack <= 0) return 0;
		return interpolate(rel, [-attack, 0], [0, 1], {...clamp, easing: Easing.in(Easing.quad)});
	}
	if (rel <= hold) return 1;
	if (release <= 0) return 0;
	return interpolate(rel - hold, [0, release], [1, 0], {...clamp, easing: Easing.out(Easing.quad)});
}

/** 0 → 1 across [start, end] frames relative to the cut, eased in-out. */
export function progress(rel: number, start: number, end: number): number {
	return interpolate(rel, [start, end], [0, 1], {...clamp, easing: Easing.inOut(Easing.cubic)});
}

/** Rises toward the cut on the outgoing side, falls after it on the incoming side. */
export function sided(rel: number, attack: number, release: number): {out: number; in: number} {
	return {
		out: rel < 0 && attack > 0 ? interpolate(rel, [-attack, 0], [0, 1], {...clamp, easing: Easing.in(Easing.cubic)}) : 0,
		in: rel >= 0 && release > 0 ? interpolate(rel, [0, release], [1, 0], {...clamp, easing: Easing.out(Easing.cubic)}) : 0,
	};
}
