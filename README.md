<a href="https://defade.org"><img src="assets/hero.svg" width="100%" alt="DEFADE, the multi-chain memecoin analyzer. See through the token."></a>

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

<a href="https://defade.org/survival"><img src="assets/pulse.svg" width="100%" alt="Live from defade.org: the share of the tokens DEFADE flagged that rugged after the flag, and the survival curve of every memecoin it follows."></a>

<a href="https://defade.org/heatmap"><img src="assets/rug-clock.svg" width="49.5%" alt="Rug Clock: scan activity and the share of new tokens scored high risk, for each hour of the day."></a>
<a href="https://defade.org/whitepaper"><img src="assets/chains.svg" width="49.5%" alt="Eight chains and their launchpads, every module on every chain."></a>

<a href="https://defade.org/modules#launchpads"><img src="assets/launchpads.svg" width="100%" alt="50 launchpads on eight chains, each read off its own contracts: pump.fun, bonk.fun, Raydium LaunchLab, Meteora DBC, boop.fun, Jupiter Studio, Bags, Believe, Moonit, MetaDAO, Printr, Shipfun, StonkFun, Launch, Float, notrandom.fun, Pangea, Clanker, Doppler, based.bid, Stockereum.fun, Zora, Flaunch, Virtuals, Bankr, flap.sh, Cracker.fun, o1 Launchpad, four.meme, Genius, Pons, Flywheel, FOBO, Clank, Pools.trade, Torch, TickUp.fun, Zeta.fun, Long.xyz, Anoncoin, Argus, Tolly, Minara.fun, ubi.fun, Warp, Foci, Peach, Faze, LiquidLaunch and nad.fun."></a>

<a href="https://defade.org/modules#launch-tools"><img src="assets/launch-tools.svg" width="100%" alt="Launch tools the scan names, each off a mark only its own launches leave: Proxima and Sumo, a critical flag on their own; uxento, J7 and RapidLaunch, scored beside a launch-block bundle."></a>

<a href="https://defade.org/blog/defade-memory"><img src="assets/memory.svg" width="100%" alt="DEFADE Memory: every scan keeps the bundlers, snipers, fresh wallets, insiders, funders, operator bands, token creators and launch tool fleets, and marks every wallet on a token that later rugs."></a>

<a href="https://defade.org/modules"><img src="assets/modules.svg" width="100%" alt="What a scan reads: 34 modules grouped by six questions, adding up to one rug pull probability from 0 to 100."></a>

### Build on DEFADE

```js
import DeFade from 'defade';                      // npm install defade

const client = new DeFade({ apiKey: process.env.DEFADE_API_KEY });
const risk = await client.rugScore('TOKEN_MINT');  // 0 to 100
```

- **[REST API](https://defade.org/api-docs)**: 30 endpoints, every chain on every plan. A free 7-day trial key opens six of them.
- **[MCP connector](https://defade.org/api-docs#mcp)**: real DEFADE scans inside an AI assistant, 15 read-only tools at `https://api.defade.org/mcp`
- **[defade-sdk](https://github.com/DeFadeLtd/defade-sdk)**: the JavaScript client. Zero dependencies, Node 18+, CJS and ESM, TypeScript types.
- **[DeFade-scanner](https://github.com/DeFadeLtd/DeFade-scanner)**: how the scan and the score work, worked API examples, and where to report a wrong verdict.

<p align="center"><sub>The live cards redraw every day from <a href="https://defade.org/survival">defade.org/survival</a> and <a href="https://defade.org/heatmap">defade.org/heatmap</a>. DEFADE Ltd, London · <a href="mailto:info@defade.org">info@defade.org</a></sub></p>
