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
	face('InterLocal', 'inter-800.woff2', 800),
	face('InterLocal', 'inter-900.woff2', 900),
	// Typographic lockup faces (all SIL OFL 1.1 from Google Fonts, see fonts/LOCKUP-FONTS-OFL.txt).
	`@font-face{font-family:'PlayfairItalicLocal';src:url('${staticFile('fonts/playfair-italic-700.woff2')}') format('woff2');font-weight:700;font-style:italic;font-display:block;}`,
	face('PinyonLocal', 'pinyon-script-400.woff2', 400),
	face('BungeeOutlineLocal', 'bungee-outline-400.woff2', 400),
	face('SilkscreenLocal', 'silkscreen-400.woff2', 400),
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
	document.fonts.load("800 80px 'InterLocal'"),
	document.fonts.load("900 80px 'InterLocal'"),
	document.fonts.load("italic 700 80px 'PlayfairItalicLocal'"),
	document.fonts.load("400 80px 'PinyonLocal'"),
	document.fonts.load("400 80px 'BungeeOutlineLocal'"),
	document.fonts.load("400 80px 'SilkscreenLocal'"),
]).then(() => continueRender(handle)).catch(() => continueRender(handle));
