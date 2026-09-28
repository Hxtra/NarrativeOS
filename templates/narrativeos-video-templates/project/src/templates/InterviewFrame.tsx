import React from 'react';
import {AbsoluteFill, Easing, Img, OffthreadVideo, interpolate, staticFile, useCurrentFrame} from 'remotion';
import type {StyleProfile} from '../styles/StyleProfile';
import {Grade, Vignette} from '../motion/FilmTexture';
import {containFit} from '../motion/mediaFit';
import {registerTemplate} from '../registry/registry';

export interface InterviewFrameParams {
	mediaSrc: string;
	mediaType: 'image' | 'video';
	/**
	 * The whole point of this template: real interview sources come from
	 * different cameras with different native aspect ratios. Rather than
	 * stretch or inconsistently crop each one, every source gets the same
	 * treatment — pillarboxed/letterboxed to fit 16:9 consistently, so a
	 * sequence of different interview subjects from different shoots
	 * still reads as one continuous visual language. Pass the source's
	 * real aspect ratio (width/height) so this can actually do that.
	 */
	sourceAspectRatio?: number;
}

const InterviewFrameComponent: React.FC<{style: StyleProfile; params: InterviewFrameParams}> = ({
	style,
	params,
}) => {
	const frame = useCurrentFrame();

	// A slight, slow "breathing" scale — nowhere near archival Ken Burns.
	// A completely static frame reads as dead; real interview footage
	// (even a locked-off camera) usually isn't perfectly still either.
	const breathe = interpolate(frame, [0, 150], [1.0, 1.025], {
		extrapolateRight: 'clamp',
		easing: Easing.inOut(Easing.sin),
	});

	const fadeIn = interpolate(frame, [0, 16], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});

	const targetAspect = 16 / 9;
	const sourceAspect = params.sourceAspectRatio ?? targetAspect;
	const fitStyle = containFit(sourceAspect, targetAspect);

	const mediaStyle: React.CSSProperties = {
		...fitStyle,
		transform: `scale(${breathe})`,
		filter: style.grade.filter,
		display: 'block',
		margin: 'auto',
	};

	return (
		<AbsoluteFill style={{backgroundColor: '#020203', opacity: fadeIn}}>
			<AbsoluteFill style={{justifyContent: 'center', alignItems: 'center', overflow: 'hidden'}}>
				{params.mediaType === 'video' ? (
					<OffthreadVideo src={staticFile(params.mediaSrc)} style={mediaStyle} />
				) : (
					<Img src={staticFile(params.mediaSrc)} style={mediaStyle} />
				)}
			</AbsoluteFill>
			<Grade style={style} />
			<Vignette style={style} />
			{/* A thin consistent frame line — the "set treatment" part: every
			    interview, regardless of source, gets the same subtle border. */}
			<AbsoluteFill
				style={{
					border: `1px solid ${style.typography.boneDimColor}`,
					opacity: 0.18,
					pointerEvents: 'none',
				}}
			/>
		</AbsoluteFill>
	);
};

registerTemplate<InterviewFrameParams>({
	id: 'interview_frame',
	label: 'Interview Frame / Set Treatment',
	pack: 'speaker',
	durationInFrames: () => 150,
	component: InterviewFrameComponent,
	defaultParams: {
		mediaSrc: 'media-library/nasa_eileen_collins_001.jpg',
		mediaType: 'image',
		sourceAspectRatio: 1, // the real asset is a 512x512 square — a genuine mismatch case
	},
});
