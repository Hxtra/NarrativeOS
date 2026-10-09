// Print the template, transition-recipe and style registries as JSON, for the Python compiler.
//
//   node scripts/export_registry.mjs            -> JSON on stdout
//
// The registries are plain data registered at import time, so they are bundled with esbuild (already a Remotion
// dependency) and evaluated in Node: no browser, no render. Packages stay external and resolve from node_modules.
import {build} from 'esbuild';
import {mkdirSync, rmSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const entry = `
import {TRANSITION_REGISTRY} from './src/vfx/transitionRegistry';
import './src/vfx/recipes';
import {TEMPLATE_REGISTRY} from './src/registry/registry';
import './src/TemplatePlayer';
import {STYLE_REGISTRY} from './src/styles/StyleProfile';
export const registry = {
	transitions: Object.values(TRANSITION_REGISTRY).map((r) => ({
		id: r.id, label: r.label, meaning: r.meaning, intensity: r.intensity, window: r.window,
		cut: r.spec.cut, layers: r.spec.layers.map((l) => l.kind), sfx: r.spec.sfx ?? [],
	})),
	templates: Object.values(TEMPLATE_REGISTRY).map((t) => ({id: t.id, label: t.label, pack: t.pack, aspects: t.aspects ?? ['16:9']})),
	styles: Object.keys(STYLE_REGISTRY),
};
`;

// Bundle inside the project so external packages resolve from its node_modules (.nos-bundle is gitignored).
const out = path.join(root, '.nos-bundle', `registry-${process.pid}.mjs`);
mkdirSync(path.dirname(out), {recursive: true});
try {
	await build({
		stdin: {contents: entry, resolveDir: root, loader: 'ts'},
		bundle: true,
		platform: 'node',
		format: 'esm',
		packages: 'external',
		jsx: 'automatic',
		loader: {'.png': 'empty', '.jpg': 'empty', '.css': 'empty', '.woff2': 'empty', '.ttf': 'empty'},
		outfile: out,
		logLevel: 'error',
	});
	const {registry} = await import(pathToFileURL(out).href);
	process.stdout.write(JSON.stringify(registry));
} finally {
	rmSync(out, {force: true});
}
