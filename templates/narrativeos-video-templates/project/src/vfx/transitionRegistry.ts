import type {TransitionSpec} from './TransitionStack';

export interface TransitionRecipe {
	id: string;
	label: string;
	/**
	 * What the transition says editorially. The Director picks by meaning,
	 * not by look: most cuts should stay clean, effects are for moments
	 * that earn them.
	 */
	meaning: string;
	intensity: 'clean' | 'subtle' | 'medium' | 'bold';
	/** Frames before / after the cut the recipe needs on screen. */
	window: {before: number; after: number};
	spec: TransitionSpec;
}

export const TRANSITION_REGISTRY: Record<string, TransitionRecipe> = {};

export function registerTransition(recipe: TransitionRecipe): void {
	if (TRANSITION_REGISTRY[recipe.id]) throw new Error(`Transition "${recipe.id}" is already registered.`);
	TRANSITION_REGISTRY[recipe.id] = recipe;
}

export function resolveTransition(id: string): TransitionRecipe {
	const r = TRANSITION_REGISTRY[id];
	if (!r) throw new Error(`Unknown transition "${id}". Known: ${Object.keys(TRANSITION_REGISTRY).join(', ')}`);
	return r;
}

export function listTransitions(intensity?: TransitionRecipe['intensity']): TransitionRecipe[] {
	return Object.values(TRANSITION_REGISTRY).filter((r) => !intensity || r.intensity === intensity);
}
