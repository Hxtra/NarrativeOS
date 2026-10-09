import React from 'react';
import {OffthreadVideo, staticFile} from 'remotion';
import {getStyle} from '../styles/StyleProfile';
import {TransitionStack} from './TransitionStack';
import {resolveTransition} from './transitionRegistry';
import './recipes';

export type TransitionSegmentProps = {
	transitionId: string;
	styleId: string;
	/** Paths under public/ (staged by the Python compiler): the two shots' pictures over the whole window. */
	outgoingSrc: string;
	incomingSrc: string;
	/** Frame of the window where A becomes B. */
	cutFrame: number;
	/** Seeds overlay selection and glitch randomness; stable per cut so re-renders match. */
	seed: string;
	durationInFrames: number;
	fps: number;
	width: number;
	height: number;
};

/**
 * One transition rendered for the multi-track compiler: real A and B footage (already fitted, moved and graded by
 * the compiler, so the look matches the rest of the cut) through a registered recipe. Vignette and grain are not
 * added here: whole-timeline finishing is the compiler's job, so the segment must not look different from its
 * neighbours.
 */
export const TransitionSegment: React.FC<TransitionSegmentProps> = ({transitionId, styleId, outgoingSrc, incomingSrc, cutFrame, seed}) => {
	const recipe = resolveTransition(transitionId);
	const style = getStyle(styleId);
	const shot = (src: string) => <OffthreadVideo src={staticFile(src)} muted style={{width: '100%', height: '100%', objectFit: 'cover'}} />;
	return (
		<TransitionStack spec={recipe.spec} cutFrame={cutFrame} seed={seed} style={style} outgoing={shot(outgoingSrc)} incoming={shot(incomingSrc)} />
	);
};
