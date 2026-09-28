import React from 'react';
import {AbsoluteFill, random, staticFile, useCurrentFrame} from 'remotion';
import type {StyleProfile} from '../styles/StyleProfile';

export const Grain: React.FC<{style: StyleProfile}> = ({style}) => {
	const frame = useCurrentFrame();
	const tile = frame % 8;
	const ox = Math.floor(random(`gx${frame}`) * 512);
	const oy = Math.floor(random(`gy${frame}`) * 512);
	return (
		<AbsoluteFill
			style={{
				backgroundImage: `url(${staticFile(`grain/grain${tile}.png`)})`,
				backgroundSize: '512px 512px',
				backgroundPosition: `${ox}px ${oy}px`,
				mixBlendMode: 'overlay',
				opacity: style.grainOpacity,
				pointerEvents: 'none',
			}}
		/>
	);
};

export const Vignette: React.FC<{style: StyleProfile}> = ({style}) => {
	const s = style.vignetteStrength;
	return (
		<>
			<AbsoluteFill
				style={{
					background: `radial-gradient(ellipse 72% 68% at 50% 48%, rgba(0,0,0,0) 45%, rgba(0,0,0,${0.55 * s}) 78%, rgba(0,0,0,${0.88 * s}) 100%)`,
					pointerEvents: 'none',
				}}
			/>
			<AbsoluteFill
				style={{
					background:
						'linear-gradient(to bottom, rgba(0,0,0,0.42) 0%, rgba(0,0,0,0) 22%, rgba(0,0,0,0) 74%, rgba(0,0,0,0.55) 100%)',
					pointerEvents: 'none',
				}}
			/>
		</>
	);
};

export const Grade: React.FC<{style: StyleProfile}> = ({style}) => (
	<>
		<AbsoluteFill style={{background: style.grade.shadow, mixBlendMode: 'color', pointerEvents: 'none'}} />
		<AbsoluteFill
			style={{background: style.grade.highlight, mixBlendMode: 'soft-light', pointerEvents: 'none'}}
		/>
	</>
);
