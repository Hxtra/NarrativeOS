import {useEffect, useState} from 'react';
import {continueRender, delayRender, random, staticFile} from 'remotion';

// Mirrors vfx-library/schema/vfx_asset.schema.json (the fields the engine reads).
export type VfxCategory =
	| 'light_leak'
	| 'film_burn'
	| 'flash'
	| 'lens_flare'
	| 'dust'
	| 'grain'
	| 'scratches'
	| 'glitch'
	| 'smoke'
	| 'bokeh'
	| 'particles'
	| 'texture'
	| 'graphic_elements'
	| 'unclassified';

export type VfxTone = 'warm' | 'cool' | 'neutral' | 'mono';
export type VfxBlend = 'screen' | 'add' | 'overlay' | 'multiply' | 'normal';

export interface VfxAsset {
	id: string;
	library_path: string;
	category: VfxCategory;
	category_status: 'suggested' | 'confirmed';
	tone: VfxTone;
	technical: {duration_sec: number | null; source_fps: number | null; has_alpha: boolean};
	analysis: {peak_time_sec: number; recommended_blend: VfxBlend};
	rights: {rights_status: 'unknown' | 'verified' | 'restricted'; redistributable: boolean};
}

export interface VfxCatalog {
	schema_version: 1;
	assets: VfxAsset[];
}

/** How a recipe asks for an overlay: by kind of clip, never by filename. */
export interface VfxSelector {
	category: VfxCategory;
	/** Preferred tone; falls back to any tone in the category. */
	tone?: VfxTone;
	/** Pin one exact asset (e.g. an editor's deliberate pick). */
	assetId?: string;
}

/** Library root as served by Remotion: public/vfx is a junction made by scripts/link_vfx_library.py. */
export const vfxSrc = (asset: VfxAsset) => staticFile(`vfx/${asset.library_path}`);

let catalogPromise: Promise<VfxCatalog | null> | null = null;

function loadCatalog(): Promise<VfxCatalog | null> {
	if (!catalogPromise) {
		catalogPromise = fetch(staticFile('vfx/vfx_catalog.json'))
			.then((r) => (r.ok ? (r.json() as Promise<VfxCatalog>) : null))
			.catch(() => null);
	}
	return catalogPromise;
}

/**
 * The linked VFX catalog, or null when no library is linked. Null is a
 * normal state, not an error: overlay layers then use their procedural
 * fallback, so every recipe still renders out of the box.
 */
export function useVfxCatalog(): VfxCatalog | null | undefined {
	const [catalog, setCatalog] = useState<VfxCatalog | null | undefined>(undefined);
	const [handle] = useState(() => delayRender('Loading VFX catalog'));
	useEffect(() => {
		loadCatalog().then((c) => {
			setCatalog(c);
			continueRender(handle);
		});
	}, [handle]);
	return catalog;
}

/**
 * Deterministic pick: confirmed assets only (a suggested category has not
 * been looked at yet), exact id wins, then tone preference, then any tone.
 */
export function resolveOverlay(catalog: VfxCatalog | null | undefined, sel: VfxSelector, seed: string): VfxAsset | null {
	if (!catalog) return null;
	const confirmed = catalog.assets.filter((a) => a.category_status === 'confirmed');
	if (sel.assetId) return confirmed.find((a) => a.id === sel.assetId) ?? null;
	const inCategory = confirmed.filter((a) => a.category === sel.category);
	const toned = sel.tone ? inCategory.filter((a) => a.tone === sel.tone) : [];
	const pool = toned.length ? toned : inCategory;
	if (!pool.length) return null;
	return pool[Math.floor(random(`vfx-${seed}`) * pool.length)];
}
