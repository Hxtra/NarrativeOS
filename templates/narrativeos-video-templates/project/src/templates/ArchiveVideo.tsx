import React from 'react';
import {AbsoluteFill, Audio, Img, OffthreadVideo, interpolate, staticFile, useCurrentFrame} from 'remotion';
import type {StyleProfile} from '../styles/StyleProfile';
import {Grade, Vignette, Grain} from '../motion/FilmTexture';
import {containFit} from '../motion/mediaFit';
import {useKenBurns, DEFAULT_KEN_BURNS, type KenBurnsSpec} from '../motion/kenBurns';
import {useArchiveFlicker} from '../motion/archiveFlicker';
import {type ArchiveAttribution, formatAttribution} from '../motion/attribution';
import {type AudioPolicy, DEFAULT_AUDIO_POLICY, resolveVideoAudioProps} from '../motion/audioPolicy';
import {type WatermarkPolicy, enforceWatermarkPolicy} from '../motion/watermarkPolicy';
import {registerTemplate} from '../registry/registry';

/**
 * Real, ffprobe-derived technical facts about the source — populated by
 * media-library/tools/probe_asset.py at ingestion time, never guessed
 * here. Video playback speed itself needs no correction: Remotion sets
 * `video.currentTime = frame / compositionFps` (confirmed in Remotion's
 * own docs), so a 20fps source already plays back at correct real-world
 * speed inside a 30fps timeline automatically. What DOES need to be
 * explicit is everything Remotion's auto-sync doesn't tell you — how
 * many actually distinct source frames exist, and whether the fps is an
 * unusual value worth knowing about before making motion decisions.
 */
export interface SourceTechnicalProfile {
	sourceFps: number;
	sourceDurationSec: number;
	sourceFpsIsCommonValue: boolean;
}

export interface ArchiveVideoParams {
	mediaSrc: string;
	mediaType: 'image' | 'video';
	sourceAspectRatio?: number;
	kenBurns?: KenBurnsSpec | null;
	attribution?: ArchiveAttribution;
	technicalProfile?: SourceTechnicalProfile;
	audioPolicy?: AudioPolicy;
	/**
	 * Required for any real (non-test-fixture) video asset with audio —
	 * there is no default that silently lets footage through. Omit only
	 * for images or silent video; see enforceWatermarkPolicy for what
	 * happens if the stated policy is itself unsafe.
	 */
	watermarkPolicy?: WatermarkPolicy;
	/** Independent of positional Ken Burns jitter — a moving video source
	 * shouldn't be forced to take translate jitter just to get exposure
	 * flicker. 0 disables. */
	flickerAmount?: number;
	/** Dev/QA aid: renders the real probed technical facts on screen so
	 * they're provably plumbed through, not just typed and ignored. */
	showTechnicalDebug?: boolean;
}

const DURATION = 180;

const ArchiveVideoComponent: React.FC<{style: StyleProfile; params: ArchiveVideoParams}> = ({
	style,
	params,
}) => {
	const frame = useCurrentFrame();

	if (params.watermarkPolicy) {
		enforceWatermarkPolicy(params.watermarkPolicy);
	}

	const targetAspect = 16 / 9;
	const sourceAspect = params.sourceAspectRatio ?? targetAspect;
	const fitStyle = containFit(sourceAspect, targetAspect);

	const kbSpec = params.kenBurns === null ? null : (params.kenBurns ?? DEFAULT_KEN_BURNS);
	const kb = useKenBurns(kbSpec ?? DEFAULT_KEN_BURNS, DURATION, style.motion.kenBurnsEase);
	const flicker = useArchiveFlicker(params.flickerAmount ?? 0);

	const mediaStyle: React.CSSProperties = {
		...fitStyle,
		transform: kbSpec ? kb.transform : undefined,
		filter: `${style.grade.filter} ${flicker.filter !== 'none' ? flicker.filter : ''}`.trim(),
		display: 'block',
		margin: 'auto',
	};

	const audioPolicy = params.audioPolicy ?? DEFAULT_AUDIO_POLICY;
	const audioProps = resolveVideoAudioProps(audioPolicy);

	const fadeIn = interpolate(frame, [0, 14], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
	const attributionOpacity = interpolate(frame, [10, 26], [0, 0.75], {
		extrapolateLeft: 'clamp',
		extrapolateRight: 'clamp',
	});

	const attributionLine = formatAttribution(params.attribution);
	const tp = params.technicalProfile;
	const realFrameCount = tp ? Math.round(tp.sourceFps * tp.sourceDurationSec) : null;

	return (
		<AbsoluteFill style={{backgroundColor: '#020203', opacity: fadeIn, overflow: 'hidden'}}>
			<AbsoluteFill style={{justifyContent: 'center', alignItems: 'center', overflow: 'hidden'}}>
				{params.mediaType === 'video' ? (
					<OffthreadVideo
						src={staticFile(params.mediaSrc)}
						style={mediaStyle}
						muted={audioProps.muted}
						volume={audioProps.volume}
					/>
				) : (
					<Img src={staticFile(params.mediaSrc)} style={mediaStyle} />
				)}
			</AbsoluteFill>

			{audioPolicy.mode === 'replace' ? (
				<Audio src={staticFile(audioPolicy.replacementSrc)} volume={audioPolicy.volume ?? 1} />
			) : null}

			<Grade style={style} />
			<Vignette style={style} />
			<Grain style={style} />

			{attributionLine ? (
				<div
					style={{
						position: 'absolute',
						right: 36,
						bottom: 28,
						opacity: attributionOpacity,
						fontFamily: style.typography.sansFamily,
						fontSize: 16,
						letterSpacing: 0.6,
						color: style.typography.boneDimColor,
						textShadow: '0 2px 8px rgba(0,0,0,0.7)',
					}}
				>
					{attributionLine}
				</div>
			) : null}

			{params.showTechnicalDebug && tp ? (
				<div
					style={{
						position: 'absolute',
						left: 36,
						top: 28,
						fontFamily: 'monospace',
						fontSize: 15,
						color: '#8f8',
						background: 'rgba(0,0,0,0.55)',
						padding: '6px 10px',
						lineHeight: 1.5,
					}}
				>
					source_fps: {tp.sourceFps}{tp.sourceFpsIsCommonValue ? '' : ' (uncommon)'}
					<br />
					real_source_frames: {realFrameCount}
					<br />
					audio_policy: {audioPolicy.mode}
				</div>
			) : null}
		</AbsoluteFill>
	);
};

registerTemplate<ArchiveVideoParams>({
	id: 'archive_video',
	label: 'Archive Video/Photo (normalized treatment for heterogeneous real sources)',
	pack: 'archive',
	durationInFrames: () => DURATION,
	component: ArchiveVideoComponent,
	defaultParams: {
		mediaSrc: 'media-library/nasa_eileen_collins_001.jpg',
		mediaType: 'image',
		sourceAspectRatio: 1,
		attribution: {source: 'NASA', date: '1995', license: 'Public Domain'},
	},
});
