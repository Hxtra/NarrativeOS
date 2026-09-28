import type React from 'react';
import type {StyleProfile} from '../styles/StyleProfile';

export interface TemplateDefinition<P> {
	id: string;
	label: string;
	/** Pack this belongs to, matching the brief: 'core' | 'speaker' | 'archive' | 'evidence' | 'transition' | 'typography' | 'audio' */
	pack: string;
	durationInFrames: (params: P, fps: number) => number;
	component: React.FC<{style: StyleProfile; params: P}>;
	defaultParams: P;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export const TEMPLATE_REGISTRY: Record<string, TemplateDefinition<any>> = {};

export function registerTemplate<P>(def: TemplateDefinition<P>): void {
	if (TEMPLATE_REGISTRY[def.id]) {
		throw new Error(`Template "${def.id}" is already registered.`);
	}
	TEMPLATE_REGISTRY[def.id] = def;
}

/**
 * The actual "pick and fill the placeholder" call: NarrativeOS's render
 * stage calls this with a template id + params from the Timeline IR — no
 * per-video code generation, no LLM asked to write a component.
 */
export function resolveTemplate<P>(id: string): TemplateDefinition<P> {
	const def = TEMPLATE_REGISTRY[id];
	if (!def) {
		const known = Object.keys(TEMPLATE_REGISTRY).join(', ') || '(none registered yet)';
		throw new Error(`Unknown template "${id}". Known templates: ${known}`);
	}
	return def;
}

export function listTemplates(pack?: string) {
	return Object.values(TEMPLATE_REGISTRY).filter((t) => !pack || t.pack === pack);
}
