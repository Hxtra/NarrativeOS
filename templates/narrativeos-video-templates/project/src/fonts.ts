import {continueRender, delayRender, staticFile} from 'remotion';
const face = (family: string, file: string, weight: number) =>
	`@font-face{font-family:'${family}';src:url('${staticFile('fonts/' + file)}') format('woff2');font-weight:${weight};font-display:block;}`;
const css = [
	face('PlayfairLocal', 'playfair-700.woff2', 700),
	face('PlayfairLocal', 'playfair-400.woff2', 400),
	face('BarlowLocal', 'barlow-400.woff2', 400),
	face('BarlowLocal', 'barlow-600.woff2', 600),
	// Inter (SIL OFL 1.1, see fonts/Inter-OFL-LICENSE.txt): clean sans for premium_documentary.
	face('InterLocal', 'inter-400.woff2', 400),
	face('InterLocal', 'inter-600.woff2', 600),
].join('\n');
const handle = delayRender('Loading local webfonts');
const style = document.createElement('style');
style.textContent = css;
document.head.appendChild(style);
Promise.all([
	document.fonts.load("700 96px 'PlayfairLocal'"),
	document.fonts.load("400 30px 'BarlowLocal'"),
	document.fonts.load("600 80px 'InterLocal'"),
	document.fonts.load("400 30px 'InterLocal'"),
]).then(() => continueRender(handle)).catch(() => continueRender(handle));
