import {GENERATED_STYLES} from './generated';

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

/**
 * How a style uses the VFX/transition library (src/vfx). The Director may
 * only pick transitions listed in allowedTransitions; the first entry is
 * the style's default cut. Overlay opacity and tint are scaled here so one
 * recipe reads right in every style.
 */
export interface VfxStyleSpec {
	density: 'minimal' | 'moderate' | 'bold';
	allowedTransitions: string[];
	/** Multiplies every overlay/burn opacity in a recipe. */
	overlayOpacityScale: number;
	/** Applied to footage overlays so a stock leak matches the grade. */
	tint: {hueRotate: number; saturate: number};
}

export interface StyleProfile {
	id: string;
	label: string;
	grade: GradeSpec;
	typography: TypographySpec;
	motion: MotionSpec;
	/** Which transitions this style is allowed to reach for, in preference order. Legacy; see `vfx`. */
	transitionSet: BurnKind[];
	vfx: VfxStyleSpec;
	/**
	 * Evidence status of the profile itself: DOCUMENTED = described from a
	 * reference analysis but not yet checked against real renders of that
	 * genre; VALIDATED = confirmed against real references.
	 */
	status?: 'DOCUMENTED' | 'VALIDATED';
	/** Editing rhythm: how long shots hold, how often cuts land, whether cuts follow the music. */
	pacing?: {targetShotSec: number; cutsPerMinute: number; beatSync: boolean};
	/** Where the profile came from, when it was generated from a reference video by style_intel. */
	source?: {kind: 'reference_video'; file: string; sha256: string; analyzerVersion: string};
	/** Traits the generator could not measure and filled with defaults (e.g. typography). */
	unmeasured?: string[];
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
	vfx: {
		density: 'moderate',
		allowedTransitions: ['hard_cut', 'dip_to_black', 'archive_flicker_cut', 'film_burn_passage', 'light_leak_warm', 'crossfade_soft', 'halftone_reveal', 'flash_cut', 'push_in_cut'],
		overlayOpacityScale: 1,
		tint: {hueRotate: 0, saturate: 1},
	},
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
	vfx: {
		density: 'moderate',
		allowedTransitions: ['hard_cut', 'soft_wipe_left', 'soft_wipe_up', 'flash_cut', 'dip_to_black', 'rgb_split_hit', 'glitch_cut', 'whip_pan_left', 'whip_pan_right'],
		overlayOpacityScale: 0.8,
		tint: {hueRotate: 0, saturate: 0.9},
	},
	vignetteStrength: 0.5,
	grainOpacity: 0.12,
	layouts: {
		title_card: 'corner-frame-broadcast',
	},
};

/**
 * Premium streaming-documentary look (the "Netflix documentary" feel), named
 * generically on purpose: no brand clone. Basis: the owner's reference
 * analysis in NarrativeOS_Master_Handoff.md section 42 (clean sans, restrained
 * titles, purposeful hard cuts, slow push-ins, cinematic grade, subtle grain,
 * selective light effects). DOCUMENTED until checked against real references.
 */
export const premiumDocumentary: StyleProfile = {
	id: 'premium_documentary',
	label: 'Premium Documentary (streaming-doc feel)',
	status: 'DOCUMENTED',
	grade: {
		// Colour, not black-and-white: gentle contrast, slightly lifted blacks, restrained saturation.
		filter: 'contrast(1.08) saturate(0.86) brightness(0.97)',
		shadow: 'rgba(14,34,44,0.28)',
		highlight: 'rgba(255,214,170,0.12)',
	},
	typography: {
		serifFamily: 'PlayfairLocal, Georgia, serif',
		sansFamily: 'InterLocal, Helvetica, Arial, sans-serif',
		headlineWeight: 600,
		kickerLetterSpacing: 6,
		boneColor: 'rgba(246,244,240,0.98)',
		boneDimColor: 'rgba(222,220,214,0.7)',
	},
	motion: {
		weaveAmount: 0, // digital cinema camera: no projector jitter
		kenBurnsEase: [0.45, 0, 0.55, 1],
		titleStaggerFrames: 0.6,
	},
	transitionSet: ['none'],
	vfx: {
		density: 'minimal',
		allowedTransitions: ['hard_cut', 'push_in_cut', 'dip_to_black', 'crossfade_soft', 'memory_fade', 'exposure_bump', 'light_leak_warm', 'blur_dissolve'],
		overlayOpacityScale: 0.6,
		tint: {hueRotate: -6, saturate: 0.85},
	},
	vignetteStrength: 0.45,
	grainOpacity: 0.1,
	layouts: {
		title_card: 'minimal-sans',
	},
};

export const STYLE_REGISTRY: Record<string, StyleProfile> = {
	documentary_general: documentaryGeneral,
	documentary_broadcast_grid: documentaryBroadcastGrid,
	premium_documentary: premiumDocumentary,
};

// Profiles generated from reference videos (python -m style_intel profile ...).
for (const generated of GENERATED_STYLES) {
	if (STYLE_REGISTRY[generated.id]) throw new Error(`Generated style "${generated.id}" collides with a built-in style.`);
	STYLE_REGISTRY[generated.id] = generated;
}

export function getStyle(id: string): StyleProfile {
	const s = STYLE_REGISTRY[id];
	if (!s) {
		throw new Error(
			`Unknown style profile "${id}". Known: ${Object.keys(STYLE_REGISTRY).join(', ')}`,
		);
	}
	return s;
}
