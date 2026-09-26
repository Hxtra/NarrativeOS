import {useCurrentFrame, random} from 'remotion';

/**
 * Exposure-flicker only — no positional jitter. Was previously bundled
 * inside useOrganicWeave's single brightness() filter line, which meant
 * a component wanting old-film exposure variance on footage that already
 * moves (real video, not a static archival photo) had to take the
 * translate/rotate jitter too, whether it wanted it or not.
 *
 * useOrganicWeave now composes this rather than duplicating the math —
 * refactor verified pixel-identical (with the bundle cache cleared first;
 * see architecture.md for why that check matters).
 */
export function useArchiveFlicker(amount: number, seedPrefix = 'flicker'): {filter: string} {
	const frame = useCurrentFrame();
	if (amount <= 0) return {filter: 'none'};
	const flicker = 1 + (random(`${seedPrefix}-${frame}`) - 0.5) * 0.085 * amount;
	return {filter: `brightness(${flicker.toFixed(4)})`};
}
