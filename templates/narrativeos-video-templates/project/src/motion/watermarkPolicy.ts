export type WatermarkStatus = 'none' | 'present' | 'licensed' | 'unknown';
export type WatermarkAction = 'preserve' | 'reject' | 'manual_review';

export interface WatermarkPolicy {
	status: WatermarkStatus;
	action: WatermarkAction;
}

/**
 * This deliberately does NOT implement watermark removal — that's not
 * the problem being solved. The problem is that NarrativeOS should never
 * accidentally render footage whose watermark must remain, by treating
 * an unclear or unsafe state as if it were fine. This throws — a real,
 * enforced guard, not just documentation of an intended policy — when
 * the stated policy is actually unsafe:
 *
 *  - status "present" + action "reject" → refuse to render at all.
 *  - status "unknown" + anything other than "manual_review" → refuse.
 *    An unknown watermark state must route to a human, not be treated
 *    as safe by default.
 *
 * A missing policy is NOT silently treated as safe either — see the
 * caller in ArchiveVideo, which requires a policy for any real asset
 * (not the technical-test-fixture path, which explicitly opts out).
 */
export function enforceWatermarkPolicy(policy: WatermarkPolicy): void {
	if (policy.status === 'present' && policy.action === 'reject') {
		throw new Error(
			'Watermark policy violation: status is "present" but action is "reject" — ' +
				'refusing to render. This asset\'s watermark must remain; render it only ' +
				'with action "preserve".',
		);
	}
	if (policy.status === 'unknown' && policy.action !== 'manual_review') {
		throw new Error(
			`Watermark policy violation: status is "unknown" but action is "${policy.action}", ` +
				'not "manual_review". An unknown watermark state must route to manual review, ' +
				'not be treated as safe by default.',
		);
	}
}
