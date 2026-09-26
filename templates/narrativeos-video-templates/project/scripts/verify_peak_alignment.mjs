// Check that a recipe's footage overlay hits its brightest frame on the cut.
//
//   node scripts/verify_peak_alignment.mjs --recipe light_leak_warm --asset vfx_light_leak_warm_001
//
// Renders the recipe in TransitionProof's isolateOverlays mode (overlay only,
// on black, constant opacity) for frames cut-12..cut+12, measures mean luma
// per frame with ffmpeg, and reports where the brightest frame falls
// relative to the cut. Exit 1 if it is more than --tolerance frames off.
import {bundle} from '@remotion/bundler';
import {renderStill, selectComposition} from '@remotion/renderer';
import {execFileSync} from 'node:child_process';
import {mkdtempSync, rmSync} from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const arg = (name, fallback) => {
	const i = process.argv.indexOf(`--${name}`);
	return i > -1 ? process.argv[i + 1] : fallback;
};
const recipe = arg('recipe', 'light_leak_warm');
const asset = arg('asset', undefined);
const tolerance = Number(arg('tolerance', '1'));
const SPAN = 12;

const serveUrl = await bundle({entryPoint: path.join(root, 'src/index.ts')});
const inputProps = {transitionId: recipe, styleId: 'documentary_general', showLabel: false, isolateOverlays: true, pinAssetId: asset};
const composition = await selectComposition({serveUrl, id: `Proof-Transition-${recipe.replace(/_/g, '-')}`, inputProps});
const {cutFrame} = composition.defaultProps;
const tmp = mkdtempSync(path.join(os.tmpdir(), 'peak-'));
const rels = [];
for (let rel = -SPAN; rel <= SPAN; rel++) {
	const frame = cutFrame + rel;
	if (frame < 0 || frame >= composition.durationInFrames) continue;
	await renderStill({serveUrl, composition, inputProps, frame, output: path.join(tmp, `f${String(rels.length).padStart(3, '0')}.png`), scale: 0.25});
	rels.push(rel);
}
const out = execFileSync('ffmpeg', ['-v', 'error', '-i', path.join(tmp, 'f%03d.png'), '-vf', 'signalstats,metadata=mode=print:file=-', '-f', 'null', '-'], {encoding: 'utf8'});
const luma = [...out.matchAll(/lavfi\.signalstats\.YAVG=([\d.]+)/g)].map((m) => Number(m[1]));
rmSync(tmp, {recursive: true, force: true});

const best = luma.indexOf(Math.max(...luma));
console.log(rels.map((r, i) => `${r >= 0 ? '+' : ''}${r}: ${luma[i].toFixed(1)}`).join('  '));
console.log(`${recipe}${asset ? ` [${asset}]` : ''}: brightest frame at cut ${rels[best] >= 0 ? '+' : ''}${rels[best]} (tolerance ±${tolerance})`);
process.exit(Math.abs(rels[best]) <= tolerance ? 0 : 1);
