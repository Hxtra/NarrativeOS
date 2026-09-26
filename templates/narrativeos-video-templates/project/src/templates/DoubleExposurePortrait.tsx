import React from 'react';
import {AbsoluteFill, Img, OffthreadVideo, interpolate, staticFile, useCurrentFrame} from 'remotion';
import type {StyleProfile} from '../styles/StyleProfile';
import {Grade, Vignette, Grain} from '../motion/FilmTexture';
import {containFit} from '../motion/mediaFit';
import {useKenBurns, DEFAULT_KEN_BURNS, type KenBurnsSpec} from '../motion/kenBurns';
import {useDoubleExposure, DEFAULT_DOUBLE_EXPOSURE, type DoubleExposureSpec} from '../motion/doubleExposure';
import {type ArchiveAttribution, formatAttribution} from '../motion/attribution';
import {Kicker, Caption} from '../typography/Typography';
import {registerTemplate} from '../registry/registry';

export interface DoubleExposurePortraitParams {
	primaryMediaSrc: string;
	primaryMediaType: 'image' | 'video';
	primaryAspectRatio?: number;
	secondaryMediaSrc: string;
	secondaryMediaType: 'image' | 'video';
	secondaryAspectRatio?: number;
	doubleExposure?: DoubleExposureSpec;
	kenBurns?: KenBurnsSpec;
	kicker?: string;
	caption?: string;
	/** Independent attribution per source — this is exactly why
	 * ArchiveAttribution was extracted to be shared rather than owned by
	 * ArchiveVideo: this component needs it twice, for two different
	 * real Media Library records. */
	primaryAttribution?: ArchiveAttribution;
	secondaryAttribution?: ArchiveAttribution;
}

const DURATION = 180;

const DoubleExposurePortraitComponent: React.FC<{style: StyleProfile; params: DoubleExposurePortraitParams}> = ({
	style,
	params,
}) => {
	const frame = useCurrentFrame();
	const primaryFit = containFit(params.primaryAspectRatio ?? 16 / 9, 16 / 9);
	const secondaryFit = containFit(params.secondaryAspectRatio ?? 16 / 9, 16 / 9);
	const kb = useKenBurns(params.kenBurns ?? DEFAULT_KEN_BURNS, DURATION, style.motion.kenBurnsEase);
	const de = useDoubleExposure(params.doubleExposure ?? DEFAULT_DOUBLE_EXPOSURE, DURATION);

	const fadeIn = interpolate(frame, [0, 16], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});

	const primaryStyle: React.CSSProperties = {
		...primaryFit,
		transform: kb.transform,
		filter: style.grade.filter,
		display: 'block',
		margin: 'auto',
	};

	const secondaryStyle: React.CSSProperties = {
		...secondaryFit,
		...de.overlayStyle,
		...de.maskStyle,
		filter: `${style.grade.filter} blur(6px)`,
		display: 'block',
		margin: 'auto',
	};

	const primaryLine = formatAttribution(params.primaryAttribution);
	const secondaryLine = formatAttribution(params.secondaryAttribution);

	return (
		<AbsoluteFill style={{backgroundColor: '#050408', opacity: fadeIn, overflow: 'hidden'}}>
			{/* primary portrait */}
			<AbsoluteFill style={{justifyContent: 'center', alignItems: 'center', overflow: 'hidden'}}>
				{params.primaryMediaType === 'video' ? (
					<OffthreadVideo src={staticFile(params.primaryMediaSrc)} style={primaryStyle} />
				) : (
					<Img src={staticFile(params.primaryMediaSrc)} style={primaryStyle} />
				)}
			</AbsoluteFill>

			{/* secondary contextual image, double-exposed via the primitive */}
			<AbsoluteFill style={{justifyContent: 'center', alignItems: 'center', overflow: 'hidden', position: 'absolute', inset: 0}}>
				{params.secondaryMediaType === 'video' ? (
					<OffthreadVideo src={staticFile(params.secondaryMediaSrc)} style={secondaryStyle} />
				) : (
					<Img src={staticFile(params.secondaryMediaSrc)} style={secondaryStyle} />
				)}
			</AbsoluteFill>

			<Grade style={style} />
			<Vignette style={style} />
			<Grain style={style} />

			<AbsoluteFill
				style={{justifyContent: 'flex-end', alignItems: 'flex-start', paddingLeft: 120, paddingBottom: 130, gap: 22}}
			>
				{params.kicker ? <Kicker text={params.kicker} style={style} delay={10} /> : null}
				{params.caption ? <Caption text={params.caption} style={style} delay={22} /> : null}
			</AbsoluteFill>

			{primaryLine || secondaryLine ? (
				<div
					style={{
						position: 'absolute',
						right: 36,
						bottom: 28,
						textAlign: 'right',
						fontFamily: style.typography.sansFamily,
						fontSize: 15,
						letterSpacing: 0.5,
						color: style.typography.boneDimColor,
						textShadow: '0 2px 8px rgba(0,0,0,0.7)',
						opacity: 0.75,
						lineHeight: 1.5,
					}}
				>
					{primaryLine ? <div>Primary: {primaryLine}</div> : null}
					{secondaryLine ? <div>Secondary: {secondaryLine}</div> : null}
				</div>
			) : null}
		</AbsoluteFill>
	);
};

registerTemplate<DoubleExposurePortraitParams>({
	id: 'double_exposure_portrait',
	label: 'Double Exposure Portrait (primary + secondary contextual media)',
	pack: 'archive',
	durationInFrames: () => DURATION,
	component: DoubleExposurePortraitComponent,
	defaultParams: {
		primaryMediaSrc: 'media-library/nasa_eileen_collins_001.jpg',
		primaryMediaType: 'image',
		primaryAspectRatio: 1,
		secondaryMediaSrc: 'media-library/nasa_hubble_deep_field_001.jpg',
		secondaryMediaType: 'image',
		secondaryAspectRatio: 1.147,
		kicker: 'Plate 04 · Portrait',
	},
});
