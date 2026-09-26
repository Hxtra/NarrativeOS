import React from 'react';
import {Easing, interpolate, useCurrentFrame} from 'remotion';
import type {StyleProfile} from '../styles/StyleProfile';

export const SplitText: React.FC<{
	text: string;
	style: StyleProfile;
	delay?: number;
	rise?: number;
	css?: React.CSSProperties;
	outDelay?: number;
}> = ({text, style, delay = 0, rise = 34, css, outDelay}) => {
	const frame = useCurrentFrame();
	const stagger = style.motion.titleStaggerFrames;
	return (
		<span style={{display: 'inline-block', whiteSpace: 'pre-wrap', ...css}}>
			{text.split('').map((ch, i) => {
				const t = frame - delay - i * stagger;
				const o = interpolate(t, [0, 14], [0, 1], {
					extrapolateLeft: 'clamp',
					extrapolateRight: 'clamp',
					easing: Easing.out(Easing.cubic),
				});
				const y = interpolate(t, [0, 18], [rise, 0], {
					extrapolateLeft: 'clamp',
					extrapolateRight: 'clamp',
					easing: Easing.bezier(0.16, 1, 0.3, 1),
				});
				const out =
					outDelay === undefined
						? 1
						: interpolate(frame - outDelay - i * 0.8, [0, 12], [1, 0], {
								extrapolateLeft: 'clamp',
								extrapolateRight: 'clamp',
							});
				return (
					<span
						key={i}
						style={{
							display: 'inline-block',
							opacity: o * out,
							transform: `translateY(${y}px)`,
							whiteSpace: 'pre',
						}}
					>
						{ch === ' ' ? '\u00A0' : ch}
					</span>
				);
			})}
		</span>
	);
};

export const Rule: React.FC<{style: StyleProfile; delay?: number; width: number; thickness?: number}> = ({
	style,
	delay = 0,
	width,
	thickness = 2,
}) => {
	const frame = useCurrentFrame();
	const w = interpolate(frame - delay, [0, 26], [0, width], {
		extrapolateLeft: 'clamp',
		extrapolateRight: 'clamp',
		easing: Easing.bezier(0.22, 1, 0.36, 1),
	});
	return <div style={{width: w, height: thickness, background: style.typography.boneColor, opacity: 0.85}} />;
};

export const Kicker: React.FC<{text: string; style: StyleProfile; delay?: number}> = ({
	text,
	style,
	delay = 0,
}) => {
	const frame = useCurrentFrame();
	const o = interpolate(frame - delay, [0, 16], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
	const x = interpolate(frame - delay, [0, 24], [-18, 0], {
		extrapolateLeft: 'clamp',
		extrapolateRight: 'clamp',
		easing: Easing.out(Easing.cubic),
	});
	return (
		<div
			style={{
				fontFamily: style.typography.sansFamily,
				fontWeight: 600,
				fontSize: 26,
				letterSpacing: style.typography.kickerLetterSpacing,
				textTransform: 'uppercase',
				color: style.typography.boneDimColor,
				opacity: o,
				transform: `translateX(${x}px)`,
			}}
		>
			{text}
		</div>
	);
};

export const Caption: React.FC<{text: string; style: StyleProfile; delay?: number; align?: 'left' | 'center'}> = ({
	text,
	style,
	delay = 0,
	align = 'left',
}) => {
	const frame = useCurrentFrame();
	const o = interpolate(frame - delay, [0, 18], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
	const y = interpolate(frame - delay, [0, 22], [14, 0], {
		extrapolateLeft: 'clamp',
		extrapolateRight: 'clamp',
		easing: Easing.out(Easing.cubic),
	});
	return (
		<div
			style={{
				fontFamily: style.typography.sansFamily,
				fontSize: 30,
				letterSpacing: 1.6,
				color: style.typography.boneDimColor,
				opacity: o * 0.92,
				transform: `translateY(${y}px)`,
				textAlign: align,
				maxWidth: 820,
			}}
		>
			{text}
		</div>
	);
};
