import React from 'react';
import {Composition} from 'remotion';
import './fonts';
import {TemplatePlayer, MultiLayerPlayer} from './TemplatePlayer';
import {resolveTemplate} from './registry/registry';
import {TransitionProof, proofTiming} from './vfx/TransitionProof';
import {listTransitions} from './vfx/transitionRegistry';
import {TransitionSegment} from './vfx/TransitionSegment';

const fps = 30;

/** Compositions driven by the multi-track compiler (scripts/render_segments.mjs): size, rate and length come from the props. */
type SegmentMeta = {durationInFrames: number; fps: number; width: number; height: number};
function segmentMetadata<T extends SegmentMeta>({props}: {props: T}) {
	return {durationInFrames: props.durationInFrames, fps: props.fps, width: props.width, height: props.height};
}
const GraphicSegment: React.FC<{templateId: string; styleId: string; params: unknown} & SegmentMeta> = ({templateId, styleId, params}) => (
	<TemplatePlayer templateId={templateId} styleId={styleId} params={params} />
);

export const RemotionRoot: React.FC = () => {
	const chapter = resolveTemplate('chapter_break');
	const credits = resolveTemplate('credits_roll');
	const cta = resolveTemplate('subscribe_cta');
	const title = resolveTemplate('title_card');

	const creditsParams = {
		title: 'THE LAST TRANSMISSION',
		rows: [
			{role: 'Narration', name: 'Sample Voice'},
			{role: 'Research', name: 'NarrativeOS'},
			{role: 'Archival Sourcing', name: 'Sample Archive'},
			{role: 'Editing', name: 'NarrativeOS Template Engine'},
			{role: 'Music', name: 'Sample Library'},
		],
		scrollSpeedPxPerSec: 90,
	};

	return (
		<>
			{/* Rendered by the compiler, not proofs: a template over transparency, and a recipe between two real shots. */}
			<Composition
				id="NOS-Graphic"
				component={GraphicSegment}
				calculateMetadata={segmentMetadata}
				durationInFrames={90}
				fps={fps}
				width={1920}
				height={1080}
				defaultProps={{templateId: 'title_card', styleId: 'documentary_general', params: title.defaultParams, durationInFrames: 90, fps, width: 1920, height: 1080}}
			/>
			<Composition
				id="NOS-Transition"
				component={TransitionSegment}
				calculateMetadata={segmentMetadata}
				durationInFrames={30}
				fps={fps}
				width={1920}
				height={1080}
				defaultProps={{
					transitionId: 'hard_cut', styleId: 'documentary_general', outgoingSrc: 'media-library/nasa_eileen_collins_001.jpg',
					incomingSrc: 'media-library/nasa_hubble_deep_field_001.jpg', cutFrame: 15, seed: 'default', durationInFrames: 30, fps, width: 1920, height: 1080,
				}}
			/>
			<Composition
				id="Proof-TitleCard"
				component={TemplatePlayer}
				durationInFrames={title.durationInFrames(title.defaultParams, fps)}
				fps={fps}
				width={1920}
				height={1080}
				defaultProps={{
					templateId: 'title_card',
					styleId: 'documentary_general',
					params: {kicker: 'Case File 12 · Cold Open', headline: 'THE LAST TRANSMISSION', sub: 'A different look-up, a different result'},
				}}
			/>
			<Composition
				id="Proof-TitleCard-BroadcastGrid"
				component={TemplatePlayer}
				durationInFrames={title.durationInFrames(title.defaultParams, fps)}
				fps={fps}
				width={1920}
				height={1080}
				defaultProps={{
					templateId: 'title_card',
					styleId: 'documentary_broadcast_grid',
					params: {kicker: 'Segment 04 · Live Desk', headline: 'THE PAPER TRAIL', sub: 'Same template id, genuinely different structure'},
				}}
			/>
			<Composition
				id="Proof-ChapterBreak"
				component={TemplatePlayer}
				durationInFrames={chapter.durationInFrames(chapter.defaultParams, fps)}
				fps={fps}
				width={1920}
				height={1080}
				defaultProps={{
					templateId: 'chapter_break',
					styleId: 'documentary_general',
					params: {eyebrow: 'Chapter Three', title: 'THE PAPER TRAIL'},
				}}
			/>
			<Composition
				id="Proof-CreditsRoll"
				component={TemplatePlayer}
				durationInFrames={credits.durationInFrames(creditsParams, fps)}
				fps={fps}
				width={1920}
				height={1080}
				defaultProps={{templateId: 'credits_roll', styleId: 'documentary_general', params: creditsParams}}
			/>
			<Composition
				id="Proof-SubscribeCta"
				component={TemplatePlayer}
				durationInFrames={cta.durationInFrames(cta.defaultParams, fps)}
				fps={fps}
				width={1920}
				height={1080}
				defaultProps={{
					templateId: 'subscribe_cta',
					styleId: 'documentary_general',
					params: {channelName: 'ARCHIVE REEL', ctaLine: 'New documentaries every Thursday'},
				}}
			/>
			<Composition
				id="Proof-MediaReveal"
				component={TemplatePlayer}
				durationInFrames={180}
				fps={fps}
				width={1920}
				height={1080}
				defaultProps={{
					templateId: 'media_reveal',
					styleId: 'documentary_general',
					params: {
						mediaSrc: 'media-library/nasa_eileen_collins_001.jpg',
						mediaType: 'image',
						kicker: 'nasa_eileen_collins_001 · rights_verified',
						caption: 'Sourced from the Media Library record, not a hardcoded path',
						// No leakOverlaySrc/noiseOverlaySrc here deliberately — this
						// composition must render out of the box with zero setup.
						// See Proof-MediaReveal-LicensedOverlay for the overlay-compositing
						// test, which requires the user's own purchased asset files
						// (see project/public/licensed/urban-slideshow/README.md).
					},
				}}
			/>
			<Composition
				id="Proof-MediaReveal-LicensedOverlay"
				component={TemplatePlayer}
				durationInFrames={180}
				fps={fps}
				width={1920}
				height={1080}
				defaultProps={{
					templateId: 'media_reveal',
					styleId: 'documentary_general',
					params: {
						mediaSrc: 'media-library/nasa_eileen_collins_001.jpg',
						mediaType: 'image',
						kicker: 'nasa_eileen_collins_001 · rights_verified',
						caption: 'Real licensed overlay compositing test',
						// Requires the user's own Leak.mov / noise.mov dropped into
						// project/public/licensed/urban-slideshow/ — this composition
						// will 404 until those files are present. That's expected,
						// not a bug — see the README in that folder.
						leakOverlaySrc: 'licensed/urban-slideshow/Leak.mov',
						noiseOverlaySrc: 'licensed/urban-slideshow/noise.mov',
					},
				}}
			/>
			<Composition
				id="Proof-SpeakerFirst"
				component={TemplatePlayer}
				durationInFrames={150}
				fps={fps}
				width={1920}
				height={1080}
				defaultProps={{
					templateId: 'speaker_lower_third',
					styleId: 'documentary_general',
					params: {name: 'Dr. Amara Solanke', role: 'Historian, University of Lagos', isReturning: false},
				}}
			/>
			<Composition
				id="Proof-SpeakerReturning"
				component={TemplatePlayer}
				durationInFrames={90}
				fps={fps}
				width={1920}
				height={1080}
				defaultProps={{
					templateId: 'speaker_lower_third',
					styleId: 'documentary_general',
					params: {name: 'Dr. Amara Solanke', isReturning: true},
				}}
			/>
			<Composition
				id="Proof-LocationStamp"
				component={TemplatePlayer}
				durationInFrames={90}
				fps={fps}
				width={1920}
				height={1080}
				defaultProps={{
					templateId: 'location_stamp',
					styleId: 'documentary_general',
					params: {location: 'Lagos, Nigeria', date: 'March 2024'},
				}}
			/>
			<Composition
				id="Proof-InterviewCombined"
				component={MultiLayerPlayer}
				durationInFrames={150}
				fps={fps}
				width={1920}
				height={1080}
				defaultProps={{
					layers: [
						{
							templateId: 'interview_frame',
							styleId: 'documentary_general',
							params: {
								mediaSrc: 'media-library/nasa_eileen_collins_001.jpg',
								mediaType: 'image',
								sourceAspectRatio: 1,
							},
						},
						{
							templateId: 'location_stamp',
							styleId: 'documentary_general',
							params: {location: 'Houston, Texas', date: 'January 1995'},
						},
						{
							templateId: 'speaker_lower_third',
							styleId: 'documentary_general',
							params: {name: 'Eileen Collins', role: 'NASA Astronaut, STS-63 Pilot', isReturning: false},
						},
					],
				}}
			/>
			<Composition
				id="Proof-ArchiveVideo"
				component={TemplatePlayer}
				durationInFrames={180}
				fps={fps}
				width={1920}
				height={1080}
				defaultProps={{
					templateId: 'archive_video',
					styleId: 'documentary_general',
					params: {
						mediaSrc: 'media-library/nasa_eileen_collins_001.jpg',
						mediaType: 'image',
						sourceAspectRatio: 1,
						attribution: {source: 'NASA Great Images database', date: '1995', license: 'Public Domain'},
					},
				}}
			/>
			<Composition
				id="Proof-DoubleExposurePortrait"
				component={TemplatePlayer}
				durationInFrames={180}
				fps={fps}
				width={1920}
				height={1080}
				defaultProps={{
					templateId: 'double_exposure_portrait',
					styleId: 'documentary_general',
					params: {
						primaryMediaSrc: 'media-library/nasa_eileen_collins_001.jpg',
						primaryMediaType: 'image',
						primaryAspectRatio: 1,
						secondaryMediaSrc: 'media-library/nasa_hubble_deep_field_001.jpg',
						secondaryMediaType: 'image',
						secondaryAspectRatio: 1.147,
						kicker: 'Plate 04 · Portrait',
						caption: 'Two real Media Library records, one primitive',
						primaryAttribution: {source: 'NASA Great Images database', date: '1995', license: 'Public Domain'},
						secondaryAttribution: {source: 'NASA / HubbleSite', license: 'Public Domain'},
					},
				}}
			/>
			<Composition
				id="Proof-ArchiveVideo-RealFootage"
				component={TemplatePlayer}
				durationInFrames={120}
				fps={fps}
				width={1920}
				height={1080}
				defaultProps={{
					templateId: 'archive_video',
					styleId: 'documentary_general',
					params: {
						mediaSrc: 'test-fixtures/cockatoo_test.mp4',
						mediaType: 'video',
						sourceAspectRatio: 1.778,
						kenBurns: null,
						flickerAmount: 0.6,
						attribution: {source: 'ENGINEERING TEST FIXTURE — rights unverified, not documentary content'},
						technicalProfile: {sourceFps: 20.0, sourceDurationSec: 14.0, sourceFpsIsCommonValue: false},
						audioPolicy: {mode: 'duck', duckToVolume: 0.2},
						watermarkPolicy: {status: 'unknown', action: 'manual_review'},
						showTechnicalDebug: true,
					},
				}}
			/>
			<Composition
				id="Proof-TitleCard-Premium"
				component={TemplatePlayer}
				durationInFrames={title.durationInFrames(title.defaultParams, fps)}
				fps={fps}
				width={1920}
				height={1080}
				defaultProps={{
					templateId: 'title_card',
					styleId: 'premium_documentary',
					params: {kicker: 'A NarrativeOS Original', headline: 'THE LAST TRANSMISSION', sub: 'Episode One'},
				}}
			/>
			{/* One proof per registered transition recipe (ids use hyphens: Remotion forbids underscores). */}
			{listTransitions().map((recipe) => (
				<Composition
					key={recipe.id}
					id={`Proof-Transition-${recipe.id.replace(/_/g, '-')}`}
					component={TransitionProof}
					durationInFrames={proofTiming(recipe).durationInFrames}
					fps={fps}
					width={1920}
					height={1080}
					defaultProps={{transitionId: recipe.id, styleId: 'documentary_general', showLabel: true, cutFrame: proofTiming(recipe).cutFrame}}
				/>
			))}
		</>
	);
};
