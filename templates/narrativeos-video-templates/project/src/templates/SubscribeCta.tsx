import React from 'react';
import {AbsoluteFill, Easing, interpolate, useCurrentFrame} from 'remotion';
import type {StyleProfile} from '../styles/StyleProfile';
import {useOrganicWeave} from '../motion/organicMotion';
import {Grain, Grade, Vignette} from '../motion/FilmTexture';
import {SplitText, Caption} from '../typography/Typography';
import {registerTemplate} from '../registry/registry';

export interface SubscribeCtaParams {
	channelName: string;
	ctaLine?: string; // e.g. "New documentaries every Thursday"
}

const SubscribeCtaComponent: React.FC<{style: StyleProfile; params: SubscribeCtaParams}> = ({
	style,
	params,
}) => {
	const frame = useCurrentFrame();
	const weaveStyle = useOrganicWeave({...style.motion, weaveAmount: style.motion.weaveAmount * 0.5});

	// A simple pulsing ring behind a subscribe glyph — deterministic, no
	// external icon asset required, keeps this template self-contained.
	const pulse = interpolate(frame % 60, [0, 30, 60], [0.75, 1.08, 0.75], {
		easing: Easing.inOut(Easing.sin),
	});
	const ringOpacity = interpolate(frame, [0, 20], [0, 0.9], {
		extrapolateLeft: 'clamp',
		extrapolateRight: 'clamp',
	});

	return (
		<AbsoluteFill style={{backgroundColor: '#07060a'}}>
			<AbsoluteFill style={weaveStyle}>
				<AbsoluteFill style={{filter: style.grade.filter, background: '#1b1624'}} />
			</AbsoluteFill>
			<Grade style={style} />
			<Vignette style={style} />
			<AbsoluteFill style={{justifyContent: 'center', alignItems: 'center', gap: 34}}>
				<div
					style={{
						width: 140,
						height: 140,
						borderRadius: '50%',
						border: `2px solid ${style.typography.boneColor}`,
						opacity: ringOpacity,
						transform: `scale(${pulse})`,
					}}
				/>
				<div
					style={{
						fontFamily: style.typography.serifFamily,
						fontWeight: style.typography.headlineWeight,
						fontSize: 64,
						letterSpacing: 3,
						color: style.typography.boneColor,
						textAlign: 'center',
					}}
				>
					<SplitText text={params.channelName} style={style} delay={14} rise={30} />
				</div>
				{params.ctaLine ? <Caption text={params.ctaLine} style={style} delay={40} align="center" /> : null}
			</AbsoluteFill>
			<Grain style={style} />
		</AbsoluteFill>
	);
};

registerTemplate<SubscribeCtaParams>({
	id: 'subscribe_cta',
	label: 'Subscribe / CTA End Card',
	pack: 'core',
	durationInFrames: () => 150, // 5s @ 30fps
	component: SubscribeCtaComponent,
	defaultParams: {
		channelName: 'PLACEHOLDER CHANNEL',
		ctaLine: 'New documentaries every week',
	},
});
