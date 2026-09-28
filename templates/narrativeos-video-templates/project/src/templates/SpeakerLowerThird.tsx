import React from 'react';
import {AbsoluteFill, Easing, interpolate, useCurrentFrame} from 'remotion';
import type {StyleProfile} from '../styles/StyleProfile';
import {registerTemplate} from '../registry/registry';

export interface SpeakerLowerThirdParams {
	name: string;
	role?: string;
	/**
	 * True if this speaker has already been introduced earlier in the
	 * video. Real broadcast/documentary convention: a returning speaker
	 * gets a smaller, quicker callback tag — just the name, no role, no
	 * full build animation — not the same full introduction replayed.
	 * This is standard editorial practice, not a genre-specific guess.
	 */
	isReturning?: boolean;
}

const FirstAppearance: React.FC<{style: StyleProfile; params: SpeakerLowerThirdParams}> = ({
	style,
	params,
}) => {
	const frame = useCurrentFrame();

	const barWidth = interpolate(frame, [0, 20], [0, 420], {
		extrapolateLeft: 'clamp',
		extrapolateRight: 'clamp',
		easing: Easing.out(Easing.cubic),
	});
	const textOpacity = interpolate(frame, [8, 22], [0, 1], {
		extrapolateLeft: 'clamp',
		extrapolateRight: 'clamp',
	});
	const textX = interpolate(frame, [8, 26], [-14, 0], {
		extrapolateLeft: 'clamp',
		extrapolateRight: 'clamp',
		easing: Easing.out(Easing.cubic),
	});

	return (
		<div style={{position: 'absolute', left: 90, bottom: 110}}>
			<div
				style={{
					height: 4,
					width: barWidth,
					background: style.typography.boneColor,
					opacity: 0.9,
					marginBottom: 14,
				}}
			/>
			<div style={{opacity: textOpacity, transform: `translateX(${textX}px)`}}>
				<div
					style={{
						fontFamily: style.typography.serifFamily,
						fontWeight: style.typography.headlineWeight,
						fontSize: 44,
						color: style.typography.boneColor,
						textShadow: '0 4px 20px rgba(0,0,0,0.6)',
					}}
				>
					{params.name}
				</div>
				{params.role ? (
					<div
						style={{
							fontFamily: style.typography.sansFamily,
							fontSize: 22,
							letterSpacing: 1.5,
							textTransform: 'uppercase',
							color: style.typography.boneDimColor,
							marginTop: 4,
						}}
					>
						{params.role}
					</div>
				) : null}
			</div>
		</div>
	);
};

/**
 * Returning speaker: no bar-wipe build, no role line, just a small tag
 * that fades in quickly and sits higher/smaller than the full lower
 * third — genuinely different treatment, not a faster replay of the same
 * animation.
 */
const ReturningTag: React.FC<{style: StyleProfile; params: SpeakerLowerThirdParams}> = ({style, params}) => {
	const frame = useCurrentFrame();
	const opacity = interpolate(frame, [0, 10], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
	const y = interpolate(frame, [0, 12], [8, 0], {
		extrapolateLeft: 'clamp',
		extrapolateRight: 'clamp',
		easing: Easing.out(Easing.cubic),
	});

	return (
		<div
			style={{
				position: 'absolute',
				left: 90,
				bottom: 140,
				opacity,
				transform: `translateY(${y}px)`,
				display: 'flex',
				alignItems: 'center',
				gap: 12,
			}}
		>
			<div style={{width: 20, height: 2, background: style.typography.boneDimColor, opacity: 0.8}} />
			<div
				style={{
					fontFamily: style.typography.sansFamily,
					fontSize: 26,
					letterSpacing: 1,
					color: style.typography.boneColor,
					textShadow: '0 3px 14px rgba(0,0,0,0.55)',
				}}
			>
				{params.name}
			</div>
		</div>
	);
};

const SpeakerLowerThirdComponent: React.FC<{style: StyleProfile; params: SpeakerLowerThirdParams}> = ({
	style,
	params,
}) => (
	<AbsoluteFill>
		{params.isReturning ? (
			<ReturningTag style={style} params={params} />
		) : (
			<FirstAppearance style={style} params={params} />
		)}
	</AbsoluteFill>
);

registerTemplate<SpeakerLowerThirdParams>({
	id: 'speaker_lower_third',
	label: 'Lower Third — Speaker ID',
	pack: 'speaker',
	durationInFrames: () => 150, // 5s @ 30fps hold, trimmed by the timeline in real use
	component: SpeakerLowerThirdComponent,
	defaultParams: {
		name: 'Placeholder Name',
		role: 'Placeholder Role, Placeholder Org',
		isReturning: false,
	},
});
