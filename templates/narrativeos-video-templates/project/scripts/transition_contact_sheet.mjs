// Render a contact sheet (8 frames across the transition window, 4x2) for
// every transition recipe, so each one can be looked at before it counts
// as done.
//
//   node scripts/transition_contact_sheet.mjs [--style premium_documentary] [--only glitch] [--frames 8]
//
// Output: out/contact-sheets/<style>/<recipe>.jpg (gitignored).
import {bundle} from '@remotion/bundler';
import {getCompositions, renderStill} from '@remotion/renderer';
import {execFileSync} from 'node:child_process';
import {mkdirSync, rmSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const arg = (name, fallback) => {
	const i = process.argv.indexOf(`--${name}`);
	return i > -1 ? process.argv[i + 1] : fallback;
};
const styleId = arg('style', 'documentary_general');
const only = arg('only', '');
const frameCount = Number(arg('frames', '8'));
const PAD = 12; // must match PROOF_PAD in src/vfx/TransitionProof.tsx

const serveUrl = await bundle({entryPoint: path.join(root, 'src/index.ts')});
const comps = (await getCompositions(serveUrl)).filter((c) => c.id.startsWith('Proof-Transition-') && c.id.includes(only));
const outDir = path.join(root, 'out', 'contact-sheets', styleId);
mkdirSync(outDir, {recursive: true});

for (const comp of comps) {
	const inputProps = {...comp.defaultProps, styleId, showLabel: true};
	// Sample evenly across the recipe window (between the pads), and always include the cut frame.
	const first = PAD;
	const last = comp.durationInFrames - PAD - 1;
	const frames = Array.from({length: frameCount}, (_, i) => Math.round(first + ((last - first) * i) / (frameCount - 1)));
	const {cutFrame} = comp.defaultProps;
	if (!frames.includes(cutFrame)) {
		const nearest = frames.reduce((a, b, i) => (Math.abs(b - cutFrame) < Math.abs(frames[a] - cutFrame) ? i : a), 0);
		frames[nearest] = cutFrame;
	}
	const tmp = path.join(outDir, `_${comp.id}`);
	mkdirSync(tmp, {recursive: true});
	for (const [i, frame] of frames.entries()) {
		await renderStill({
			serveUrl,
			composition: {...comp, props: inputProps},
			inputProps,
			frame,
			output: path.join(tmp, `f${String(i).padStart(2, '0')}.png`),
			scale: 0.25,
		});
	}
	const recipe = comp.defaultProps.transitionId;
	const sheet = path.join(outDir, `${recipe}.jpg`);
	execFileSync('ffmpeg', ['-v', 'error', '-y', '-i', path.join(tmp, 'f%02d.png'), '-vf', `tile=4x${Math.ceil(frameCount / 4)}:padding=4`, '-frames:v', '1', '-update', '1', sheet]);
	rmSync(tmp, {recursive: true, force: true});
	console.log(`${recipe} -> ${path.relative(root, sheet)}`);
}
