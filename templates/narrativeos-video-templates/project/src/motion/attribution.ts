/**
 * Shared across any editorial treatment that displays a real Media
 * Library source credit on screen. Was previously defined only inside
 * ArchiveVideo — extracted here because DoubleExposurePortrait needs the
 * identical shape for two sources (primary + secondary), not one.
 */
export interface ArchiveAttribution {
	/** e.g. "NASA", "Library of Congress via Wikimedia Commons" */
	source?: string;
	/** e.g. "1915", "January 1995" — whatever precision the real record has */
	date?: string;
	/** e.g. "Public Domain" — shown only when present, never invented */
	license?: string;
}

export function formatAttribution(a?: ArchiveAttribution): string {
	if (!a) return '';
	return [a.source, a.date, a.license].filter(Boolean).join(' · ');
}
