#!/usr/bin/env python3
"""Draws the cards on github.com/DeFadeLtd.

Every card is a self-contained SVG in assets/: the fonts are subset to the
glyphs the card uses and embedded, the icons are inline, and nothing is
fetched when GitHub shows it. Two cards carry live figures from the public
pages of defade.org (the Survival page's track record and survival curve,
and the Rug Clock); the workflow in .github/workflows/refresh.yml redraws them daily.

    pip install fonttools brotli
    python scripts/build.py            # fetch live figures, draw every card
    python scripts/build.py --offline  # draw from data/live.json as it is

When a fetch fails the last good figures in data/live.json are drawn again,
so a bad day at the API never blanks the profile.
"""
import argparse
import base64
import datetime as dt
import io
import json
import math
import os
import random
import sys
import urllib.request
from collections import defaultdict

from fontTools import subset
from fontTools.ttLib import TTFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, 'assets')
API = 'https://api.defade.org'
UA = 'DeFade-profile/1.0 (+https://github.com/DeFadeLtd)'

C = {
    'bg': '#05060f',
    'panel': '#0a0c1c',
    'text': '#f0f0f8',
    'dim': '#9095bb',
    'faint': '#5d6189',
    'cyan': '#00d4ff',
    'purple': '#bf5af2',
    'green': '#30d158',
    'yellow': '#f5c842',
    'orange': '#f5873a',
    'red': '#f0375c',
    'extreme': '#ff2d55',
}

# The five verdict bands, as the site draws them.
BANDS = [
    (0, 24, 'PROBABLY SAFE', C['green']),
    (25, 44, 'SOME RISK', C['yellow']),
    (45, 59, 'ELEVATED RISK', C['orange']),
    (60, 74, 'HIGH RISK', C['red']),
    (75, 100, 'EXTREME RISK', C['extreme']),
]

# ---------------------------------------------------------------- fonts ---

FONTS = {
    # key: (file, css family stack behind the embedded face, weight)
    'display': ('ChakraPetch-Bold.ttf', "'Chakra Petch', 'Segoe UI', sans-serif", 700),
    'sans': ('Manrope-600.ttf', "Manrope, 'Segoe UI', Helvetica, Arial, sans-serif", 600),
    'sansb': ('Manrope-800.ttf', "Manrope, 'Segoe UI', Helvetica, Arial, sans-serif", 800),
    'mono': ('JetBrainsMono-Medium.ttf', "'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Consolas, monospace", 500),
    'monob': ('JetBrainsMono-Bold.ttf', "'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Consolas, monospace", 700),
}
_metrics = {}


def font_path(key):
    return os.path.join(ROOT, 'fonts', FONTS[key][0])


def measure(s, key, size, ls=0.0):
    """Advance width of s in px: enough to lay out pills and wrap lines."""
    if key not in _metrics:
        tt = TTFont(font_path(key))
        _metrics[key] = (tt['head'].unitsPerEm, tt.getBestCmap(), tt['hmtx'])
    upm, cmap, hmtx = _metrics[key]
    w = 0
    for ch in s:
        g = cmap.get(ord(ch))
        w += hmtx[g][0] if g else upm * 0.55
    return w * size / upm + ls * len(s)


def font_face(key, chars):
    opts = subset.Options()
    opts.flavor = 'woff2'
    opts.layout_features = ['kern', 'liga', 'tnum']
    opts.hinting = False
    opts.name_IDs = [1, 2]
    opts.notdef_outline = True
    font = subset.load_font(font_path(key), opts)
    sub = subset.Subsetter(opts)
    sub.populate(text=chars + ' ')
    sub.subset(font)
    buf = io.BytesIO()
    subset.save_font(font, buf, opts)
    data = base64.b64encode(buf.getvalue()).decode()
    return ('@font-face{font-family:df-%s;font-weight:%d;'
            'src:url(data:font/woff2;base64,%s) format("woff2")}' % (key, FONTS[key][2], data))


# ---------------------------------------------------------------- cards ---

def esc(s):
    return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')


class Card:
    """One SVG: collects the text it draws so the fonts carry only those glyphs."""

    def __init__(self, w, h, title, desc):
        self.w, self.h = w, h
        self.title, self.desc = title, desc
        self.defs, self.body, self.css = [], [], []
        self.used = defaultdict(set)
        self._anim = 0

    def add(self, *parts):
        self.body.extend(parts)

    def text(self, x, y, s, font='sans', size=14, fill=None, anchor='start', ls=0, attrs=''):
        self.used[font].update(s)
        fill = fill or C['text']
        extra = ''
        if anchor != 'start':
            extra += ' text-anchor="%s"' % anchor
        if ls:
            extra += ' letter-spacing="%s"' % _n(ls)
        return '<text x="%s" y="%s" class="%s" font-size="%s" fill="%s"%s%s>%s</text>' % (
            _n(x), _n(y), font, _n(size), fill, extra, (' ' + attrs) if attrs else '', esc(s))

    def spans(self, x, y, parts, font='sans', size=14, anchor='start', ls=0):
        """One line in several colours: parts is [(text, fill, font or None)]."""
        out = []
        for s, fill, f in parts:
            self.used[f or font].update(s)
            cls = (' class="%s"' % f) if f else ''
            out.append('<tspan fill="%s"%s>%s</tspan>' % (fill, cls, esc(s)))
        extra = ' text-anchor="%s"' % anchor if anchor != 'start' else ''
        if ls:
            extra += ' letter-spacing="%s"' % _n(ls)
        return '<text x="%s" y="%s" class="%s" font-size="%s"%s>%s</text>' % (
            _n(x), _n(y), font, _n(size), extra, ''.join(out))

    def appear(self, t_in, t_out=9.3, period=10.0, dx=-6, fade=0.35):
        """A class that brings an element in at t_in and out at t_out, every period."""
        self._anim += 1
        name = 'a%d' % self._anim
        p = lambda t: '%.2f%%' % (100 * t / period)
        start = 'opacity:0;transform:translate(%dpx,0)' % dx
        self.css.append(
            '@keyframes k%s{0%%,%s{%s}%s,%s{opacity:1;transform:none}%s,100%%{opacity:0}}'
            '.%s{animation:k%s %ss linear infinite both}' % (
                name, p(t_in), start, p(t_in + fade), p(t_out), p(t_out + 0.3),
                name, name, _n(period)))
        return name

    def render(self):
        faces = ''.join(font_face(k, ''.join(sorted(v))) for k, v in sorted(self.used.items()))
        classes = ''.join('.%s{font-family:df-%s,%s;font-weight:%d}' % (k, k, f[1], f[2])
                          for k, f in FONTS.items() if k in self.used)
        style = (faces + classes + ''.join(self.css) +
                 '@media (prefers-reduced-motion:reduce){*{animation:none!important}}')
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
            'width="%d" height="%d" viewBox="0 0 %d %d" role="img" aria-labelledby="title desc">'
            '<title id="title">%s</title><desc id="desc">%s</desc>'
            '<style>%s</style><defs>%s</defs>%s</svg>\n' % (
                self.w, self.h, self.w, self.h, esc(self.title), esc(self.desc),
                style, ''.join(self.defs), ''.join(self.body)))

    def save(self, name):
        path = os.path.join(ASSETS, name)
        with open(path, 'w') as f:
            f.write(self.render())
        print('  %-22s %6.1f kB' % (name, os.path.getsize(path) / 1024))


def _n(v):
    if isinstance(v, float):
        s = ('%.2f' % v).rstrip('0').rstrip('.')
        return s if s not in ('-0', '') else '0'
    return str(v)


def frame(card, seed, stars=46, glow=('cyan', 'purple'), radius=20):
    """The space backdrop every card shares: deep black, two soft glows, stars."""
    w, h = card.w, card.h
    card.defs.append(
        '<clipPath id="clip"><rect width="%d" height="%d" rx="%d"/></clipPath>'
        '<linearGradient id="brand" x1="0" y1="0" x2="1" y2="0">'
        '<stop offset="0" stop-color="%s"/><stop offset="1" stop-color="%s"/></linearGradient>'
        '<radialGradient id="g1" cx=".5" cy=".5" r=".5"><stop offset="0" stop-color="%s" stop-opacity=".16"/>'
        '<stop offset="1" stop-color="%s" stop-opacity="0"/></radialGradient>'
        '<radialGradient id="g2" cx=".5" cy=".5" r=".5"><stop offset="0" stop-color="%s" stop-opacity=".18"/>'
        '<stop offset="1" stop-color="%s" stop-opacity="0"/></radialGradient>'
        '<linearGradient id="edge" x1="0" y1="0" x2="1" y2="0">'
        '<stop offset="0" stop-color="%s" stop-opacity="0"/><stop offset=".25" stop-color="%s" stop-opacity=".9"/>'
        '<stop offset=".75" stop-color="%s" stop-opacity=".9"/><stop offset="1" stop-color="%s" stop-opacity="0"/>'
        '</linearGradient>' % (
            w, h, radius, C['cyan'], C['purple'],
            C[glow[0]], C[glow[0]], C[glow[1]], C[glow[1]],
            C['cyan'], C['cyan'], C['purple'], C['purple']))
    card.css.append('@keyframes tw{0%,100%{opacity:.15}50%{opacity:.9}}')
    rnd = random.Random(seed)
    dots = []
    for i in range(stars):
        x, y = rnd.uniform(6, w - 6), rnd.uniform(6, h - 6)
        r = rnd.choice([0.5, 0.6, 0.7, 0.8, 1.0, 1.2])
        o = rnd.uniform(0.15, 0.6)
        if i % 7 == 0:
            dots.append('<circle cx="%.1f" cy="%.1f" r="%s" fill="#fff" style="animation:tw %.1fs ease-in-out %.1fs infinite"/>'
                        % (x, y, _n(r + 0.3), rnd.uniform(2.5, 5.5), rnd.uniform(0, 3)))
        else:
            dots.append('<circle cx="%.1f" cy="%.1f" r="%s" fill="#fff" opacity="%.2f"/>' % (x, y, _n(r), o))
    card.add(
        '<g clip-path="url(#clip)">',
        '<rect width="%d" height="%d" fill="%s"/>' % (w, h, C['bg']),
        '<ellipse cx="%d" cy="%d" rx="%d" ry="%d" fill="url(#g1)"/>' % (w * 0.12, h * 0.1, w * 0.5, h * 0.9),
        '<ellipse cx="%d" cy="%d" rx="%d" ry="%d" fill="url(#g2)"/>' % (w * 0.9, h * 0.95, w * 0.55, h * 0.9),
        ''.join(dots),
        '</g>',
        '<rect x=".5" y=".5" width="%d" height="%d" rx="%d" fill="none" stroke="#fff" stroke-opacity=".09"/>' % (w - 1, h - 1, radius),
        '<rect x="%d" y="0" width="%d" height="1.5" fill="url(#edge)"/>' % (radius, w - 2 * radius),
    )


def label(card, x, y, main, rest='', color=None, anchor='start'):
    """The small mono kicker over every block: DEFADE · WHAT IT IS."""
    parts = [(main, color or C['cyan'], 'monob')]
    if rest:
        parts.append(('  ' + rest, C['faint'], 'mono'))
    return card.spans(x, y, parts, font='mono', size=11, ls=2.2, anchor=anchor)


def icon(svg, x, y, size, color=None):
    """Place a DFI icon (24-unit viewBox) at x, y."""
    inner = svg[svg.index('>') + 1:svg.rindex('</svg>')]
    head = svg[:svg.index('>')]
    stroke = color
    if stroke is None:
        i = head.find('stroke="')
        stroke = head[i + 8:head.index('"', i + 8)] if i >= 0 else C['cyan']
    if color:
        inner = inner.replace('fill="currentColor"', 'fill="%s"' % color)
    inner = inner.replace('currentColor', stroke)
    s = size / 24
    return ('<g transform="translate(%s %s) scale(%s)" fill="none" stroke="%s" stroke-width="2" '
            'stroke-linecap="round" stroke-linejoin="round">%s</g>' % (_n(x), _n(y), _n(s), stroke, inner))


def png_data(path, size=None):
    from PIL import Image
    im = Image.open(path).convert('RGBA')
    if size:
        im = im.resize((size, size), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, 'PNG', optimize=True)
    return 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode()


def load_dfi():
    with open(os.path.join(ROOT, 'src', 'dfi.json')) as f:
        return json.load(f)


# Chain marks, drawn as the site draws them (js/evm-ui.js); Robinhood and Arc
# are the site's own PNGs.
CHAINS = [
    ('solana', 'Solana', ['pump.fun', 'LaunchLab', 'Meteora DBC', 'Boop', 'MetaDAO']),
    ('ethereum', 'Ethereum', ['based.bid', 'Clanker', 'Doppler']),
    ('base', 'Base', ['Clanker', 'Zora', 'Flaunch', 'Virtuals', 'Doppler', 'based.bid', 'o1']),
    ('bsc', 'BSC', ['four.meme', 'flap.sh', 'Clanker', 'based.bid']),
    ('robinhood', 'Robinhood', ['Pons', 'Clank.trade', 'Pools.trade', 'Torch', 'Clanker', 'Doppler', 'based.bid', 'o1']),
    ('arc', 'Arc', ['Argus', 'Tolly', 'Minara', 'ubi.fun', 'Warp', 'Foci', 'Peach', 'Faze', 'based.bid', 'o1']),
    ('hyperevm', 'Hyperliquid', ['LiquidLaunch']),
]


def chain_mark(key, x, y, size, uid):
    s = size / 24
    g = '<g transform="translate(%s %s) scale(%s)">' % (_n(x), _n(y), _n(s))
    if key == 'solana':
        return (g + '<defs><linearGradient id="sol%s" x1="0" y1="1" x2="1" y2="0"><stop offset="0" stop-color="#9945FF"/>'
                '<stop offset="1" stop-color="#14F195"/></linearGradient></defs><path fill="url(#sol%s)" d="M5.2 16.2c.2-.2.5-.3.7-.3h15c.4 0 .6.5.3.8l-3 3c-.2.2-.5.3-.7.3h-15c-.4 0-.6-.5-.3-.8l3-3zM5.2 4.3c.2-.2.5-.3.7-.3h15c.4 0 .6.5.3.8l-3 3c-.2.2-.5.3-.7.3h-15c-.4 0-.6-.5-.3-.8l3-3zM18.5 10.2c-.2-.2-.5-.3-.7-.3h-15c-.4 0-.6.5-.3.8l3 3c.2.2.5.3.7.3h15c.4 0 .6-.5.3-.8l-3-3z"/></g>' % (uid, uid))
    if key == 'ethereum':
        return g + '<path fill="#8C9EFF" d="M12 1.5l6.2 10.3L12 15.5 5.8 11.8z"/><path fill="#8C9EFF" opacity=".65" d="M12 16.9l6.2-3.7L12 22.5l-6.2-9.3z"/></g>'
    if key == 'base':
        return g + '<circle cx="12" cy="12" r="10.5" fill="#0052FF"/><path fill="#fff" d="M12 20.6a8.6 8.6 0 100-17.2 8.6 8.6 0 00-8.55 7.5h11.3v2.2H3.45A8.6 8.6 0 0012 20.6z"/></g>'
    if key == 'bsc':
        return ('<g transform="translate(%s %s) scale(%s)"><path fill="#F0B90B" d="M12.116 14.404L16 10.52l3.886 3.886 2.26-2.26L16 6l-6.144 6.144 2.26 2.26zM6 16l2.26-2.26L10.52 16l-2.26 2.26L6 16zm6.116 1.596L16 21.48l3.886-3.886 2.26 2.259L16 26l-6.144-6.144-.003-.003 2.263-2.257zM21.48 16l2.26-2.26L26 16l-2.26 2.26L21.48 16zm-3.188-.002h.002v.002L16 18.294l-2.291-2.29-.004-.004.004-.003.401-.402.195-.195L16 13.706l2.293 2.293z"/></g>'
                % (_n(x), _n(y), _n(size / 32)))
    if key == 'hyperevm':
        return g + '<circle cx="12" cy="12" r="10.5" fill="#0B2A25"/><path fill="#97FCE4" d="M5.2 7.6c0-1.9 1.9-2.8 3.2-1.5l2.1 2.1c.8.8 2.2.8 3 0l2.1-2.1c1.3-1.3 3.2-.4 3.2 1.5v8.8c0 1.9-1.9 2.8-3.2 1.5l-2.1-2.1c-.8-.8-2.2-.8-3 0l-2.1 2.1c-1.3 1.3-3.2.4-3.2-1.5z"/></g>'
    # Robinhood and Arc: the site's PNG marks, in a circle.
    data = png_data(os.path.join(ROOT, 'src', key + '.png'), 64)
    return ('<clipPath id="cm%s"><circle cx="%s" cy="%s" r="%s"/></clipPath>'
            '<image xlink:href="%s" x="%s" y="%s" width="%s" height="%s" clip-path="url(#cm%s)"/>' % (
                uid, _n(x + size / 2), _n(y + size / 2), _n(size / 2), data, _n(x), _n(y), _n(size), _n(size), uid))


# ----------------------------------------------------------------- hero ---
#
# Canvas widths: a full-width card is 780 wide and a half-width one 386, so
# both draw close to 1:1 in a profile README (about 690 px on a laptop, 850
# on a wide screen) and the smallest text stays readable.

FULL, HALF = 780, 386


def hero(dfi):
    card = Card(FULL, 330, 'DeFade, the multi-chain memecoin analyzer',
                'Read the wallets, not the promises. A scan reads a token and lands on a rug pull probability.')
    frame(card, seed=7, stars=64)

    # A planet's edge along the bottom, as on the site's banner.
    card.defs.append(
        '<linearGradient id="rim" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="%s" stop-opacity="0"/>'
        '<stop offset=".3" stop-color="%s"/><stop offset=".7" stop-color="%s"/><stop offset="1" stop-color="%s" stop-opacity="0"/></linearGradient>'
        '<radialGradient id="atmo" cx=".5" cy="0" r=".6"><stop offset="0" stop-color="%s" stop-opacity=".22"/><stop offset="1" stop-color="%s" stop-opacity="0"/></radialGradient>'
        '<linearGradient id="tag" x1="32" y1="0" x2="300" y2="0" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="%s"/><stop offset="1" stop-color="%s"/></linearGradient>'
        '<linearGradient id="word" x1="100" y1="0" x2="280" y2="0" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="%s"/><stop offset="1" stop-color="%s"/></linearGradient>'
        '<clipPath id="logo"><rect x="32" y="32" width="56" height="56" rx="13"/></clipPath>'
        % (C['cyan'], C['cyan'], C['purple'], C['purple'], C['purple'], C['purple'],
           C['cyan'], C['purple'], C['cyan'], C['purple']))
    card.add('<g clip-path="url(#clip)"><ellipse cx="390" cy="1240" rx="960" ry="925" fill="url(#atmo)"/>'
             '<ellipse cx="390" cy="1240" rx="960" ry="925" fill="%s" stroke="url(#rim)" stroke-width="1.5"/></g>' % C['bg'])

    # Left: the mark, the name, the line.
    logo = png_data(os.path.join(ROOT, 'src', 'logo.png'), 168)
    card.add('<image xlink:href="%s" x="32" y="32" width="56" height="56" clip-path="url(#logo)"/>' % logo,
             '<rect x="32.5" y="32.5" width="55" height="55" rx="12.5" fill="none" stroke="#fff" stroke-opacity=".12"/>')
    card.add(card.text(100, 77, 'DeFade', 'display', 48, 'url(#word)', ls=-1.2))
    card.add(card.text(102, 99, 'MULTI-CHAIN MEMECOIN ANALYZER', 'mono', 10, C['dim'], ls=2.5))
    card.add(card.text(32, 158, 'Read the wallets,', 'sansb', 31, C['text'], ls=-0.7))
    card.add(card.text(32, 196, 'not the promises.', 'sansb', 31, 'url(#tag)', ls=-0.7))
    card.add(card.text(32, 229, 'Paste any token. Get its rug pull probability,', 'sans', 13.5, C['dim']))
    card.add(card.text(32, 248, 'and every wallet, funder and transaction', 'sans', 13.5, C['dim']))
    card.add(card.text(32, 267, 'behind it.', 'sans', 13.5, C['dim']))
    x = 32
    for i, (key, _, _) in enumerate(CHAINS):
        card.add(chain_mark(key, x, 286, 16, 'h%d' % i))
        x += 23
    card.add(card.text(x + 6, 299, 'SEVEN CHAINS', 'mono', 10, C['faint'], ls=1.6))

    # Right: a scan running. The contract is clean, the wallets are not.
    x0, y0, pw, ph = 398, 28, 354, 274
    card.add('<rect x="%d" y="%d" width="%d" height="%d" rx="16" fill="%s" stroke="#fff" stroke-opacity=".1"/>' % (x0, y0, pw, ph, C['panel']),
             '<rect x="%d" y="%d" width="%d" height="1" fill="url(#edge)" opacity=".6"/>' % (x0 + 16, y0, pw - 32))
    card.add(card.text(x0 + 18, y0 + 28, 'SCAN', 'monob', 10.5, C['faint'], ls=2))
    addr = '4kTn…pump'
    ax = x0 + 60
    card.add(card.text(ax, y0 + 28, addr, 'mono', 12.5, C['cyan']))
    aw = math.ceil(measure(addr, 'mono', 12.5)) + 2
    # The address types itself in: a cover slides off it, one character at a time.
    card.css.append(
        '@keyframes type{0%%,2%%{transform:translateX(0)}12%%,93%%{transform:translateX(%dpx)}94%%,100%%{transform:translateX(0)}}'
        '.type{animation:type 10s steps(%d,end) infinite}'
        '@keyframes blink{0%%,49%%{opacity:1}50%%,100%%{opacity:0}}'
        '.caret{animation:type 10s steps(%d,end) infinite}.caret rect{animation:blink 1s step-end infinite}'
        % (aw, len(addr), len(addr)))
    card.add('<rect class="type" x="%d" y="%d" width="%d" height="18" fill="%s"/>' % (ax - 1, y0 + 14, aw + 2, C['panel']))
    card.add('<g class="caret"><rect x="%d" y="%d" width="7" height="15" fill="%s" opacity=".85"/></g>' % (ax, y0 + 16, C['cyan']))
    card.add(card.text(x0 + pw - 18, y0 + 28, 'SOLANA · PUMP.FUN', 'mono', 10, C['faint'], 'end', ls=1))
    card.add('<rect x="%d" y="%d" width="%d" height="1" fill="#fff" fill-opacity=".08"/>' % (x0 + 18, y0 + 42, pw - 36))

    rows = [
        ('lock', 'Contract', 'mint, freeze revoked', C['green']),
        ('liquidity', 'Liquidity', 'burned', C['green']),
        ('bundle', 'Bundles', '38.4% at launch', C['red']),
        ('freshwallet', 'Fresh Wallets', '14 from one funder', C['red']),
        ('sniper', 'Snipers', '9 in the first 120 s', C['orange']),
        ('devtracker', 'Dev Wallet', 'behind 3 earlier rugs', C['red']),
    ]
    for i, (ic, name, finding, col) in enumerate(rows):
        y = y0 + 66 + i * 25.5
        cls = card.appear(1.5 + i * 0.42)
        fx = x0 + pw - 18
        card.add('<g class="%s">' % cls,
                 icon(dfi[ic], x0 + 18, y - 12, 15, C['dim']),
                 card.text(x0 + 42, y, name, 'sans', 13, C['text']),
                 '<circle cx="%s" cy="%s" r="3" fill="%s"/>' % (_n(fx - measure(finding, 'mono', 11.5) - 9), _n(y - 4), col),
                 card.text(fx, y, finding, 'mono', 11.5, col, 'end'),
                 '</g>')
    # A scan line sweeping down while the modules report.
    card.defs.append('<linearGradient id="sweep" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="%s" stop-opacity="0"/>'
                     '<stop offset="1" stop-color="%s" stop-opacity=".22"/></linearGradient>' % (C['cyan'], C['cyan']))
    card.css.append('@keyframes sweep{0%%,14%%{transform:translateY(0);opacity:0}16%%{opacity:1}42%%{transform:translateY(%dpx);opacity:1}45%%,100%%{transform:translateY(%dpx);opacity:0}}'
                    '.sweep{animation:sweep 10s linear infinite}' % (6 * 25.5, 6 * 25.5))
    card.add('<rect class="sweep" x="%d" y="%d" width="%d" height="23" fill="url(#sweep)" opacity="0"/>' % (x0 + 1, y0 + 43, pw - 2))

    # The verdict.
    yv = y0 + 218
    card.add('<rect x="%d" y="%d" width="%d" height="1" fill="#fff" fill-opacity=".08"/>' % (x0 + 18, yv - 12, pw - 36))
    score = 81
    card.add(card.text(x0 + 18, yv + 8, 'RUG PULL PROBABILITY', 'mono', 10, C['dim'], ls=1.6))
    v = card.appear(4.3, dx=0)
    card.add('<g class="%s">' % v, card.text(x0 + pw - 18, yv + 8, 'EXTREME RISK', 'monob', 11, C['extreme'], 'end', ls=1.4), '</g>')
    card.defs.append('<linearGradient id="hot" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="%s"/><stop offset="1" stop-color="%s"/></linearGradient>' % (C['orange'], C['extreme']))
    n = card.appear(4.3, dx=0)
    card.add('<g class="%s">' % n, card.text(x0 + 16, yv + 44, str(score), 'display', 34, 'url(#hot)'), '</g>')
    bx, bw, by = x0 + 70, pw - 88, yv + 24
    for lo, hi, _, col in BANDS:
        card.add('<rect x="%s" y="%d" width="%s" height="8" fill="%s" fill-opacity=".18"/>' % (
            _n(bx + bw * lo / 100), by, _n(bw * (hi - lo + 1) / 100 - 2), col))
    card.css.append('@keyframes fill{0%,43%{transform:scaleX(0)}55%,93%{transform:scaleX(1)}96%,100%{transform:scaleX(0)}}'
                    '.fill{transform-box:fill-box;transform-origin:left;animation:fill 10s cubic-bezier(.2,.7,.2,1) infinite}')
    card.add('<rect class="fill" x="%d" y="%d" width="%s" height="8" rx="2" fill="url(#hot)"/>' % (bx, by, _n(bw * score / 100)))
    card.add(card.text(bx, by + 21, '0', 'mono', 9.5, C['faint']),
             card.text(bx + bw * 0.45, by + 21, '45', 'mono', 9.5, C['faint'], 'middle'),
             card.text(bx + bw * 0.75, by + 21, '75', 'mono', 9.5, C['faint'], 'middle'),
             card.text(bx + bw, by + 21, '100', 'mono', 9.5, C['faint'], 'end'))
    card.save('hero.svg')


# ---------------------------------------------------------------- pulse ---

def fmt_int(n):
    return '{:,}'.format(int(n))


def pulse(live):
    tot, cur = live['survival']['totals'], live['survival']['current']
    card = Card(FULL, 296, 'DeFade live: rugged after our flag',
                'Tokens DeFade flagged first that collapsed later, out of every token flagged and tracked, '
                'and how many memecoins are still alive after an hour, a day, a week and a month.')
    frame(card, seed=11, stars=36, glow=('red', 'purple'))
    card.css.append('@keyframes pulse{0%,100%{opacity:1}50%{opacity:.25}}.live{animation:pulse 1.6s ease-in-out infinite}')
    card.add('<circle class="live" cx="34" cy="34" r="4" fill="%s"/>' % C['green'])
    card.add(label(card, 46, 38, 'LIVE FROM DEFADE.ORG', 'TRACK RECORD', C['green']))
    card.add(card.text(card.w - 28, 38, 'updated ' + live['stamp'], 'mono', 10.5, C['faint'], 'end'))

    # The headline: flagged first, collapsed later. The Survival page's figures, as it prints them.
    card.defs.append('<linearGradient id="big" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#ffffff"/>'
                     '<stop offset="1" stop-color="#ffc2d1"/></linearGradient>')
    card.add(card.text(30, 82, 'RUGGED AFTER OUR FLAG', 'mono', 11, C['dim'], ls=2))
    card.add(card.text(26, 144, fmt_int(tot['calledIt']), 'display', 66, 'url(#big)', ls=-1))
    card.add(card.text(30, 168, 'flagged first, collapsed later · every chain', 'mono', 10.5, C['faint']))

    # Tracked and flagged, then the funnel the three figures make, as the site draws it.
    for i, (val, what, col) in enumerate([(tot['tracked'], 'TOKENS TRACKED', '#e2e3f0'),
                                          (tot['flagged'], 'TOKENS FLAGGED', C['orange'])]):
        x = 30 + i * 150
        card.add(card.text(x, 198, what, 'mono', 9.5, C['dim'], ls=1.6))
        card.add(card.text(x, 221, fmt_int(val), 'monob', 19, col))
    bx, bw, by = 30, 312, 236
    card.css.append('@keyframes bar{from{transform:scaleX(0)}to{transform:scaleX(1)}}'
                    '.bar{transform-box:fill-box;transform-origin:left;animation:bar 1.4s cubic-bezier(.2,.7,.2,1) both}')
    card.add('<rect x="%d" y="%d" width="%d" height="9" rx="4.5" fill="#fff" fill-opacity=".14"/>' % (bx, by, bw))
    card.add('<rect class="bar" style="animation-delay:.2s" x="%d" y="%d" width="%s" height="9" rx="4.5" fill="%s"/>' % (
        bx, by, _n(bw * tot['flagged'] / tot['tracked']), C['orange']))
    card.add('<rect class="bar" style="animation-delay:.5s" x="%d" y="%d" width="%s" height="9" rx="4.5" fill="%s"/>' % (
        bx, by, _n(bw * tot['calledIt'] / tot['tracked']), C['red']))
    x = bx
    for what, dot in (('Tracked', '#5d6189'), ('Flagged', C['orange']), ('Rugged after our flag', C['red'])):
        card.add('<circle cx="%s" cy="%d" r="3.5" fill="%s"/>' % (_n(x + 4), by + 25, dot))
        card.add(card.text(x + 13, by + 29, what, 'mono', 10, C['dim']))
        x += measure(what, 'mono', 10) + 30
    card.add('<rect x="368" y="66" width="1" height="200" fill="#fff" fill-opacity=".08"/>')

    # The survival curve.
    pts = [('launch', 100.0), ('1 h', cur['survival_1h']), ('6 h', cur['survival_6h']),
           ('24 h', cur['survival_24h']), ('7 d', cur['survival_7d']), ('30 d', cur['survival_30d'])]
    month = int(round(float(cur['survival_30d'])))
    card.add(card.spans(394, 84, [('%d in 100' % month, C['cyan'], 'sansb'),
                                  (' memecoins are alive after a month', C['text'], None)], 'sansb', 15))
    card.add(card.text(394, 104, 'Half are dead within %s hours. Every memecoin the' % _n(round(float(cur['median_lifespan_hours']))),
                       'sans', 11.5, C['faint']))
    card.add(card.text(394, 119, 'Survival Tracker follows, from launch.', 'sans', 11.5, C['faint']))
    left, right, top, bottom = 424, 742, 152, 248
    xs = [left + (right - left) * i / (len(pts) - 1) for i in range(len(pts))]
    ys = [bottom - (bottom - top) * float(v) / 100 for _, v in pts]
    for g in (0, 50, 100):
        gy = bottom - (bottom - top) * g / 100
        card.add('<rect x="%d" y="%s" width="%d" height="1" fill="#fff" fill-opacity="%s"/>' % (left, _n(gy), right - left, '.1' if g == 0 else '.05'))
        card.add(card.text(left - 10, gy + 3.5, '%d%%' % g, 'mono', 9.5, C['faint'], 'end'))
    d = smooth_path(list(zip(xs, ys)))
    card.defs.append('<linearGradient id="area" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="%s" stop-opacity=".28"/>'
                     '<stop offset="1" stop-color="%s" stop-opacity="0"/></linearGradient>'
                     '<linearGradient id="line" x1="%d" y1="0" x2="%d" y2="0" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="%s"/><stop offset="1" stop-color="%s"/></linearGradient>'
                     % (C['purple'], C['purple'], left, right, C['cyan'], C['purple']))
    card.css.append('@keyframes draw{from{stroke-dashoffset:800}to{stroke-dashoffset:0}}'
                    '.draw{stroke-dasharray:800;animation:draw 2.4s cubic-bezier(.3,.6,.2,1) .3s both}'
                    '@keyframes rise{from{opacity:0}to{opacity:1}}.rise{animation:rise .8s ease-out 1.6s both}')
    card.add('<path class="rise" d="%s L%s %s L%s %s Z" fill="url(#area)"/>' % (d, _n(xs[-1]), bottom, _n(xs[0]), bottom))
    card.add('<path class="draw" d="%s" fill="none" stroke="url(#line)" stroke-width="2.5" stroke-linecap="round"/>' % d)
    for i, ((name, v), x, y) in enumerate(zip(pts, xs, ys)):
        card.add('<circle cx="%s" cy="%s" r="4" fill="%s" stroke="%s" stroke-width="2"/>' % (_n(x), _n(y), C['bg'], C['cyan'] if i < 3 else C['purple']))
        if i:
            card.add(card.text(x, y - 11, '%s%%' % _n(round(float(v), 1)), 'monob', 11, C['text'], 'middle'))
        card.add(card.text(x, bottom + 18, name, 'mono', 10, C['dim'], 'middle'))
    card.save('pulse.svg')


def smooth_path(p):
    """Monotone cubic through the points, so the curve never bulges past them."""
    n = len(p)
    dx = [p[i + 1][0] - p[i][0] for i in range(n - 1)]
    m = [(p[i + 1][1] - p[i][1]) / dx[i] for i in range(n - 1)]
    t = [m[0]] + [0 if m[i - 1] * m[i] <= 0 else (m[i - 1] + m[i]) / 2 for i in range(1, n - 1)] + [m[-1]]
    for i in range(n - 1):
        if m[i] == 0:
            t[i] = t[i + 1] = 0
            continue
        a, b = t[i] / m[i], t[i + 1] / m[i]
        h = a * a + b * b
        if h > 9:
            k = 3 / math.sqrt(h)
            t[i], t[i + 1] = k * a * m[i], k * b * m[i]
    d = 'M%s %s' % (_n(p[0][0]), _n(p[0][1]))
    for i in range(n - 1):
        h = dx[i] / 3
        d += ' C%s %s %s %s %s %s' % (_n(p[i][0] + h), _n(p[i][1] + t[i] * h), _n(p[i + 1][0] - h),
                                       _n(p[i + 1][1] - t[i + 1] * h), _n(p[i + 1][0]), _n(p[i + 1][1]))
    return d


# ------------------------------------------------------------- rug clock ---

def mix(a, b, t):
    a, b = [int(a[i:i + 2], 16) for i in (1, 3, 5)], [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return '#%02x%02x%02x' % tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def ramp(t):
    t = max(0.0, min(1.0, t))
    return mix(C['cyan'], C['purple'], t / 0.5) if t < 0.5 else mix(C['purple'], C['red'], (t - 0.5) / 0.5)


HALF_H = 446


def rug_clock(live):
    heat = live['heatmap']
    hours = heat['hourOfDay']
    card = Card(HALF, HALF_H, 'DeFade Rug Clock',
                'Scan activity and the share of new tokens scored high risk, for each hour of the day in UTC, over the last %d days.' % heat['days'])
    frame(card, seed=23, stars=30, glow=('purple', 'purple'))
    card.add(label(card, 24, 38, 'RUG CLOCK', '%d DAYS · UTC' % heat['days'], C['purple']))
    card.add(card.text(24, 66, 'When the risky launches land', 'sansb', 16))
    card.add(card.text(24, 86, 'Each hour: how busy scanning was, and how', 'sans', 11.5, C['faint']))
    card.add(card.text(24, 101, 'many new tokens scored high risk', 'sans', 11.5, C['faint']))

    cx, cy, r0, r1 = HALF // 2, 262, 44, 126
    shares = [h['highRisk'] for h in hours if h and h.get('highRisk') is not None]
    lo, hi = (min(shares), max(shares)) if shares else (0, 1)
    peak = max(range(24), key=lambda i: (hours[i] or {}).get('highRisk') or -1)
    for rr in (r0, (r0 + r1) / 2, r1):
        card.add('<circle cx="%d" cy="%d" r="%s" fill="none" stroke="#fff" stroke-opacity=".06"/>' % (cx, cy, _n(rr)))
    for h in range(0, 24, 6):
        a = math.radians(h * 15 - 90)
        card.add(card.text(cx + (r1 + 13) * math.cos(a), cy + (r1 + 13) * math.sin(a) + 3.5, '%02d' % h, 'mono', 10, C['faint'], 'middle'))
    card.css.append('@keyframes grow{from{transform:scale(.2);opacity:0}to{transform:scale(1);opacity:1}}'
                    '.w{transform-origin:%dpx %dpx;animation:grow .7s cubic-bezier(.2,.8,.2,1) both}' % (cx, cy))
    for i, hd in enumerate(hours):
        if not hd or hd.get('activity') is None:
            continue
        share = hd.get('highRisk')
        rr = r0 + 10 + (r1 - r0 - 10) * hd['activity'] / 100
        col = ramp((share - lo) / (hi - lo) if share is not None and hi > lo else 0.0)
        a0, a1 = math.radians(i * 15 - 90 + 1.2), math.radians((i + 1) * 15 - 90 - 1.2)
        pth = 'M%s %s L%s %s A%s %s 0 0 1 %s %s L%s %s A%s %s 0 0 0 %s %s Z' % (
            _n(cx + r0 * math.cos(a0)), _n(cy + r0 * math.sin(a0)),
            _n(cx + rr * math.cos(a0)), _n(cy + rr * math.sin(a0)), _n(rr), _n(rr),
            _n(cx + rr * math.cos(a1)), _n(cy + rr * math.sin(a1)),
            _n(cx + r0 * math.cos(a1)), _n(cy + r0 * math.sin(a1)), r0, r0,
            _n(cx + r0 * math.cos(a0)), _n(cy + r0 * math.sin(a0)))
        extra = ' stroke="#fff" stroke-width="1.5"' if i == peak else ''
        card.add('<path class="w" style="animation-delay:%.2fs" d="%s" fill="%s" fill-opacity="%s"%s/>' % (
            0.2 + i * 0.04, pth, col, '1' if i == peak else '.85', extra))
    # A radar hand, sweeping the dial the way a scan sweeps a token.
    card.defs.append('<linearGradient id="hand" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#fff" stop-opacity="0"/>'
                     '<stop offset="1" stop-color="#fff" stop-opacity=".5"/></linearGradient>')
    card.css.append('@keyframes spin{to{transform:rotate(360deg)}}.hand{transform-origin:%dpx %dpx;animation:spin 12s linear infinite}' % (cx, cy))
    card.add('<g class="hand"><rect x="%d" y="%s" width="%d" height="1.4" fill="url(#hand)"/></g>' % (cx + r0, _n(cy - 0.7), r1 - r0 + 4))
    card.add('<circle cx="%d" cy="%d" r="%d" fill="%s"/>' % (cx, cy, r0 - 4, C['bg']))
    pk = hours[peak] or {}
    card.add(card.text(cx, cy - 3, '%02d:00' % peak, 'display', 20, C['text'], 'middle'))
    card.add(card.text(cx, cy + 12, 'RISKIEST', 'mono', 8.5, C['faint'], 'middle', ls=1.4))
    card.add(card.text(cx, cy + 24, '%d%% high risk' % round(100 * (pk.get('highRisk') or 0)), 'mono', 8.5, C['red'], 'middle'))

    # Legend.
    ly = HALF_H - 22
    for k in range(5):
        card.add('<rect x="%d" y="%d" width="12" height="6" rx="1.5" fill="%s"/>' % (24 + k * 14, ly - 6, ramp(k / 4)))
    card.add(card.text(24 + 5 * 14 + 4, ly, 'fewer → more high risk', 'mono', 9.5, C['faint']))
    card.add(card.text(card.w - 24, ly, 'length: scans', 'mono', 9.5, C['faint'], 'end'))
    card.save('rug-clock.svg')


# ---------------------------------------------------------------- chains ---

def chains():
    card = Card(HALF, HALF_H, 'Seven chains, one UI', 'The chains and launchpads DeFade reads, all with the same modules.')
    frame(card, seed=31, stars=30, glow=('cyan', 'cyan'))
    card.add(label(card, 24, 38, 'COVERAGE', 'ONE UI'))
    card.add(card.text(24, 66, 'Every module, on every chain', 'sansb', 16))
    card.add(card.text(24, 86, 'The chain and the launchpad are read from', 'sans', 11.5, C['faint']))
    card.add(card.text(24, 101, 'the address. Nothing to pick.', 'sans', 11.5, C['faint']))
    for i, (key, name, pads) in enumerate(CHAINS):
        y = 120 + i * 42
        card.add('<rect x="16" y="%d" width="%d" height="38" rx="10" fill="#fff" fill-opacity="%s"/>' % (y, HALF - 32, '.035' if i % 2 == 0 else '0'))
        card.add(chain_mark(key, 26, y + 8, 22, 'c%d' % i))
        card.add(card.text(58, y + 17, name, 'sansb', 13.5, C['text']))
        shown, more = [], 0
        for p in pads:
            if measure(' · '.join(shown + [p]) + ' +9', 'mono', 9.5) > 236 and shown:
                more = len(pads) - len(shown)
                break
            shown.append(p)
        line = ' · '.join(shown) + (' +%d' % more if more else '')
        card.add(card.text(58, y + 31, line, 'mono', 9.5, C['dim']))
        card.add(card.text(HALF - 26, y + 18, '%d' % len(pads), 'display', 15, C['cyan'], 'end'))
        card.add(card.text(HALF - 26, y + 31, 'launchpad' + ('s' if len(pads) != 1 else ''), 'mono', 8.5, C['faint'], 'end'))
    card.save('chains.svg')


# --------------------------------------------------------------- modules ---

QUESTIONS = [
    ('whale', 'Who holds it?', ['Holder Distribution', 'Whale Alert', 'Top Holder History', 'Bubble Map', 'Holder Overlap', 'Wallet Overlap', 'Notable Holders']),
    ('bundle', 'How did it launch?', ['Bundle Detection', 'Historical Bundles', 'Token Snipers', 'Fee Fingerprint', 'Terminal']),
    ('freshwallet', 'Who is behind the wallets?', ['Fresh Wallets', 'Funding Origin', 'Sybil Bands', 'Holder Network', 'Cross-Funding Graph', 'Copy Trading', 'Signal Fusion', 'Wallet Reputation']),
    ('devtracker', 'What did the dev do?', ['Dev Wallet', 'Deployer Reputation', 'Exit Playbook', 'Wallet Profiler', 'Token Lifecycle']),
    ('exitliq', 'Can you get out?', ['Liquidity', 'Exit Liquidity', 'Insider Profit Pressure', 'Position Stress Test', 'Contract Safety']),
    ('smarttracker', 'What is the market saying?', ['Smart Money', 'Smart Money Signals', 'Social Sentiment']),
]
# 33 chips, and Rug Pull Probability drawn as the verdict under them: the 34
# modules on defade.org/modules.


def chip_rows(mods, width, size=10):
    """Lay the module chips out in rows that fit width: [(x offset, name, chip width)] per row."""
    rows, row, x = [], [], 0
    for m in mods:
        w = measure(m, 'mono', size) + 14
        if row and x + w > width:
            rows.append(row)
            row, x = [], 0
        row.append((x, m, w))
        x += w + 6
    rows.append(row)
    return rows


def modules(dfi):
    pad, gap, cols = 28, 12, 2
    tw = (FULL - 2 * pad - gap * (cols - 1)) / cols
    laid = [chip_rows(mods, tw - 32) for _, _, mods in QUESTIONS]
    heights = []
    for r in range(0, len(QUESTIONS), cols):
        n = max(len(laid[i]) for i in range(r, min(r + cols, len(QUESTIONS))))
        heights.append(52 + n * 24)
    top = 92
    verdict_y = top + sum(heights) + gap * (len(heights) - 1) + 40
    card = Card(FULL, verdict_y + 70, 'What a DeFade scan reads',
                '34 modules grouped by the six questions they answer, adding up to one rug pull probability from 0 to 100.')
    frame(card, seed=41, stars=50)
    card.add(label(card, pad, 38, 'WHAT A SCAN READS', '34 MODULES · SIX QUESTIONS'))
    card.add(card.text(pad, 68, 'The rug is not in the contract. It is in the wallets.', 'sansb', 17))
    y = top
    for r, h in enumerate(heights):
        for c in range(cols):
            i = r * cols + c
            if i >= len(QUESTIONS):
                break
            ic, q, _ = QUESTIONS[i]
            x = pad + c * (tw + gap)
            card.add('<rect x="%s" y="%d" width="%s" height="%d" rx="12" fill="#fff" fill-opacity=".035" stroke="#fff" stroke-opacity=".07"/>' % (_n(x), y, _n(tw), h))
            card.add(icon(dfi[ic], x + 16, y + 14, 17))
            card.add(card.text(x + 42, y + 28, q, 'sansb', 14, C['text']))
            for k, row in enumerate(laid[i]):
                cy = y + 54 + k * 24
                for ox, m, w in row:
                    cx = x + 16 + ox
                    card.add('<rect x="%s" y="%d" width="%s" height="19" rx="9.5" fill="%s" fill-opacity=".08" stroke="%s" stroke-opacity=".22"/>' % (
                        _n(cx), cy - 13, _n(w), C['cyan'], C['cyan']))
                    card.add(card.text(cx + 7, cy, m, 'mono', 10, C['dim']))
        y += h + gap

    # The verdict: where every finding lands.
    y = verdict_y
    card.add(card.text(pad, y, 'ONE NUMBER', 'monob', 10.5, C['purple'], ls=2))
    card.add(card.text(pad, y + 22, 'Rug pull probability, 0 to 100', 'sansb', 14))
    card.add(card.text(pad, y + 40, 'and every finding that moved it', 'sans', 11.5, C['faint']))
    bx, bw = 262, FULL - pad - 262
    for lo, hi, name, col in BANDS:
        x = bx + bw * lo / 100
        w = bw * (hi - lo + 1) / 100 - 4
        card.add('<rect x="%s" y="%d" width="%s" height="10" rx="3" fill="%s"/>' % (_n(x), y - 4, _n(w), col))
        words = name.split(' ')
        card.add(card.text(x, y + 22, words[0], 'monob', 9.5, col, ls=0.4))
        card.add(card.text(x, y + 35, words[1], 'monob', 9.5, col, ls=0.4))
        card.add(card.text(x, y + 50, '%d–%d' % (lo, hi), 'mono', 9.5, C['faint']))
    card.save('modules.svg')


# ----------------------------------------------------------------- pills ---

PILL_ICONS = {
    'web': '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 010 18M12 3a14 14 0 000 18"/>',
    'telegram': '<path d="M21 4L3 11l6 2.5M21 4l-3 16-9-6.5M21 4L9 13.5V19l3-3.5"/>',
    'phone': '<rect x="6" y="2.5" width="12" height="19" rx="2.5"/><path d="M11 18.5h2"/>',
    'ext': '<path d="M10 3.5a2 2 0 014 0V6h4v4h-1.5a2 2 0 000 4H18v4.5H6V14h1.5a2 2 0 000-4H6V6h4z"/>',
    'api': '<path d="M8 4c-2 0-3 1-3 3v2.5c0 1.2-.8 2.5-2 2.5 1.2 0 2 1.3 2 2.5V17c0 2 1 3 3 3M16 4c2 0 3 1 3 3v2.5c0 1.2.8 2.5 2 2.5-1.2 0-2 1.3-2 2.5V17c0 2-1 3-3 3"/>',
    'mcp': '<path d="M9 2.5v5M15 2.5v5M6.5 7.5h11V11a5.5 5.5 0 01-11 0zM12 16.5v5"/>',
}

PILLS = [
    ('scan', 'web', 'Scan a token', C['cyan']),
    ('telegram', 'telegram', 'Telegram bot', C['cyan']),
    ('apps', 'phone', 'iOS · Android', C['cyan']),
    ('extension', 'ext', 'Chrome extension', C['purple']),
    ('api', 'api', 'API · MCP', C['purple']),
]


def pills():
    for name, ic, text, col in PILLS:
        tw = measure(text, 'sansb', 12.5)
        w, h = int(math.ceil(tw + 48)), 34
        card = Card(w, h, text, text)
        card.add('<rect x=".5" y=".5" width="%d" height="%d" rx="%s" fill="%s" stroke="%s" stroke-opacity=".45"/>' % (
            w - 1, h - 1, _n((h - 1) / 2), C['panel'], col))
        card.add('<g transform="translate(13 9) scale(.67)" fill="none" stroke="%s" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round">%s</g>' % (col, PILL_ICONS[ic]))
        card.add(card.text(35, 21.5, text, 'sansb', 12.5, C['text']))
        card.save('pill-%s.svg' % name)


# The X mark (simple-icons, CC0), filled, on a 24-unit grid.
X_MARK = ('M18.901 1.153h3.68l-8.04 9.19L24 22.846h-7.406l-5.8-7.584-6.638 7.584H.474l8.6-9.83L0 1.154h7.594'
          'l5.243 6.932ZM17.61 20.644h2.039L6.486 3.24H4.298Z')


def byline():
    """The credit under the link pills: built by @dexbuilds, linked to the X account."""
    pre, handle = 'BUILT BY', '@dexbuilds'
    pw = measure(pre, 'mono', 10, 1.6)
    hw = measure(handle, 'sansb', 13)
    w, h = int(math.ceil(18 + pw + 10 + 14 + 7 + hw + 18)), 32
    card = Card(w, h, 'Built by @dexbuilds', 'Built by @dexbuilds on X')
    card.add('<rect x=".5" y=".5" width="%d" height="%d" rx="%s" fill="%s" stroke="#fff" stroke-opacity=".16"/>' % (
        w - 1, h - 1, _n((h - 1) / 2), C['panel']))
    card.add(card.text(18, 20, pre, 'mono', 10, C['dim'], ls=1.6))
    x = 18 + pw + 10
    card.add('<path transform="translate(%s 9.5) scale(%s)" fill="%s" d="%s"/>' % (_n(x), _n(13 / 24), C['text'], X_MARK))
    card.add(card.text(x + 14 + 7, 20.5, handle, 'sansb', 13, C['text']))
    card.save('byline.svg')


# ------------------------------------------------------------------ data ---

def fetch(path):
    req = urllib.request.Request(API + path, headers={'User-Agent': UA, 'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def live_data(offline):
    path = os.path.join(ROOT, 'data', 'live.json')
    old = None
    if os.path.exists(path):
        with open(path) as f:
            old = json.load(f)
    if offline:
        if not old:
            sys.exit('no data/live.json to draw from')
        return old
    try:
        surv = fetch('/api/survival/stats?chain=all')
        heat = fetch('/api/launch-heatmap?days=30')
        assert all(surv.get('totals', {}).get(k) for k in ('tracked', 'flagged', 'calledIt')), 'empty totals'
        assert surv.get('current', {}).get('survival_30d') is not None, 'empty survival stats'
        assert len(heat.get('hourOfDay') or []) == 24, 'empty heatmap'
    except Exception as e:  # noqa: BLE001 -- any failure keeps the last good figures
        print('live fetch failed (%s); drawing the last good figures' % e, file=sys.stderr)
        if not old:
            raise
        return old
    now = dt.datetime.now(dt.timezone.utc)
    live = {
        'stamp': now.strftime('%-d %b %Y'),
        'survival': {'totals': {k: surv['totals'][k] for k in ('tracked', 'flagged', 'calledIt')},
                     'current': {k: surv['current'][k] for k in (
                         'survival_1h', 'survival_6h', 'survival_24h', 'survival_7d', 'survival_30d',
                         'median_lifespan_hours')}},
        'heatmap': {'days': heat['days'], 'hourOfDay': heat['hourOfDay']},
    }
    with open(path, 'w') as f:
        json.dump(live, f, indent=1)
        f.write('\n')
    return live


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--offline', action='store_true', help='draw from data/live.json without fetching')
    ap.add_argument('--live-only', action='store_true', help='redraw only the cards with live figures')
    args = ap.parse_args()
    os.makedirs(ASSETS, exist_ok=True)
    live = live_data(args.offline)
    dfi = load_dfi()
    pulse(live)
    rug_clock(live)
    if not args.live_only:
        hero(dfi)
        chains()
        modules(dfi)
        pills()
        byline()


if __name__ == '__main__':
    main()
