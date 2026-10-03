// First batch of transition recipes. Each is data only: a cut type plus a
// stack of layers from TransitionStack. New recipes are new combinations,
// not new code. Timings assume 30fps.
import {registerTransition, type TransitionRecipe} from './transitionRegistry';
import type {VfxLayer} from './TransitionStack';
import type {VfxBlend} from './catalog';

const r = (recipe: TransitionRecipe) => registerTransition(recipe);

// Reusable layer fragments.
const burnWarm: VfxLayer = {kind: 'film_burn', tone: 'warm', opacity: 0.95, attack: 12, release: 14};
const burnCool: VfxLayer = {kind: 'film_burn', tone: 'cool', opacity: 0.9, attack: 12, release: 14};
const leak = (tone: 'warm' | 'cool', opacity = 0.85, attack = 14, release = 18): VfxLayer => ({
	kind: 'overlay',
	select: {category: 'light_leak', tone},
	opacity,
	attack,
	release,
	fallback: {...(tone === 'warm' ? burnWarm : burnCool), opacity: opacity * 0.8, attack, release},
});
const whiteFlash = (opacity = 1, attack = 2, release = 6, hold = 0): VfxLayer => ({kind: 'flash', color: '#fff', opacity, attack, release, hold});

// --- Clean -----------------------------------------------------------------
r({id: 'hard_cut', label: 'Hard cut', meaning: 'The default. Most professional cuts are clean; nothing else draws attention to the edit.', intensity: 'clean', window: {before: 15, after: 15}, spec: {cut: {type: 'hard'}, layers: []}});
r({id: 'crossfade_soft', label: 'Soft crossfade', meaning: 'Passage of time or a gentle change of place, used sparingly.', intensity: 'clean', window: {before: 15, after: 15}, spec: {cut: {type: 'crossfade', frames: 18}, layers: []}});
r({id: 'dip_to_black', label: 'Dip to black', meaning: 'Chapter end, a pause, or a heavy beat landing.', intensity: 'clean', window: {before: 20, after: 20}, spec: {cut: {type: 'hard'}, layers: [{kind: 'dip', color: '#000', attack: 14, release: 14, hold: 2}]}});
r({id: 'dip_to_white', label: 'Dip to white', meaning: 'Memory, revelation, or entering a flashback.', intensity: 'subtle', window: {before: 18, after: 18}, spec: {cut: {type: 'hard'}, layers: [{kind: 'dip', color: '#f6f2ea', attack: 12, release: 12, hold: 1}]}});
r({id: 'blur_dissolve', label: 'Blur dissolve', meaning: 'Dreamlike drift between related images; softer than a crossfade.', intensity: 'subtle', window: {before: 18, after: 18}, spec: {cut: {type: 'crossfade', frames: 20}, layers: [{kind: 'blur', px: 14, attack: 14, release: 14}]}});
r({id: 'push_in_cut', label: 'Push-in cut', meaning: 'Slow cinematic emphasis: lean into A, then cut. Premium-documentary staple.', intensity: 'subtle', window: {before: 30, after: 10}, spec: {cut: {type: 'hard'}, layers: [{kind: 'zoom_punch', scale: 1.07, attack: 30, release: 0, side: 'out'}]}});

// --- Light / exposure ---------------------------------------------------------
r({id: 'flash_cut', label: 'Flash cut', meaning: 'Impact or a camera-flash reveal.', intensity: 'medium', window: {before: 10, after: 14}, spec: {cut: {type: 'hard'}, layers: [whiteFlash(1, 2, 8)], sfx: [{cue: 'shutter'}]}});
r({id: 'exposure_bump', label: 'Exposure bump', meaning: 'A warm breath of light on the cut; subtle energy without a flash.', intensity: 'subtle', window: {before: 10, after: 14}, spec: {cut: {type: 'hard'}, layers: [{kind: 'flash', color: '#ffd9a8', opacity: 0.55, attack: 4, release: 10, blend: 'screen'}]}});
r({id: 'light_leak_warm', label: 'Warm light leak', meaning: 'Memory, warmth, nostalgia; a cinematic passage.', intensity: 'medium', window: {before: 18, after: 22}, spec: {cut: {type: 'hard'}, layers: [leak('warm')]}});
r({id: 'light_leak_cool', label: 'Cool light leak', meaning: 'Night, distance, melancholy; a colder passage.', intensity: 'medium', window: {before: 18, after: 22}, spec: {cut: {type: 'hard'}, layers: [leak('cool')]}});
r({id: 'leak_crossfade', label: 'Leak crossfade', meaning: 'A soft dissolve carried by light; gentle transition between moods.', intensity: 'medium', window: {before: 20, after: 20}, spec: {cut: {type: 'crossfade', frames: 16}, layers: [leak('warm', 0.75, 18, 20)]}});
r({id: 'leak_flash_combo', label: 'Leak + flash', meaning: 'Energetic cinematic reveal; the layered leak-and-flash editors stack on hero moments.', intensity: 'bold', window: {before: 16, after: 20}, spec: {cut: {type: 'hard'}, layers: [leak('warm', 0.9, 14, 18), whiteFlash(0.8, 2, 6), {kind: 'directional_blur', px: 18, axis: 'x', attack: 4, release: 5}], sfx: [{cue: 'whoosh', at: -8}, {cue: 'impact'}]}});
r({id: 'memory_fade', label: 'Memory fade', meaning: 'Drifting into the past: blur, warm light, slow dissolve.', intensity: 'subtle', window: {before: 24, after: 24}, spec: {cut: {type: 'crossfade', frames: 26}, layers: [{kind: 'blur', px: 8, attack: 20, release: 20}, leak('warm', 0.5, 22, 24)]}});
r({id: 'film_burn_passage', label: 'Film burn', meaning: 'Archival passage of time, analog decay.', intensity: 'bold', window: {before: 18, after: 18}, spec: {cut: {type: 'hard'}, layers: [{kind: 'overlay', select: {category: 'film_burn'}, opacity: 1, attack: 14, release: 16, fallback: burnWarm}]}});
r({id: 'film_burn_procedural', label: 'Film burn (procedural)', meaning: 'Same as film burn, always procedural: works with no overlay library.', intensity: 'bold', window: {before: 18, after: 18}, spec: {cut: {type: 'hard'}, layers: [burnWarm]}});

// --- Motion -------------------------------------------------------------------
r({id: 'whip_zoom', label: 'Whip zoom', meaning: 'Energy and forward momentum; jumping into a new place.', intensity: 'bold', window: {before: 10, after: 12}, spec: {cut: {type: 'hard'}, layers: [{kind: 'zoom_punch', scale: 1.4, attack: 8, release: 10}, {kind: 'blur', px: 6, attack: 6, release: 8}, whiteFlash(0.35, 1, 4)], sfx: [{cue: 'whoosh', at: -6}]}});
r({id: 'whip_pan_left', label: 'Whip pan left', meaning: 'Fast lateral move: "meanwhile", or following movement.', intensity: 'bold', window: {before: 8, after: 10}, spec: {cut: {type: 'hard'}, layers: [{kind: 'whip_pan', direction: 'left', blurPx: 40, attack: 7, release: 9}], sfx: [{cue: 'whoosh', at: -5}]}});
r({id: 'whip_pan_right', label: 'Whip pan right', meaning: 'Fast lateral move: "meanwhile", or following movement.', intensity: 'bold', window: {before: 8, after: 10}, spec: {cut: {type: 'hard'}, layers: [{kind: 'whip_pan', direction: 'right', blurPx: 40, attack: 7, release: 9}], sfx: [{cue: 'whoosh', at: -5}]}});
r({id: 'whip_pan_up', label: 'Whip pan up', meaning: 'Rising energy, lift-off, looking up at scale.', intensity: 'bold', window: {before: 8, after: 10}, spec: {cut: {type: 'hard'}, layers: [{kind: 'whip_pan', direction: 'up', blurPx: 40, attack: 7, release: 9}], sfx: [{cue: 'whoosh', at: -5}]}});
r({id: 'impact_cut', label: 'Impact cut', meaning: 'A hit: shock, a hard fact landing, a turning point.', intensity: 'bold', window: {before: 8, after: 16}, spec: {cut: {type: 'hard'}, layers: [{kind: 'zoom_punch', scale: 1.12, attack: 0, release: 10, side: 'in'}, whiteFlash(0.9, 1, 7), {kind: 'directional_blur', px: 22, axis: 'x', attack: 2, release: 6}], sfx: [{cue: 'impact'}, {cue: 'low_hit'}]}});
r({id: 'shake_impact', label: 'Shake impact', meaning: 'Physical force or violence; the frame itself reacts.', intensity: 'bold', window: {before: 6, after: 16}, spec: {cut: {type: 'hard'}, layers: [{kind: 'shake', px: 18, attack: 0, release: 14, side: 'in'}, whiteFlash(0.6, 1, 5)], sfx: [{cue: 'impact'}]}});

// --- Digital / glitch ---------------------------------------------------------------
r({id: 'glitch_cut', label: 'Glitch cut', meaning: 'Technology, disruption, instability; a digital subject.', intensity: 'bold', window: {before: 8, after: 10}, spec: {cut: {type: 'hard'}, layers: [{kind: 'glitch_slices', bands: 7, maxOffsetPx: 90, attack: 5, release: 6}, {kind: 'rgb_split', px: 14, attack: 5, release: 6}], sfx: [{cue: 'glitch_tick', at: -4}]}});
r({id: 'glitch_reveal', label: 'Glitch reveal', meaning: 'A corrupted signal resolving into the truth; tech-thriller reveal.', intensity: 'bold', window: {before: 14, after: 16}, spec: {cut: {type: 'hard'}, layers: [{kind: 'stutter', holdFrames: 3, attack: 10, release: 8}, {kind: 'glitch_slices', bands: 9, maxOffsetPx: 140, attack: 10, release: 12}, {kind: 'rgb_split', px: 22, attack: 10, release: 12}, whiteFlash(0.5, 1, 3)], sfx: [{cue: 'glitch_tick', at: -10}, {cue: 'glitch_tick'}]}});
r({id: 'rgb_split_hit', label: 'RGB split hit', meaning: 'A brief digital jolt without full glitch chaos.', intensity: 'medium', window: {before: 6, after: 10}, spec: {cut: {type: 'hard'}, layers: [{kind: 'rgb_split', px: 18, attack: 3, release: 8}]}});
r({id: 'digital_tear', label: 'Digital tear', meaning: 'Signal breaking apart; surveillance, hacked footage, lost transmission.', intensity: 'bold', window: {before: 8, after: 10}, spec: {cut: {type: 'hard'}, layers: [{kind: 'glitch_slices', bands: 12, maxOffsetPx: 220, attack: 6, release: 8}]}});
r({id: 'stutter_cut', label: 'Stutter cut', meaning: 'Hesitation, a skipping memory, a broken tape.', intensity: 'medium', window: {before: 12, after: 10}, spec: {cut: {type: 'hard'}, layers: [{kind: 'stutter', holdFrames: 4, attack: 12, release: 6}, whiteFlash(0.25, 1, 3)]}});

// --- Archive / graphic ------------------------------------------------------------------
r({id: 'archive_flicker_cut', label: 'Archive flicker cut', meaning: 'Old projector: entering archival footage.', intensity: 'subtle', window: {before: 12, after: 14}, spec: {cut: {type: 'hard'}, layers: [{kind: 'flicker', amount: 1, attack: 10, release: 12}, {kind: 'dip', color: '#000', attack: 3, release: 3}, {kind: 'desaturate', amount: 1, attack: 0, release: 14, side: 'in'}]}});
r({id: 'halftone_reveal', label: 'Halftone reveal', meaning: 'Stylised history: printed image resolving into living colour.', intensity: 'medium', window: {before: 20, after: 20}, spec: {cut: {type: 'halftone', frames: 30, cellPx: 22}, layers: []}});
r({id: 'soft_wipe_left', label: 'Soft wipe left', meaning: 'Clean graphic change of topic; broadcast/explainer feel.', intensity: 'subtle', window: {before: 16, after: 16}, spec: {cut: {type: 'soft_wipe', frames: 22, direction: 'left'}, layers: []}});
r({id: 'soft_wipe_up', label: 'Soft wipe up', meaning: 'Rising to a new section; restrained graphic transition.', intensity: 'subtle', window: {before: 16, after: 16}, spec: {cut: {type: 'soft_wipe', frames: 22, direction: 'up'}, layers: []}});

// --- Overlay footage from the owner's VFX library (added 2026-10-03) -------------------------------
// Each selects a confirmed library category; the fallback renders when no such clip is linked.
const greyFlash = (opacity = 0.35): VfxLayer => ({kind: 'flash', color: '#8a8a8a', opacity, attack: 3, release: 5});
const overlay = (category: 'glitch' | 'crt' | 'lens_flare' | 'scratches' | 'dust' | 'particles' | 'weather' | 'flicker', opacity: number, attack: number, release: number, fallback?: VfxLayer, blend?: VfxBlend): VfxLayer =>
	({kind: 'overlay', select: {category}, opacity, attack, release, fallback, ...(blend ? {blend} : {})});

r({id: 'glitch_overlay_cut', label: 'Glitch footage cut', meaning: 'Digital disruption carried by real glitch footage: hacked feeds, corrupted data, tech failure.', intensity: 'bold', window: {before: 8, after: 12}, spec: {cut: {type: 'hard'}, layers: [overlay('glitch', 1, 4, 7, whiteFlash(0.3, 1, 3)), {kind: 'rgb_split', px: 10, attack: 4, release: 6}], sfx: [{cue: 'glitch_tick', at: -3}]}});
r({id: 'vhs_static_cut', label: 'VHS static cut', meaning: 'Analog signal breakup: tape, broadcast and surveillance eras, a feed cutting out.', intensity: 'bold', window: {before: 8, after: 10}, spec: {cut: {type: 'hard'}, layers: [overlay('crt', 0.8, 3, 4, greyFlash(), 'normal'), {kind: 'stutter', holdFrames: 3, attack: 5, release: 4}, {kind: 'flicker', amount: 1, attack: 5, release: 6}], sfx: [{cue: 'glitch_tick'}]}});
r({id: 'lens_flare_sweep', label: 'Lens flare sweep', meaning: 'Light sweeping across the lens: travel, nature, scale, a hopeful turn.', intensity: 'medium', window: {before: 16, after: 20}, spec: {cut: {type: 'hard'}, layers: [overlay('lens_flare', 0.9, 14, 18, leak('cool', 0.7)), {kind: 'flash', color: '#fff4e0', opacity: 0.25, attack: 4, release: 8, blend: 'screen'}]}});
r({id: 'archive_scratch_cut', label: 'Archive scratch cut', meaning: 'Entering damaged archival film: the past, rough and physical.', intensity: 'subtle', window: {before: 10, after: 18}, spec: {cut: {type: 'hard'}, layers: [{kind: 'overlay', select: {category: 'scratches', blend: 'screen'}, opacity: 1, attack: 8, release: 16}, {kind: 'flicker', amount: 0.8, attack: 6, release: 14}, {kind: 'desaturate', amount: 1, attack: 0, release: 16, side: 'in'}]}});
r({id: 'dust_drift_dissolve', label: 'Dust drift dissolve', meaning: 'Quiet time passing, dust in projector light; contemplative and restrained.', intensity: 'subtle', window: {before: 20, after: 22}, spec: {cut: {type: 'crossfade', frames: 22}, layers: [overlay('dust', 0.75, 18, 20)]}});
r({id: 'particle_shimmer_reveal', label: 'Particle shimmer reveal', meaning: 'Wonder, memory or a discovery glittering into view; use sparingly.', intensity: 'medium', window: {before: 16, after: 22}, spec: {cut: {type: 'crossfade', frames: 16}, layers: [overlay('particles', 0.9, 14, 20), {kind: 'flash', color: '#ffd9a8', opacity: 0.3, attack: 6, release: 10, blend: 'screen'}]}});
r({id: 'snowfall_passage', label: 'Snowfall passage', meaning: 'Winter, cold and stillness; only for stories that are actually set in snow.', intensity: 'subtle', window: {before: 24, after: 24}, spec: {cut: {type: 'crossfade', frames: 24}, layers: [overlay('weather', 0.8, 20, 24)]}});
r({id: 'projector_flicker_cut', label: 'Projector flicker cut', meaning: 'An old projector changing reels: archival chapter break.', intensity: 'medium', window: {before: 12, after: 14}, spec: {cut: {type: 'hard'}, layers: [{kind: 'dip', color: '#000', attack: 2, release: 2}, overlay('flicker', 0.6, 8, 10, whiteFlash(0.4, 2, 4), 'screen'), {kind: 'flicker', amount: 1, attack: 10, release: 12}]}});
r({id: 'leak_whip', label: 'Leak whip', meaning: 'Energetic warm move between places: travel montage, momentum with warmth.', intensity: 'bold', window: {before: 8, after: 12}, spec: {cut: {type: 'hard'}, layers: [{kind: 'whip_pan', direction: 'right', blurPx: 40, attack: 7, release: 9}, leak('warm', 0.7, 8, 12)], sfx: [{cue: 'whoosh', at: -5}]}});
r({id: 'film_damage_dip', label: 'Film damage dip', meaning: 'A worn reel fading out and back: archival time jump.', intensity: 'medium', window: {before: 18, after: 18}, spec: {cut: {type: 'hard'}, layers: [{kind: 'dip', color: '#000', attack: 14, release: 14, hold: 2}, overlay('scratches', 0.7, 16, 16)]}});
