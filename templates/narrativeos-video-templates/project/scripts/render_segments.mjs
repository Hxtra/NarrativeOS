// Render the compiler's Remotion segments: graphics over transparency, and recipe transitions between real shots.
//
//   node scripts/render_segments.mjs <jobs.json>
//
// jobs.json: {"bundleKey": "<hash of src/>", "segments": [{"key", "composition": "NOS-Graphic" | "NOS-Transition",
//             "props": {...incl. durationInFrames, fps, width, height}, "scale": 0.5, "transparent": true,
//             "output": "<absolute path>"}]}
// Writes one JSON object per line on stdout: {"type": "bundle"|"start"|"progress"|"done"|"error", ...}. Exit code 1
// if any segment failed. The bundle is cached in .nos-bundle/<bundleKey> (gitignored), so only a changed src/
// rebundles.
import {bundle} from '@remotion/bundler';
import {renderMedia, selectComposition} from '@remotion/renderer';
import {cpSync, existsSync, mkdirSync, readFileSync, readdirSync, renameSync, rmSync, writeFileSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const emit = (o) => process.stdout.write(JSON.stringify(o) + '\n');
const jobs = JSON.parse(readFileSync(process.argv[2], 'utf8'));

const cacheRoot = path.join(root, '.nos-bundle');
const bundleDir = path.join(cacheRoot, `bundle-${jobs.bundleKey}`);
let serveUrl = bundleDir;
const t0 = Date.now();
if (!existsSync(path.join(bundleDir, 'index.html'))) {
	mkdirSync(cacheRoot, {recursive: true});
	// Old bundles are stale once src/ changed: keep the cache to the current one.
	for (const d of readdirSync(cacheRoot)) if (d.startsWith('bundle-')) rmSync(path.join(cacheRoot, d), {recursive: true, force: true});
	serveUrl = await bundle({entryPoint: path.join(root, 'src/index.ts'), outDir: bundleDir});
	emit({type: 'bundle', cached: false, seconds: (Date.now() - t0) / 1000});
} else {
	emit({type: 'bundle', cached: true, seconds: 0});
}
// The bundle serves its own copy of public/, taken when it was built. Staged compiler inputs (public/_nos) appear
// after that, so copy them in for this run (existing files are kept) and clear the per-render windows afterwards.
const stagedSrc = path.join(root, 'public', '_nos');
const stagedDst = path.join(bundleDir, 'public', '_nos');
if (existsSync(stagedSrc)) cpSync(stagedSrc, stagedDst, {recursive: true, force: false, errorOnExist: false});

let failed = 0;
for (const seg of jobs.segments) {
	const started = Date.now();
	emit({type: 'start', key: seg.key, composition: seg.composition});
	try {
		const composition = await selectComposition({serveUrl, id: seg.composition, inputProps: seg.props});
		mkdirSync(path.dirname(seg.output), {recursive: true});
		const tmp = seg.output.replace(/(\.\w+)$/, '.partial$1');
		const transparent = Boolean(seg.transparent);
		let last = -1;
		await renderMedia({
			serveUrl,
			composition,
			inputProps: seg.props,
			outputLocation: tmp,
			scale: seg.scale ?? 1,
			// Transparent graphics: PNG frames into ProRes 4444 with alpha. Opaque transitions: near-lossless H.264.
			...(transparent
				? {codec: 'prores', proResProfile: '4444', imageFormat: 'png', pixelFormat: 'yuva444p10le'}
				: {codec: 'h264', crf: 12, imageFormat: 'jpeg', jpegQuality: 95}),
			muted: true,
			onProgress: ({progress}) => {
				const p = Math.round(progress * 100);
				if (p !== last) {
					last = p;
					emit({type: 'progress', key: seg.key, progress});
				}
			},
		});
		renameSync(tmp, seg.output);
		emit({type: 'done', key: seg.key, seconds: (Date.now() - started) / 1000, frames: composition.durationInFrames});
	} catch (e) {
		failed++;
		emit({type: 'error', key: seg.key, message: String(e && e.stack ? e.stack : e).slice(0, 4000)});
	}
}
rmSync(path.join(stagedDst, 'work'), {recursive: true, force: true});
writeFileSync(path.join(cacheRoot, 'last-run.json'), JSON.stringify({segments: jobs.segments.length, failed, seconds: (Date.now() - t0) / 1000}));
process.exit(failed ? 1 : 0);
