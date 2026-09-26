import React from 'react';
import {AbsoluteFill, Img, staticFile, useCurrentFrame} from 'remotion';
import {getStyle, type StyleProfile} from '../styles/StyleProfile';
import {Grade, Grain, Vignette} from '../motion/FilmTexture';
import {TransitionStack, type TransitionSpec} from './TransitionStack';
import {resolveTransition, type TransitionRecipe} from './transitionRegistry';
import './recipes';

/** Frames of plain shot either side of a recipe's window in its proof. */
export const PROOF_PAD = 12;

export const proofTiming = (recipe: TransitionRecipe) => ({
	cutFrame: PROOF_PAD + recipe.window.before,
	durationInFrames: PROOF_PAD * 2 + recipe.window.before + recipe.window.after,
});

/** A shot with the style's grade (filter + shadow/highlight wash) applied to it alone. */
const Still: React.FC<{src: string; drift: number; style: StyleProfile}> = ({src, drift, style}) => {
	const frame = useCurrentFrame();
	return (
		<AbsoluteFill style={{overflow: 'hidden'}}>
			<AbsoluteFill style={{filter: style.grade.filter}}>
				<Img
					src={staticFile(src)}
					style={{width: '100%', height: '100%', objectFit: 'cover', transform: `scale(${(1.04 + frame * drift).toFixed(4)})`}}
				/>
			</AbsoluteFill>
			<Grade style={style} />
		</AbsoluteFill>
	);
};

/**
 * Proof for one recipe: two real Media Library stills (NASA, public domain)
 * cut together through the recipe, under the style's grade. With no VFX
 * library linked, overlay layers render their procedural fallbacks.
 */
export const TransitionProof: React.FC<{
	transitionId: string;
	styleId: string;
	showLabel?: boolean;
	/**
	 * QA mode for scripts/verify_peak_alignment.mjs: only the recipe's footage
	 * overlays, on black, at constant opacity (no envelope), so frame
	 * brightness follows the clip itself and its peak should sit on the cut.
	 */
	isolateOverlays?: boolean;
	/** With isolateOverlays: force one library asset id. */
	pinAssetId?: string;
	/** Informational only: where the cut falls, exposed for the QA scripts. The component derives it itself. */
	cutFrame?: number;
}> = ({transitionId, styleId, showLabel = true, isolateOverlays = false, pinAssetId}) => {
	const recipe = resolveTransition(transitionId);
	const style = getStyle(styleId);
	const frame = useCurrentFrame();
	const {cutFrame} = proofTiming(recipe);
	if (isolateOverlays) {
		const spec: TransitionSpec = {
			cut: {type: 'hard'},
			layers: recipe.spec.layers
				.filter((l) => l.kind === 'overlay')
				.map((l) => (l.kind === 'overlay' ? {...l, fallback: undefined, attack: 1e6, release: 1e6, select: pinAssetId ? {...l.select, assetId: pinAssetId} : l.select} : l)),
		};
		const black = <AbsoluteFill style={{backgroundColor: '#000'}} />;
		return <TransitionStack spec={spec} cutFrame={cutFrame} seed={recipe.id} style={style} outgoing={black} incoming={black} />;
	}
	return (
		<AbsoluteFill style={{backgroundColor: '#000'}}>
			{/* Grade the shots, not the stack: leaks, burns and RGB fringes sit above the grade, as in an editor. */}
			<AbsoluteFill>
				<TransitionStack
					spec={recipe.spec}
					cutFrame={cutFrame}
					seed={recipe.id}
					style={style}
					outgoing={<Still src="media-library/nasa_eileen_collins_001.jpg" drift={0.0006} style={style} />}
					incoming={<Still src="media-library/nasa_hubble_deep_field_001.jpg" drift={0.0004} style={style} />}
				/>
			</AbsoluteFill>
			{/* Lens and film sit over everything; the grade lives on the shots (see Still). */}
			<Vignette style={style} />
			<Grain style={style} />
			{showLabel ? (
				<div style={{position: 'absolute', left: 40, bottom: 32, fontFamily: 'monospace', fontSize: 26, color: 'rgba(255,255,255,0.85)', textShadow: '0 2px 6px #000'}}>
					{recipe.id} · {styleId} · cut {frame - cutFrame >= 0 ? '+' : ''}
					{frame - cutFrame}
				</div>
			) : null}
		</AbsoluteFill>
	);
};
