import React from 'react';
import {AbsoluteFill} from 'remotion';
import {resolveTemplate} from './registry/registry';
import {getStyle} from './styles/StyleProfile';
import './templates/TitleCard'; // side-effect: registers itself
import './templates/ChapterBreak';
import './templates/CreditsRoll';
import './templates/SubscribeCta';
import './templates/MediaReveal';
import './templates/SpeakerLowerThird';
import './templates/LocationStamp';
import './templates/InterviewFrame';
import './templates/ArchiveVideo';
import './templates/DoubleExposurePortrait';
import './templates/KineticCaptions';

// This is the literal "pick a template by name, fill the placeholder
// params, done" call NarrativeOS's render stage would make — no code
// generation, no LLM writing a component, just data in.
export const TemplatePlayer: React.FC<{templateId: string; styleId: string; params: unknown}> = ({
	templateId,
	styleId,
	params,
}) => {
	const def = resolveTemplate(templateId);
	const style = getStyle(styleId);
	const Component = def.component;
	return <Component style={style} params={params ?? def.defaultParams} />;
};

export interface LayerSpec {
	templateId: string;
	styleId: string;
	params: unknown;
}

/**
 * Stacks multiple templates as layers in one frame — the real mechanism a
 * timeline needs (interview footage + speaker ID + location stamp all
 * visible simultaneously), not just a way to preview one template at a
 * time.
 */
export const MultiLayerPlayer: React.FC<{layers: LayerSpec[]}> = ({layers}) => (
	<AbsoluteFill>
		{layers.map((layer, i) => (
			<AbsoluteFill key={i}>
				<TemplatePlayer templateId={layer.templateId} styleId={layer.styleId} params={layer.params} />
			</AbsoluteFill>
		))}
	</AbsoluteFill>
);
