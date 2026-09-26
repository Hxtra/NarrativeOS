export type AudioPolicy =
	| {mode: 'preserve'}
	| {mode: 'mute'}
	| {mode: 'duck'; duckToVolume: number}
	| {mode: 'replace'; replacementSrc: string; volume?: number};

/**
 * Safe default is 'mute', not 'preserve'. Old footage can carry useful
 * natural sound (interviews, crowd noise, camera noise) — but silently
 * preserving unknown archival audio by default is its own kind of
 * silent assumption, the same category of mistake as silently assuming
 * a frame rate. Preserving audio should be a deliberate choice per
 * asset, not what happens when nobody thought about it.
 */
export const DEFAULT_AUDIO_POLICY: AudioPolicy = {mode: 'mute'};

export function resolveVideoAudioProps(policy: AudioPolicy): {muted: boolean; volume: number} {
	switch (policy.mode) {
		case 'preserve':
			return {muted: false, volume: 1};
		case 'mute':
			return {muted: true, volume: 0};
		case 'duck':
			return {muted: false, volume: policy.duckToVolume};
		case 'replace':
			// Original audio silenced; the caller is responsible for adding a
			// separate <Audio src={policy.replacementSrc}> track — this
			// primitive only knows how to silence the source, not mount a
			// replacement, since that's a layout decision for the component.
			return {muted: true, volume: 0};
	}
}
