import React from 'react';
import {AbsoluteFill, Img, Loop, OffthreadVideo, interpolate, staticFile, useCurrentFrame} from 'remotion';
import type {StyleProfile} from '../styles/StyleProfile';
import {Grade, Vignette} from '../motion/FilmTexture';
import {Kicker, Caption} from '../typography/Typography';
import {registerTemplate} from '../registry/registry';
import {useKenBurns, DEFAULT_KEN_BURNS, type KenBurnsSpec} from '../motion/kenBurns';

export interface MediaRevealParams {
	/** The actual media slot — this is what gets swapped per shot. Path relative to /public. */
	mediaSrc: string;
	mediaType: 'image' | 'video';
	kenBurns?: KenBurnsSpec;
	kicker?: string;
	caption?: string;
	/**
	 * Path to a licensed light-leak overlay clip, relative to /public.
	 * Documented convention: drop your own licensed asset at
	 * public/licensed/<pack-name>/Leak.mov and pass that path here.
	 * This template does not ship the overlay itself.
	 */
	leakOverlaySrc?: string;
	/** Same convention, for a grain/noise overlay clip instead of procedural grain. */
	noiseOverlaySrc?: string;
}

const MediaRevealComponent: React.FC<{style: StyleProfile; params: MediaRevealParams}> = ({
	style,
	params,
}) => {
	const frame = useCurrentFrame();
	const kb = useKenBurns(params.kenBurns ?? DEFAULT_KEN_BURNS, 180, style.motion.kenBurnsEase);

	const mediaStyle: React.CSSProperties = {
		width: '100%',
		height: '100%',
		objectFit: 'cover',
		transform: kb.transform,
		filter: style.grade.filter,
	};

	// Real light-leak sweep, front-loaded into the first ~1s of the reveal,
	// composited via Screen blend — the exact technique both real .aep
	// templates used their licensed overlay packs for.
	const leakWindowFrames = 45;
	const leakOpacity = interpolate(frame, [0, 8, leakWindowFrames], [0, 0.85, 0], {
		extrapolateLeft: 'clamp',
		extrapolateRight: 'clamp',
	});

	return (
		<AbsoluteFill style={{backgroundColor: '#050408', overflow: 'hidden'}}>
			<AbsoluteFill>
				{params.mediaType === 'video' ? (
					<OffthreadVideo src={staticFile(params.mediaSrc)} style={mediaStyle} />
				) : (
					<Img src={staticFile(params.mediaSrc)} style={mediaStyle} />
				)}
			</AbsoluteFill>

			<Grade style={style} />

			{params.noiseOverlaySrc ? (
				<AbsoluteFill style={{mixBlendMode: 'screen', opacity: 0.28, pointerEvents: 'none'}}>
					<Loop durationInFrames={121}>
						<OffthreadVideo
							src={staticFile(params.noiseOverlaySrc)}
							style={{width: '100%', height: '100%', objectFit: 'cover'}}
							muted
						/>
					</Loop>
				</AbsoluteFill>
			) : null}

			{params.leakOverlaySrc ? (
				<AbsoluteFill style={{mixBlendMode: 'screen', opacity: leakOpacity, pointerEvents: 'none'}}>
					<OffthreadVideo
						src={staticFile(params.leakOverlaySrc)}
						style={{width: '100%', height: '100%', objectFit: 'cover'}}
						muted
					/>
				</AbsoluteFill>
			) : null}

			<Vignette style={style} />

			<AbsoluteFill
				style={{
					justifyContent: 'flex-end',
					alignItems: 'flex-start',
					paddingLeft: 120,
					paddingBottom: 130,
					gap: 22,
				}}
			>
				{params.kicker ? <Kicker text={params.kicker} style={style} delay={leakWindowFrames + 4} /> : null}
				{params.caption ? (
					<Caption text={params.caption} style={style} delay={leakWindowFrames + 12} />
				) : null}
			</AbsoluteFill>
		</AbsoluteFill>
	);
};

registerTemplate<MediaRevealParams>({
	id: 'media_reveal',
	label: 'Media Reveal (photo or video slot + text slot)',
	pack: 'archive',
	durationInFrames: () => 180, // 6s @ 30fps — one representative scene beat
	component: MediaRevealComponent,
	defaultParams: {
		mediaSrc: 'img/shot01.jpg',
		mediaType: 'image',
		kicker: 'Plate 01',
		caption: 'Replace this media and caption per shot',
	},
});
