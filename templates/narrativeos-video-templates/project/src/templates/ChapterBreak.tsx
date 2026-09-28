import React from 'react';
import {AbsoluteFill, useCurrentFrame} from 'remotion';
import type {StyleProfile} from '../styles/StyleProfile';
import {useOrganicWeave} from '../motion/organicMotion';
import {Grain, Grade, Vignette} from '../motion/FilmTexture';
import {SplitText, Rule} from '../typography/Typography';
import {registerTemplate} from '../registry/registry';

export interface ChapterBreakParams {
	/** e.g. "CHAPTER TWO" */
	eyebrow: string;
	title: string;
}

const ChapterBreakComponent: React.FC<{style: StyleProfile; params: ChapterBreakParams}> = ({
	style,
	params,
}) => {
	const frame = useCurrentFrame();
	const weaveStyle = useOrganicWeave(style.motion);

	// eyebrow number/word appears first, small and high; title rises under it.
	// A horizontal rule splits them — this is a RESET/BUILD beat per
	// editing-brain.md, so the motion is deliberately slower and heavier
	// than the title card's, not a re-skin of the same timing.
	const ruleWidth = 640;

	return (
		<AbsoluteFill style={{backgroundColor: '#050408'}}>
			<AbsoluteFill style={weaveStyle}>
				<AbsoluteFill style={{filter: style.grade.filter, background: '#15111c'}} />
			</AbsoluteFill>
			<Grade style={style} />
			<Vignette style={style} />
			<AbsoluteFill
				style={{
					justifyContent: 'center',
					alignItems: 'center',
					textAlign: 'center',
					gap: 30,
				}}
			>
				<div
					style={{
						fontFamily: style.typography.sansFamily,
						fontWeight: 600,
						fontSize: 30,
						letterSpacing: style.typography.kickerLetterSpacing + 2,
						textTransform: 'uppercase',
						color: style.typography.boneDimColor,
					}}
				>
					<SplitText text={params.eyebrow} style={style} delay={4} rise={20} />
				</div>
				<Rule style={style} delay={22} width={ruleWidth} thickness={1.5} />
				<div
					style={{
						fontFamily: style.typography.serifFamily,
						fontWeight: style.typography.headlineWeight,
						fontSize: 78,
						letterSpacing: 3,
						color: style.typography.boneColor,
						textShadow: '0 10px 46px rgba(0,0,0,0.6)',
						maxWidth: 1400,
					}}
				>
					<SplitText text={params.title} style={style} delay={34} rise={36} />
				</div>
			</AbsoluteFill>
			<Grain style={style} />
			<AbsoluteFill style={{opacity: frame < 1 ? 0 : undefined}} />
		</AbsoluteFill>
	);
};

registerTemplate<ChapterBreakParams>({
	id: 'chapter_break',
	label: 'Chapter / Section Break',
	pack: 'core',
	durationInFrames: () => 120, // 4s @ 30fps — a beat, not a scene
	component: ChapterBreakComponent,
	defaultParams: {
		eyebrow: 'Chapter Two',
		title: 'PLACEHOLDER SECTION TITLE',
	},
});
