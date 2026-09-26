import type React from 'react';

/**
 * The actual continuity mechanism proven in interview_frame: whatever the
 * source's real aspect ratio is, apply the same containment rule so
 * heterogeneous sources (a 1940s clip, a phone recording, a square
 * archival photo) all read as belonging to the same documentary, instead
 * of each shot getting a different ad hoc crop/stretch decision.
 *
 * Was previously inlined only inside InterviewFrame — extracted here
 * because ArchiveVideo needs the identical logic, and duplicating it
 * would be the same mistake the Ken Burns primitive extraction just fixed.
 */
export function containFit(sourceAspectRatio: number, targetAspectRatio = 16 / 9): React.CSSProperties {
	return sourceAspectRatio >= targetAspectRatio
		? {width: '100%', height: 'auto'}
		: {height: '100%', width: 'auto'};
}
