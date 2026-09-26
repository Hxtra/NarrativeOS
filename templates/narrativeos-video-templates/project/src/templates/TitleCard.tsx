import React from 'react';
import {AbsoluteFill, useCurrentFrame} from 'remotion';
import type {StyleProfile} from '../styles/StyleProfile';
import {useOrganicWeave} from '../motion/organicMotion';
import {Grain, Grade, Vignette} from '../motion/FilmTexture';
import {SplitText, Kicker, Rule, Caption} from '../typography/Typography';
import {registerTemplate} from '../registry/registry';

export interface TitleCardParams {
	kicker?: string;
	headline: string;
	sub?: string;
}

const Corner: React.FC<{pos: 'tl' | 'tr' | 'bl' | 'br'}> = ({pos}) => {
	const base: React.CSSProperties = {
		position: 'absolute',
		width: 44,
		height: 44,
		borderColor: 'rgba(240,234,224,0.34)',
		borderStyle: 'solid',
		borderWidth: 0,
	};
	const map: Record<string, React.CSSProperties> = {
		tl: {left: 56, top: 56, borderLeftWidth: 2, borderTopWidth: 2},
		tr: {right: 56, top: 56, borderRightWidth: 2, borderTopWidth: 2},
		bl: {left: 56, bottom: 56, borderLeftWidth: 2, borderBottomWidth: 2},
		br: {right: 56, bottom: 56, borderRightWidth: 2, borderBottomWidth: 2},
	};
	return <div style={{...base, ...map[pos]}} />;
};

/**
 * Layout 1: centered-classic. Symmetric, centered, corner brackets.
 * This is the original, only layout that existed before per-style
 * structural branching — kept as the default for any style that doesn't
 * specify a title_card layout.
 */
const CenteredClassic: React.FC<{style: StyleProfile; params: TitleCardParams}> = ({style, params}) => (
	<AbsoluteFill style={{justifyContent: 'center', alignItems: 'center', textAlign: 'center', gap: 38}}>
		<Corner pos="tl" />
		<Corner pos="tr" />
		<Corner pos="bl" />
		<Corner pos="br" />
		{params.kicker ? <Kicker text={params.kicker} style={style} delay={8} /> : null}
		<div
			style={{
				fontFamily: style.typography.serifFamily,
				fontWeight: style.typography.headlineWeight,
				fontSize: 96,
				letterSpacing: 6,
				color: style.typography.boneColor,
				lineHeight: 1.05,
				textShadow: '0 10px 46px rgba(0,0,0,0.6)',
			}}
		>
			<SplitText text={params.headline} style={style} delay={16} rise={46} />
		</div>
		<div style={{display: 'flex', justifyContent: 'center', width: '100%'}}>
			<Rule style={style} delay={40} width={420} />
		</div>
		{params.sub ? <Caption text={params.sub} style={style} delay={52} align="center" /> : null}
	</AbsoluteFill>
);

/**
 * Layout 2: corner-frame-broadcast. Asymmetric, headline anchored
 * bottom-left, kicker as a small top-right tag, vertical accent rule
 * instead of a horizontal one under center. Structural basis: standard
 * broadcast-graphic convention (network opens, corner "bugs", lower-third-
 * anchored titles) — not a guess at a specific documentary genre's look.
 */
const CornerFrameBroadcast: React.FC<{style: StyleProfile; params: TitleCardParams}> = ({style, params}) => (
	<AbsoluteFill style={{justifyContent: 'flex-end', alignItems: 'flex-start', padding: 90}}>
		{params.kicker ? (
			<div style={{position: 'absolute', top: 90, right: 90, textAlign: 'right'}}>
				<Kicker text={params.kicker} style={style} delay={6} />
			</div>
		) : null}
		<div style={{display: 'flex', flexDirection: 'row', alignItems: 'stretch', gap: 28, maxWidth: 1500}}>
			<div style={{width: 3, background: style.typography.boneColor, opacity: 0.7}}>
				{/* vertical accent rule takes the place of the centered layout's
				    horizontal rule — grows on its own timing via a plain CSS
				    transition-free height reveal driven by the same frame clock */}
				<VerticalRule style={style} delay={14} />
			</div>
			<div>
				<div
					style={{
						fontFamily: style.typography.serifFamily,
						fontWeight: style.typography.headlineWeight,
						fontSize: 84,
						letterSpacing: 2,
						color: style.typography.boneColor,
						lineHeight: 1.05,
						textShadow: '0 8px 36px rgba(0,0,0,0.55)',
						textAlign: 'left',
					}}
				>
					<SplitText text={params.headline} style={style} delay={22} rise={34} />
				</div>
				{params.sub ? (
					<div style={{marginTop: 18}}>
						<Caption text={params.sub} style={style} delay={48} align="left" />
					</div>
				) : null}
			</div>
		</div>
	</AbsoluteFill>
);

const VerticalRule: React.FC<{style: StyleProfile; delay: number}> = ({delay}) => {
	const frame = useCurrentFrame();
	const h = Math.max(0, Math.min(1, (frame - delay) / 26)) * 100;
	return <div style={{width: '100%', height: `${h}%`}} />;
};

const LAYOUTS: Record<string, React.FC<{style: StyleProfile; params: TitleCardParams}>> = {
	'centered-classic': CenteredClassic,
	'corner-frame-broadcast': CornerFrameBroadcast,
};

const TitleCardComponent: React.FC<{style: StyleProfile; params: TitleCardParams}> = ({style, params}) => {
	const frame = useCurrentFrame();
	const weaveStyle = useOrganicWeave({...style.motion, weaveAmount: style.motion.weaveAmount * 1.4});
	const layoutKey = style.layouts?.title_card ?? 'centered-classic';
	const Layout = LAYOUTS[layoutKey] ?? CenteredClassic;

	return (
		<AbsoluteFill style={{backgroundColor: '#07060a'}}>
			<AbsoluteFill style={weaveStyle}>
				<AbsoluteFill style={{filter: style.grade.filter, background: '#221c2e'}} />
			</AbsoluteFill>
			<Grade style={style} />
			<Vignette style={style} />
			<Layout style={style} params={params} />
			<Grain style={style} />
			<AbsoluteFill style={{opacity: frame < 3 ? 0 : undefined}} />
		</AbsoluteFill>
	);
};

registerTemplate<TitleCardParams>({
	id: 'title_card',
	label: 'Main Title / Show Open',
	pack: 'core',
	durationInFrames: () => 168,
	component: TitleCardComponent,
	defaultParams: {
		kicker: 'Archive Reel No. 01',
		headline: 'PLACEHOLDER HEADLINE',
		sub: '',
	},
});
