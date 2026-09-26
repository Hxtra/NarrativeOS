import React from 'react';
import {AbsoluteFill, interpolate, useCurrentFrame} from 'remotion';
import type {StyleProfile} from '../styles/StyleProfile';
import {Grain, Grade, Vignette} from '../motion/FilmTexture';
import {Rule} from '../typography/Typography';
import {registerTemplate} from '../registry/registry';

export interface CreditsRollParams {
	title: string; // e.g. "DOCUMENTARY SLIDESHOW"
	rows: {role: string; name: string}[];
	/** How many pixels of scroll per second — tune to how many rows exist */
	scrollSpeedPxPerSec?: number;
}

const ROW_HEIGHT = 64;

const CreditsRollComponent: React.FC<{style: StyleProfile; params: CreditsRollParams}> = ({
	style,
	params,
}) => {
	const frame = useCurrentFrame();
	const fps = 30;
	const speed = params.scrollSpeedPxPerSec ?? 90;
	const scrollY = (frame / fps) * speed;

	const fadeIn = interpolate(frame, [0, 20], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});

	return (
		<AbsoluteFill style={{backgroundColor: '#050408'}}>
			<AbsoluteFill style={{filter: style.grade.filter, background: '#15111c'}} />
			<Grade style={style} />
			<Vignette style={style} />
			<AbsoluteFill style={{opacity: fadeIn, overflow: 'hidden'}}>
				<div
					style={{
						position: 'absolute',
						left: '50%',
						top: `calc(100% - ${scrollY}px)`,
						transform: 'translateX(-50%)',
						width: 900,
						textAlign: 'center',
					}}
				>
					<div
						style={{
							fontFamily: style.typography.serifFamily,
							fontWeight: style.typography.headlineWeight,
							fontSize: 56,
							letterSpacing: 4,
							color: style.typography.boneColor,
							marginBottom: 30,
						}}
					>
						{params.title}
					</div>
					<div style={{display: 'flex', justifyContent: 'center', marginBottom: 50}}>
						<Rule style={style} delay={0} width={200} />
					</div>
					{params.rows.map((row, i) => (
						<div
							key={i}
							style={{
								height: ROW_HEIGHT,
								display: 'flex',
								justifyContent: 'space-between',
								fontFamily: style.typography.sansFamily,
								fontSize: 26,
								color: style.typography.boneDimColor,
								borderBottom: '1px solid rgba(240,234,224,0.08)',
								padding: '0 8px',
								alignItems: 'center',
							}}
						>
							<span style={{letterSpacing: 2, textTransform: 'uppercase', opacity: 0.65}}>
								{row.role}
							</span>
							<span style={{color: style.typography.boneColor}}>{row.name}</span>
						</div>
					))}
				</div>
			</AbsoluteFill>
			{/* vignette edges hide the scroll clip boundary so rows don't hard-cut in/out */}
			<AbsoluteFill
				style={{
					background:
						'linear-gradient(to bottom, #050408 0%, rgba(5,4,8,0) 12%, rgba(5,4,8,0) 88%, #050408 100%)',
					pointerEvents: 'none',
				}}
			/>
			<Grain style={style} />
		</AbsoluteFill>
	);
};

registerTemplate<CreditsRollParams>({
	id: 'credits_roll',
	label: 'Credits / Outro Roll',
	pack: 'core',
	durationInFrames: (params) => {
		// enough time for every row to scroll fully through, plus lead-in/out
		const rows = params.rows?.length ?? 6;
		const speed = params.scrollSpeedPxPerSec ?? 90;
		const contentHeight = 300 + rows * ROW_HEIGHT;
		const scrollSeconds = contentHeight / speed + 3;
		return Math.round(scrollSeconds * 30);
	},
	component: CreditsRollComponent,
	defaultParams: {
		title: 'PLACEHOLDER SHOW TITLE',
		rows: [
			{role: 'Narration', name: 'Placeholder Name'},
			{role: 'Research', name: 'Placeholder Name'},
			{role: 'Editing', name: 'NarrativeOS'},
		],
		scrollSpeedPxPerSec: 90,
	},
});
