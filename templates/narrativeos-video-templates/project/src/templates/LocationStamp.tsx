import React from 'react';
import {AbsoluteFill, Easing, interpolate, useCurrentFrame} from 'remotion';
import type {StyleProfile} from '../styles/StyleProfile';
import {registerTemplate} from '../registry/registry';

export interface LocationStampParams {
	location?: string;
	date?: string;
}

/**
 * Deliberately NOT bottom-left like speaker_lower_third — top-left is
 * standard broadcast convention for a location/date super specifically so
 * it can coexist on screen with a speaker ID without overlapping or being
 * confused for the same kind of information. Smaller type scale too: this
 * is a secondary context cue, not the primary on-screen identity.
 */
const LocationStampComponent: React.FC<{style: StyleProfile; params: LocationStampParams}> = ({
	style,
	params,
}) => {
	const frame = useCurrentFrame();
	const opacity = interpolate(frame, [0, 14], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
	const x = interpolate(frame, [0, 18], [-10, 0], {
		extrapolateLeft: 'clamp',
		extrapolateRight: 'clamp',
		easing: Easing.out(Easing.cubic),
	});

	if (!params.location && !params.date) return null;

	return (
		<AbsoluteFill>
			<div
				style={{
					position: 'absolute',
					left: 90,
					top: 90,
					opacity,
					transform: `translateX(${x}px)`,
					display: 'flex',
					flexDirection: 'column',
					gap: 2,
				}}
			>
				{params.location ? (
					<div
						style={{
							fontFamily: style.typography.sansFamily,
							fontWeight: 600,
							fontSize: 24,
							letterSpacing: 2,
							textTransform: 'uppercase',
							color: style.typography.boneColor,
							textShadow: '0 3px 14px rgba(0,0,0,0.6)',
						}}
					>
						{params.location}
					</div>
				) : null}
				{params.date ? (
					<div
						style={{
							fontFamily: style.typography.sansFamily,
							fontSize: 19,
							letterSpacing: 1.5,
							color: style.typography.boneDimColor,
							textShadow: '0 2px 10px rgba(0,0,0,0.55)',
						}}
					>
						{params.date}
					</div>
				) : null}
			</div>
		</AbsoluteFill>
	);
};

registerTemplate<LocationStampParams>({
	id: 'location_stamp',
	label: 'Location / Date Stamp',
	pack: 'speaker',
	durationInFrames: () => 150,
	component: LocationStampComponent,
	defaultParams: {
		location: 'Placeholder City, Country',
		date: 'Placeholder Month Year',
	},
});
