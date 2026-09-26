// The style-hub. Mirrors the pattern both real .aep templates used:
// one central place holding grade/typography/transition-set/motion params,
// referenced by every template component — never hardcoded per-template.
// This is the code-equivalent of the "Color" comp both purchased templates
// wired every layer's color effects through via expressions.

export type BurnKind = 'wipe' | 'flash' | 'vertical' | 'bloom' | 'none';

export interface GradeSpec {
	filter: string; // CSS filter chain applied to the plate
	shadow: string; // multiply-blend wash, shadows
	highlight: string; // soft-light wash, highlights
}

export interface TypographySpec {
	serifFamily: string;
	sansFamily: string;
	headlineWeight: number;
	kickerLetterSpacing: number;
	boneColor: string; // primary text color
	boneDimColor: string; // secondary/caption text color
}

export interface MotionSpec {
	/** Base amount for the shared organic-jitter rig (gate weave). 0 disables it. */
	weaveAmount: number;
	/** Ken Burns default ease, as a cubic-bezier tuple. */
	kenBurnsEase: [number, number, number, number];
	/** Per-character title stagger, in frames at 30fps. */
	titleStaggerFrames: number;
}

export interface StyleProfile {
	id: string;
	label: string;
	grade: GradeSpec;
	typography: TypographySpec;
	motion: MotionSpec;
	/** Which transitions this style is allowed to reach for, in preference order. */
	transitionSet: BurnKind[];
	vignetteStrength: number;
	grainOpacity: number;
	/**
	 * Structural layout choice per template id — NOT color/type, actual
	 * composition. A style that only changes grade/typography is still
	 * reusing someone else's structure with a different coat of paint,
	 * which is a real gap: different documentary styles don't just look
	 * different, they're composed differently (what's on screen, where,
	 * in what order). Keys are template ids; values are layout variant
	 * names that template's own component knows how to render. A missing
	 * key means the template's default layout.
	 *
	 * Only add a variant here with a real, defensible structural basis —
	 * general broadcast-graphic convention, or something confirmed by the
	 * .aep reverse-engineering / case-library work. Do not add a variant
	 * because it "feels like" what true crime or DW would do — that's
	 * the exact guessing failure mode this schema exists to keep out.
	 * See references/architecture.md.
	 */
	layouts?: Record<string, string>;
}

// ---- Concrete profiles ----
// Start with one general-purpose documentary look (the through-line profile
// used in this project so far). Style-specific profiles (DW, true crime,
// mystery, educational...) get added here as their own StyleProfile objects
// once the case-library work gives us real grounds for their specifics —
// until then, they'd just be guesses wearing a style name.

export const documentaryGeneral: StyleProfile = {
	id: 'documentary_general',
	label: 'Documentary — General Archival',
	grade: {
		filter: 'grayscale(1) contrast(1.22) brightness(0.92)',
		shadow: 'rgba(48,32,86,0.62)',
		highlight: 'rgba(206,196,224,0.34)',
	},
	typography: {
		serifFamily: 'PlayfairLocal, Georgia, serif',
		sansFamily: 'BarlowLocal, Helvetica, sans-serif',
		headlineWeight: 700,
		kickerLetterSpacing: 7,
		boneColor: 'rgba(243,238,230,0.97)',
		boneDimColor: 'rgba(232,225,214,0.72)',
	},
	motion: {
		weaveAmount: 1.0,
		kenBurnsEase: [0.37, 0.03, 0.63, 0.97],
		titleStaggerFrames: 1.5,
	},
	transitionSet: ['wipe', 'flash', 'vertical', 'bloom'],
	vignetteStrength: 0.9,
	grainOpacity: 0.34,
};

export const documentaryBroadcastGrid: StyleProfile = {
	id: 'documentary_broadcast_grid',
	label: 'Documentary — Broadcast Grid',
	// Structural basis: standard broadcast-graphic convention (network news
	// opens, corner "bugs", lower-third-anchored titles) — asymmetric,
	// corner-anchored composition rather than centered. This is generic,
	// well-established design convention, not a specific unverified claim
	// about any one documentary genre.
	grade: {
		filter: 'grayscale(1) contrast(1.15) brightness(1.0)',
		shadow: 'rgba(20,28,44,0.55)',
		highlight: 'rgba(196,210,224,0.3)',
	},
	typography: {
		serifFamily: 'PlayfairLocal, Georgia, serif',
		sansFamily: 'BarlowLocal, Helvetica, sans-serif',
		headlineWeight: 700,
		kickerLetterSpacing: 4,
		boneColor: 'rgba(240,244,248,0.98)',
		boneDimColor: 'rgba(200,212,222,0.75)',
	},
	motion: {
		weaveAmount: 0.5, // steadier, less archival-jitter — a broadcast graphic isn't old film
		kenBurnsEase: [0.25, 0.1, 0.25, 1],
		titleStaggerFrames: 1.0,
	},
	transitionSet: ['flash', 'none'],
	vignetteStrength: 0.5,
	grainOpacity: 0.12,
	layouts: {
		title_card: 'corner-frame-broadcast',
	},
};

export const STYLE_REGISTRY: Record<string, StyleProfile> = {
	documentary_general: documentaryGeneral,
	documentary_broadcast_grid: documentaryBroadcastGrid,
};

export function getStyle(id: string): StyleProfile {
	const s = STYLE_REGISTRY[id];
	if (!s) {
		throw new Error(
			`Unknown style profile "${id}". Known: ${Object.keys(STYLE_REGISTRY).join(', ')}`,
		);
	}
	return s;
}
