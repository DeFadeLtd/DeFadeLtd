<a href="https://defade.org"><img src="assets/hero.svg" width="100%" alt="DeFade, the multi-chain memecoin analyzer. Read the wallets, not the promises."></a>

<p align="center">
  <a href="https://defade.org"><img src="assets/pill-scan.svg" height="34" alt="Scan a token on defade.org"></a>
  <a href="https://t.me/DeFadeAnalyzerBot"><img src="assets/pill-telegram.svg" height="34" alt="Telegram bot"></a>
  <a href="https://defade.org/download"><img src="assets/pill-apps.svg" height="34" alt="iOS and Android apps"></a>
  <a href="https://chromewebstore.google.com/detail/defade-%E2%80%94-solana-rug-pull/omcpnfjfaedbkakmnmbfjfmdnbpninof"><img src="assets/pill-extension.svg" height="34" alt="Chrome extension"></a>
  <a href="https://defade.org/api-docs"><img src="assets/pill-api.svg" height="34" alt="REST API and MCP connector"></a>
</p>

<p align="center">
  <a href="https://x.com/dexbuilds"><img src="assets/byline.svg" height="32" alt="Built by @dexbuilds on X"></a>
</p>

<a href="https://defade.org/survival"><img src="assets/pulse.svg" width="100%" alt="Live from defade.org: tokens DeFade flagged first that rugged later, out of every token flagged and tracked, and the survival curve of every memecoin it follows."></a>

<a href="https://defade.org/heatmap"><img src="assets/rug-clock.svg" width="49.5%" alt="Rug Clock: scan activity and the share of new tokens scored high risk, for each hour of the day."></a>
<a href="https://defade.org/whitepaper"><img src="assets/chains.svg" width="49.5%" alt="Seven chains and their launchpads, every module on every chain."></a>

<a href="https://defade.org/modules"><img src="assets/modules.svg" width="100%" alt="What a scan reads: 34 modules grouped by six questions, adding up to one rug pull probability from 0 to 100."></a>

### Build on DeFade

```js
import DeFade from 'defade';                      // npm install defade

const client = new DeFade({ apiKey: process.env.DEFADE_API_KEY });
const risk = await client.rugScore('TOKEN_MINT');  // 0 to 100
```

- **[REST API](https://defade.org/api-docs)**: 30 endpoints, every chain on every plan. A free 7-day trial key opens six of them.
- **[MCP connector](https://defade.org/api-docs#mcp)**: real DeFade scans inside an AI assistant, 15 read-only tools at `https://api.defade.org/mcp`
- **[defade-sdk](https://github.com/DeFadeLtd/defade-sdk)**: the JavaScript client. Zero dependencies, Node 18+, CJS and ESM, TypeScript types.
- **[DeFade-scanner](https://github.com/DeFadeLtd/DeFade-scanner)**: how the scan and the score work, worked API examples, and where to report a wrong verdict.

<p align="center"><sub>The live cards redraw every day from <a href="https://defade.org/survival">defade.org/survival</a> and <a href="https://defade.org/heatmap">defade.org/heatmap</a>. DeFade Ltd, London · <a href="mailto:info@defade.org">info@defade.org</a></sub></p>
