#!/usr/bin/env python3
"""Draws the cards on github.com/DeFadeLtd.

Every card is a self-contained SVG in assets/: the fonts are subset to the
glyphs the card uses and embedded, the icons are inline, and nothing is
fetched when GitHub shows it. The cards wear defade.org's X-ray look: film
plates on a lightbox, the brand cyan, nothing round, condensed capitals and
a typewriter. Two cards carry live figures from the public pages of
defade.org (the Survival page's track record and survival curve, and the Rug
Clock); the workflow in .github/workflows/refresh.yml redraws them daily.
They show shares, never counts: the track record is the share of flagged
tokens that rugged after the flag, and data/live.json keeps only that.

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
import sys
import urllib.request
from collections import defaultdict

from fontTools import subset
from fontTools.ttLib import TTFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, 'assets')
API = 'https://api.defade.org'
UA = 'DeFade-profile/1.0 (+https://github.com/DeFadeLtd)'

# The X-ray look of defade.org (css/ui-xray.css): film on a lightbox, the
# brand cyan, nothing round, no gradients, condensed capitals for headings
# and a typewriter for labels.
C = {
    'bg': '#05080b',      # the page
    'film': '#0a151b',    # a film plate
    'line': '#1d2f37',    # a plate's edge
    'light': '#d6eaf0',   # the lightbox
    'tab': '#6f8790',     # the clip on top of a film
    'text': '#e8f3f6',
    'bone': '#d7eef5',
    'dim': '#a9bcc4',
    'faint': '#6f8790',
    'cyan': '#00d4ff',
    'green': '#4ade80',
    'yellow': '#f5c842',
    'orange': '#ff9f43',
    'amber': '#ffc24d',
    'red': '#ff4d5e',
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
    'display': ('BarlowCondensed-800.ttf', "'Barlow Condensed', 'Arial Narrow', sans-serif", 800),
    'sans': ('Barlow-500.ttf', "Barlow, 'Segoe UI', Helvetica, Arial, sans-serif", 500),
    'mono': ('CourierPrime-400.ttf', "'Courier Prime', 'Courier New', monospace", 400),
    'monob': ('CourierPrime-700.ttf', "'Courier Prime', 'Courier New', monospace", 700),
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


def word_path(s, key, x, y, width):
    """s as outlines, its advance stretched to width: the wordmark needs no
    font to load and can clip the hatching inside its letters."""
    from fontTools.pens.svgPathPen import SVGPathPen
    from fontTools.pens.transformPen import TransformPen
    tt = TTFont(font_path(key))
    gs, cmap, upm = tt.getGlyphSet(), tt.getBestCmap(), tt['head'].unitsPerEm
    adv = sum(tt['hmtx'][cmap[ord(ch)]][0] for ch in s)
    k = width / adv
    out, cx = [], 0
    for ch in s:
        name = cmap[ord(ch)]
        pen = SVGPathPen(gs)
        gs[name].draw(TransformPen(pen, (k, 0, 0, -k, x + cx * k, y)))
        out.append(pen.getCommands())
        cx += tt['hmtx'][name][0]
    return ' '.join(out), adv * k, (tt['OS/2'].sCapHeight or upm * 0.7) * k


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


def frame(card, rule=True):
    """Every card: a film plate with a hard edge, the cyan rule along its top
    (the site's scroll boxes and headers), faint scan lines across it."""
    w, h = card.w, card.h
    card.defs.append('<pattern id="grain" width="4" height="3" patternUnits="userSpaceOnUse">'
                     '<rect width="4" height="1" fill="#fff" fill-opacity=".018"/></pattern>')
    card.add('<rect width="%d" height="%d" fill="%s"/>' % (w, h, C['film']),
             '<rect width="%d" height="%d" fill="url(#grain)"/>' % (w, h),
             '<rect x=".5" y=".5" width="%d" height="%d" fill="none" stroke="%s"/>' % (w - 1, h - 1, C['line']))
    if rule:
        card.add('<rect width="%d" height="3" fill="%s"/>' % (w, C['cyan']))


def label(card, x, y, main, rest='', color=None, anchor='start'):
    """The typewritten kicker over every block: DEFADE · WHAT IT IS."""
    parts = [(main, color or C['cyan'], 'monob')]
    if rest:
        parts.append(('  ' + rest, C['faint'], 'mono'))
    return card.spans(x, y, parts, font='mono', size=11.5, ls=1.8, anchor=anchor)


def heading(card, x, y, s, size=22, fill=None, anchor='start'):
    """A heading as the X-ray pages set them: condensed, capitals."""
    return card.text(x, y, s.upper(), 'display', size, fill or C['text'], anchor, ls=0.3)


def lightbox(card, x, y, w, h):
    """A film on the lightbox: the light frame, the clip on top, the dark plate."""
    return ('<rect x="%s" y="%s" width="%s" height="%s" fill="%s"/>' % (_n(x), _n(y), _n(w), _n(h), C['light']) +
            '<rect x="%s" y="%s" width="%s" height="%s" fill="%s"/>' % (_n(x + 8), _n(y + 8), _n(w - 16), _n(h - 16), C['bg']) +
            '<rect x="%s" y="%s" width="%s" height="7" fill="%s"/>' % (_n(x + w * 0.35), _n(y), _n(w * 0.3), C['tab']))


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
            'stroke-linecap="square" stroke-linejoin="miter">%s</g>' % (_n(x), _n(y), _n(s), stroke, inner))


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
# are the site's own PNGs. The launchpads each chain's feed reads.
CHAINS = [
    ('solana', 'Solana', ['pump.fun', 'LaunchLab', 'Meteora DBC', 'Boop', 'MetaDAO']),
    ('ethereum', 'Ethereum', ['based.bid', 'Clanker', 'Doppler']),
    ('base', 'Base', ['Clanker', 'Zora', 'Flaunch', 'Virtuals', 'Doppler', 'based.bid', 'o1']),
    ('bsc', 'BSC', ['four.meme', 'flap.sh', 'Clanker', 'based.bid']),
    ('robinhood', 'Robinhood', ['Pons', 'Clank.trade', 'Pools.trade', 'Torch', 'Clanker', 'Doppler', 'based.bid', 'o1']),
    ('arc', 'Arc', ['Argus', 'Tolly', 'Minara', 'ubi.fun', 'Warp', 'Foci', 'Peach', 'Faze', 'based.bid', 'o1']),
    ('hyperevm', 'Hyperliquid', ['LiquidLaunch']),
    ('monad', 'Monad', ['nad.fun', 'flap.sh']),
]


def chain_mark(key, x, y, size, uid):
    s = size / 24
    g = '<g transform="translate(%s %s) scale(%s)">' % (_n(x), _n(y), _n(s))
    if key == 'solana':
        return (g + '<path fill="#14F195" d="M5.2 16.2c.2-.2.5-.3.7-.3h15c.4 0 .6.5.3.8l-3 3c-.2.2-.5.3-.7.3h-15c-.4 0-.6-.5-.3-.8l3-3z"/>'
                '<path fill="#9945FF" d="M5.2 4.3c.2-.2.5-.3.7-.3h15c.4 0 .6.5.3.8l-3 3c-.2.2-.5.3-.7.3h-15c-.4 0-.6-.5-.3-.8l3-3z"/>'
                '<path fill="#5fa3c8" d="M18.5 10.2c-.2-.2-.5-.3-.7-.3h-15c-.4 0-.6.5-.3.8l3 3c.2.2.5.3.7.3h15c.4 0 .6-.5.3-.8l-3-3z"/></g>')
    if key == 'ethereum':
        return g + '<path fill="#8C9EFF" d="M12 1.5l6.2 10.3L12 15.5 5.8 11.8z"/><path fill="#8C9EFF" opacity=".65" d="M12 16.9l6.2-3.7L12 22.5l-6.2-9.3z"/></g>'
    if key == 'base':
        return g + '<circle cx="12" cy="12" r="10.5" fill="#0052FF"/><path fill="#fff" d="M12 20.6a8.6 8.6 0 100-17.2 8.6 8.6 0 00-8.55 7.5h11.3v2.2H3.45A8.6 8.6 0 0012 20.6z"/></g>'
    if key == 'bsc':
        return ('<g transform="translate(%s %s) scale(%s)"><path fill="#F0B90B" d="M12.116 14.404L16 10.52l3.886 3.886 2.26-2.26L16 6l-6.144 6.144 2.26 2.26zM6 16l2.26-2.26L10.52 16l-2.26 2.26L6 16zm6.116 1.596L16 21.48l3.886-3.886 2.26 2.259L16 26l-6.144-6.144-.003-.003 2.263-2.257zM21.48 16l2.26-2.26L26 16l-2.26 2.26L21.48 16zm-3.188-.002h.002v.002L16 18.294l-2.291-2.29-.004-.004.004-.003.401-.402.195-.195L16 13.706l2.293 2.293z"/></g>'
                % (_n(x), _n(y), _n(size / 32)))
    if key == 'hyperevm':
        return g + '<circle cx="12" cy="12" r="10.5" fill="#0B2A25"/><path fill="#97FCE4" d="M5.2 7.6c0-1.9 1.9-2.8 3.2-1.5l2.1 2.1c.8.8 2.2.8 3 0l2.1-2.1c1.3-1.3 3.2-.4 3.2 1.5v8.8c0 1.9-1.9 2.8-3.2 1.5l-2.1-2.1c-.8-.8-2.2-.8-3 0l-2.1 2.1c-1.3 1.3-3.2.4-3.2-1.5z"/></g>'
    if key == 'monad':
        # The mark the site draws for Monad (js/evm-ui.js).
        return g + ('<circle cx="12" cy="12" r="11.2" fill="#836EF9"/><path fill="#fff" fill-rule="evenodd" d="M12 5.4C10.09 5.4 5.4 10.09 5.4 12C5.4 13.91 10.09 18.6 12 18.6C13.91 18.6 18.6 13.91 18.6 12C18.6 10.09 13.91 5.4 12 5.4ZM10.97 15.77C10.17 15.56 8.01 11.78 8.23 10.97C8.44 10.17 12.22 8.01 13.03 8.23C13.83 8.44 15.99 12.22 15.77 13.03C15.56 13.83 11.78 15.99 10.97 15.77Z"/></g>')
    # Robinhood and Arc: the site's PNG marks.
    data = png_data(os.path.join(ROOT, 'src', key + '.png'), 64)
    return '<image xlink:href="%s" x="%s" y="%s" width="%s" height="%s"/>' % (data, _n(x), _n(y), _n(size), _n(size))


CHAIN_WORD = ['NO', 'ONE', 'TWO', 'THREE', 'FOUR', 'FIVE', 'SIX', 'SEVEN', 'EIGHT', 'NINE', 'TEN']

# ----------------------------------------------------------------- hero ---
#
# Canvas widths: a full-width card is 780 wide and a half-width one 386, so
# both draw close to 1:1 in a profile README (about 690 px on a laptop, 850
# on a wide screen) and the smallest text stays readable.

FULL, HALF = 780, 386


def wordmark(card, x, y, width, uid):
    """DEFADE under the scan line, as the homepage draws it (js/ui-xray.js
    markSvg): solid and faint above the line, outlined and hatched below."""
    d, w, cap = word_path('DEFADE', 'display', x, y, width)
    top = y - cap
    scan = top + cap * 0.62
    card.defs.append('<clipPath id="wt%s"><rect x="0" y="0" width="%d" height="%s"/></clipPath>'
                     '<clipPath id="wb%s"><rect x="0" y="%s" width="%d" height="%d"/></clipPath>'
                     '<clipPath id="ww%s"><path d="%s"/></clipPath>' % (uid, card.w, _n(scan), uid, _n(scan), card.w, card.h, uid, d))
    hatch = ''.join('<line x1="%s" y1="%s" x2="%s" y2="%s"/>' % (_n(hx), _n(scan + 3), _n(hx + 3), _n(y + 2))
                    for hx in [x + i * 8.5 for i in range(int(w / 8.5) + 2)])
    card.add('<g clip-path="url(#wt%s)"><path d="%s" fill="%s" fill-opacity=".16"/></g>' % (uid, d, C['cyan']),
             '<g clip-path="url(#wb%s)"><path d="%s" fill="none" stroke="%s" stroke-opacity=".55" stroke-width="1.2"/>'
             '<g clip-path="url(#ww%s)" stroke="%s" stroke-opacity=".3" stroke-width="2">%s</g></g>' % (uid, d, C['cyan'], uid, C['bone'], hatch),
             '<rect x="%s" y="%s" width="%s" height="9" fill="%s" fill-opacity=".1"/>' % (_n(x - 8), _n(scan - 4.5), _n(w + 16), C['cyan']),
             '<rect x="%s" y="%s" width="%s" height="2" fill="%s"/>' % (_n(x - 8), _n(scan - 1), _n(w + 16), C['cyan']))
    return top, w


def hero(dfi):
    card = Card(FULL, 330, 'DEFADE, the multi-chain memecoin analyzer',
                'See through the token. A scan reads a token and lands on a rug pull probability.')
    frame(card)

    # Left: the name under the scan line, the headline, the line.
    wordmark(card, 32, 108, 330, 'h')
    card.add(card.spans(32, 152, [('SEE THROUGH THE ', C['text'], None), ('TOKEN.', C['cyan'], None)], 'display', 36, ls=0.2))
    card.add(card.text(32, 186, 'Paste any token. Get its rug pull probability,', 'sans', 14, C['dim']))
    card.add(card.text(32, 205, 'and every wallet, funder and transaction', 'sans', 14, C['dim']))
    card.add(card.text(32, 224, 'behind it.', 'sans', 14, C['dim']))
    x = 32
    for i, (key, _, _) in enumerate(CHAINS):
        card.add(chain_mark(key, x, 262, 16, 'h%d' % i))
        x += 23
    card.add(card.text(x + 6, 275, '%s CHAINS' % CHAIN_WORD[len(CHAINS)], 'mono', 11, C['faint'], ls=1.4))
    card.add(card.text(32, 306, 'MULTI-CHAIN MEMECOIN ANALYZER', 'mono', 10.5, C['faint'], ls=1.6))

    # Right: a scan running, on the lightbox. The contract is clean, the wallets are not.
    x0, y0, pw, ph = 398, 22, 360, 290
    card.add(lightbox(card, x0, y0, pw, ph))
    ix, iw = x0 + 8, pw - 16
    card.add(card.text(ix + 14, y0 + 34, 'SCAN', 'monob', 11, C['faint'], ls=1.6))
    addr = '4kTn…pump'
    ax = ix + 58
    card.add(card.text(ax, y0 + 34, addr, 'mono', 13, C['cyan']))
    aw = math.ceil(measure(addr, 'mono', 13)) + 2
    # The address types itself in: a cover slides off it, one character at a time.
    card.css.append(
        '@keyframes type{0%%,2%%{transform:translateX(0)}12%%,93%%{transform:translateX(%dpx)}94%%,100%%{transform:translateX(0)}}'
        '.type{animation:type 10s steps(%d,end) infinite}'
        '@keyframes blink{0%%,49%%{opacity:1}50%%,100%%{opacity:0}}'
        '.caret{animation:type 10s steps(%d,end) infinite}.caret rect{animation:blink 1s step-end infinite}'
        % (aw, len(addr), len(addr)))
    card.add('<rect class="type" x="%d" y="%d" width="%d" height="18" fill="%s"/>' % (ax - 1, y0 + 20, aw + 2, C['bg']))
    card.add('<g class="caret"><rect x="%d" y="%d" width="7" height="15" fill="%s" opacity=".85"/></g>' % (ax, y0 + 22, C['cyan']))
    card.add(card.text(ix + iw - 14, y0 + 34, 'SOLANA · PUMP.FUN', 'mono', 10.5, C['faint'], 'end'))
    card.add('<rect x="%d" y="%d" width="%d" height="1" fill="%s"/>' % (ix + 14, y0 + 46, iw - 28, C['line']))

    rows = [
        ('lock', 'CONTRACT', 'mint, freeze revoked', C['green']),
        ('liquidity', 'LIQUIDITY', 'burned', C['green']),
        ('bundle', 'BUNDLES', '38.4% at launch', C['red']),
        ('freshwallet', 'FRESH WALLETS', '14 from one funder', C['red']),
        ('sniper', 'SNIPERS', '9 in the first 120 s', C['amber']),
        ('devtracker', 'DEV WALLET', 'behind 3 earlier rugs', C['red']),
    ]
    for i, (ic, name, finding, col) in enumerate(rows):
        y = y0 + 70 + i * 24
        cls = card.appear(1.5 + i * 0.42)
        fx = ix + iw - 14
        card.add('<g class="%s">' % cls,
                 icon(dfi[ic], ix + 14, y - 12, 15, C['dim']),
                 card.text(ix + 38, y, name, 'display', 15, C['text'], ls=0.3),
                 '<rect x="%s" y="%s" width="6" height="6" fill="%s"/>' % (_n(fx - measure(finding, 'mono', 12) - 12), _n(y - 7), col),
                 card.text(fx, y, finding, 'mono', 12, col, 'end'),
                 '</g>')
    # The scan line sweeping down while the modules report.
    card.css.append('@keyframes sweep{0%%,14%%{transform:translateY(0);opacity:0}16%%{opacity:1}42%%{transform:translateY(%dpx);opacity:1}45%%,100%%{transform:translateY(%dpx);opacity:0}}'
                    '.sweep{animation:sweep 10s linear infinite}' % (6 * 24, 6 * 24))
    card.add('<g class="sweep" opacity="0"><rect x="%d" y="%d" width="%d" height="20" fill="%s" fill-opacity=".1"/>'
             '<rect x="%d" y="%d" width="%d" height="2" fill="%s"/></g>' % (ix, y0 + 50, iw, C['cyan'], ix, y0 + 69, iw, C['cyan']))

    # The verdict: the IMPRESSION, a hard box in its colour.
    yv = y0 + 212
    card.add('<rect x="%d" y="%d" width="%d" height="1" fill="%s"/>' % (ix + 14, yv - 10, iw - 28, C['line']))
    score = 81
    card.add(card.text(ix + 14, yv + 8, 'RUG PULL PROBABILITY', 'mono', 10.5, C['dim'], ls=1.2))
    v = card.appear(4.3, dx=0)
    bw_, bh_ = 128, 40
    bx_ = ix + iw - 14 - bw_
    card.add('<g class="%s">' % v,
             '<rect x="%d" y="%d" width="%d" height="%d" fill="%s" fill-opacity=".1" stroke="%s" stroke-width="2"/>' % (bx_, yv - 4, bw_, bh_, C['extreme'], C['extreme']),
             card.text(bx_ + 8, yv + 7, 'IMPRESSION', 'monob', 8, C['extreme'], ls=0.6),
             card.text(bx_ + 8, yv + 30, 'EXTREME RISK', 'display', 21, C['extreme'], ls=0.2),
             '</g>')
    n = card.appear(4.3, dx=0)
    card.add('<g class="%s">' % n, card.text(ix + 12, yv + 52, str(score), 'display', 40, C['extreme']), '</g>')
    bx, bw, by = ix + 60, iw - 74 - bw_ - 10, yv + 38
    for lo, hi, _, col in BANDS:
        card.add('<rect x="%s" y="%d" width="%s" height="8" fill="%s" fill-opacity=".22"/>' % (
            _n(bx + bw * lo / 100), by, _n(bw * (hi - lo + 1) / 100 - 2), col))
    card.css.append('@keyframes fill{0%,43%{transform:scaleX(0)}55%,93%{transform:scaleX(1)}96%,100%{transform:scaleX(0)}}'
                    '.fill{transform-box:fill-box;transform-origin:left;animation:fill 10s cubic-bezier(.2,.7,.2,1) infinite}')
    card.add('<rect class="fill" x="%d" y="%d" width="%s" height="8" fill="%s"/>' % (bx, by, _n(bw * score / 100), C['extreme']))
    card.add(card.text(bx, by + 21, '0', 'mono', 9.5, C['faint']),
             card.text(bx + bw, by + 21, '100', 'mono', 9.5, C['faint'], 'end'))
    card.save('hero.svg')


# ---------------------------------------------------------------- pulse ---

def pulse(live):
    cur = live['survival']['current']
    share = live['survival']['shares']['ruggedOfFlagged']
    card = Card(FULL, 280, 'DEFADE live: rugged after our flag',
                'The share of the tokens DEFADE flagged that collapsed later, and how many memecoins are still '
                'alive after an hour, a day, a week and a month.')
    frame(card)
    card.css.append('@keyframes pulse{0%,100%{opacity:1}50%{opacity:.25}}.live{animation:pulse 1.6s ease-in-out infinite}')
    card.add('<rect class="live" x="28" y="29" width="8" height="8" fill="%s"/>' % C['green'])
    card.add(label(card, 44, 38, 'LIVE FROM DEFADE.ORG', 'TRACK RECORD', C['green']))
    card.add(card.text(card.w - 28, 38, 'updated ' + live['stamp'], 'mono', 11, C['faint'], 'end'))

    # The headline: flagged first, collapsed later, as a share (owner,
    # 2026-11-02: no counts on any card).
    card.add(card.text(30, 84, 'RUGGED AFTER OUR FLAG', 'mono', 11.5, C['dim'], ls=1.6))
    pct = '%d%%' % round(share)
    card.add(card.text(26, 176, pct, 'display', 104, C['text'], ls=-1))
    card.add(card.text(30, 204, 'of the tokens we flagged collapsed after', 'mono', 11.5, C['faint']))
    card.add(card.text(30, 220, 'our flag · every chain', 'mono', 11.5, C['faint']))
    bx, bw, by = 30, 300, 240
    card.css.append('@keyframes bar{from{transform:scaleX(0)}to{transform:scaleX(1)}}'
                    '.bar{transform-box:fill-box;transform-origin:left;animation:bar 1.4s cubic-bezier(.2,.7,.2,1) both}')
    card.add('<rect x="%d" y="%d" width="%d" height="8" fill="%s" fill-opacity=".15"/>' % (bx, by, bw, C['bone']))
    card.add('<rect class="bar" style="animation-delay:.3s" x="%d" y="%d" width="%s" height="8" fill="%s"/>' % (
        bx, by, _n(bw * share / 100), C['red']))
    card.add('<rect x="368" y="66" width="1" height="186" fill="%s"/>' % C['line'])

    # The survival curve.
    pts = [('launch', 100.0), ('1 h', cur['survival_1h']), ('6 h', cur['survival_6h']),
           ('24 h', cur['survival_24h']), ('7 d', cur['survival_7d']), ('30 d', cur['survival_30d'])]
    month = int(round(float(cur['survival_30d'])))
    card.add(card.spans(394, 84, [('%d IN 100' % month, C['cyan'], None),
                                  (' MEMECOINS ARE ALIVE AFTER A MONTH', C['text'], None)], 'display', 19, ls=0.2))
    card.add(card.text(394, 104, 'Half are dead within %s hours. Every memecoin the' % _n(round(float(cur['median_lifespan_hours']))),
                       'sans', 12, C['faint']))
    card.add(card.text(394, 120, 'Survival Tracker follows, from launch.', 'sans', 12, C['faint']))
    left, right, top, bottom = 424, 742, 150, 236
    xs = [left + (right - left) * i / (len(pts) - 1) for i in range(len(pts))]
    ys = [bottom - (bottom - top) * float(v) / 100 for _, v in pts]
    for g in (0, 50, 100):
        gy = bottom - (bottom - top) * g / 100
        card.add('<rect x="%d" y="%s" width="%d" height="1" fill="%s" fill-opacity="%s"/>' % (left, _n(gy), right - left, C['bone'], '.2' if g == 0 else '.08'))
        card.add(card.text(left - 10, gy + 3.5, '%d%%' % g, 'mono', 10, C['faint'], 'end'))
    d = smooth_path(list(zip(xs, ys)))
    card.css.append('@keyframes draw{from{stroke-dashoffset:800}to{stroke-dashoffset:0}}'
                    '.draw{stroke-dasharray:800;animation:draw 2.4s cubic-bezier(.3,.6,.2,1) .3s both}')
    card.add('<path class="draw" d="%s" fill="none" stroke="%s" stroke-width="2.5"/>' % (d, C['cyan']))
    for i, ((name, v), x, y) in enumerate(zip(pts, xs, ys)):
        card.add('<rect x="%s" y="%s" width="8" height="8" fill="%s" stroke="%s" stroke-width="2"/>' % (_n(x - 4), _n(y - 4), C['film'], C['cyan']))
        if i:
            card.add(card.text(x, y - 11, '%s%%' % _n(round(float(v), 1)), 'monob', 11.5, C['text'], 'middle'))
        card.add(card.text(x, bottom + 18, name, 'mono', 10.5, C['dim'], 'middle'))
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
    """Fewer high-risk tokens to more: cyan, through the warning amber, to the alarm red."""
    t = max(0.0, min(1.0, t))
    return mix(C['cyan'], C['amber'], t / 0.5) if t < 0.5 else mix(C['amber'], C['red'], (t - 0.5) / 0.5)


HALF_H = 486


def rug_clock(live):
    heat = live['heatmap']
    hours = heat['hourOfDay']
    card = Card(HALF, HALF_H, 'DEFADE Rug Clock',
                'Scan activity and the share of new tokens scored high risk, for each hour of the day in UTC, over the last %d days.' % heat['days'])
    frame(card)
    card.add(label(card, 24, 38, 'RUG CLOCK', '%d DAYS · UTC' % heat['days']))
    card.add(heading(card, 24, 68, 'When the risky launches land', 22))
    card.add(card.text(24, 90, 'Each hour: how busy scanning was, and how', 'sans', 12, C['faint']))
    card.add(card.text(24, 106, 'many new tokens scored high risk', 'sans', 12, C['faint']))

    cx, cy, r0, r1 = HALF // 2, 286, 44, 130
    shares = [h['highRisk'] for h in hours if h and h.get('highRisk') is not None]
    lo, hi = (min(shares), max(shares)) if shares else (0, 1)
    peak = max(range(24), key=lambda i: (hours[i] or {}).get('highRisk') or -1)
    for rr in (r0, (r0 + r1) / 2, r1):
        card.add('<circle cx="%d" cy="%d" r="%s" fill="none" stroke="%s" stroke-opacity=".1"/>' % (cx, cy, _n(rr), C['bone']))
    for h in range(0, 24, 6):
        a = math.radians(h * 15 - 90)
        card.add(card.text(cx + (r1 + 14) * math.cos(a), cy + (r1 + 14) * math.sin(a) + 3.5, '%02d' % h, 'mono', 10.5, C['faint'], 'middle'))
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
        extra = ' stroke="#fff" stroke-width="2"' if i == peak else ''
        card.add('<path class="w" style="animation-delay:%.2fs" d="%s" fill="%s" fill-opacity="%s"%s/>' % (
            0.2 + i * 0.04, pth, col, '1' if i == peak else '.85', extra))
    # The scan line, sweeping the dial the way a scan sweeps a token.
    card.css.append('@keyframes spin{to{transform:rotate(360deg)}}.hand{transform-origin:%dpx %dpx;animation:spin 12s linear infinite}' % (cx, cy))
    card.add('<g class="hand"><rect x="%d" y="%s" width="%d" height="2" fill="%s"/></g>' % (cx + r0, _n(cy - 1), r1 - r0 + 6, C['cyan']))
    card.add('<circle cx="%d" cy="%d" r="%d" fill="%s"/>' % (cx, cy, r0 - 4, C['film']))
    pk = hours[peak] or {}
    card.add(card.text(cx, cy - 2, '%02d:00' % peak, 'display', 24, C['text'], 'middle'))
    card.add(card.text(cx, cy + 13, 'RISKIEST', 'mono', 9, C['faint'], 'middle', ls=1.2))
    card.add(card.text(cx, cy + 25, '%d%% high risk' % round(100 * (pk.get('highRisk') or 0)), 'mono', 9, C['red'], 'middle'))

    # Legend.
    ly = HALF_H - 22
    for k in range(5):
        card.add('<rect x="%d" y="%d" width="12" height="6" fill="%s"/>' % (24 + k * 14, ly - 6, ramp(k / 4)))
    card.add(card.text(24 + 5 * 14 + 4, ly, 'fewer to more high risk', 'mono', 10, C['faint']))
    card.add(card.text(card.w - 24, ly, 'length: scans', 'mono', 10, C['faint'], 'end'))
    card.save('rug-clock.svg')


# ---------------------------------------------------------------- chains ---

def chains():
    word = CHAIN_WORD[len(CHAINS)].capitalize()
    card = Card(HALF, HALF_H, '%s chains, one UI' % word, 'The chains and launchpads DEFADE reads, all with the same modules.')
    frame(card)
    card.add(label(card, 24, 38, 'COVERAGE', 'ONE UI'))
    card.add(heading(card, 24, 68, 'Every module, on every chain', 22))
    card.add(card.text(24, 90, 'The chain and the launchpad are read from', 'sans', 12, C['faint']))
    card.add(card.text(24, 106, 'the address. Nothing to pick.', 'sans', 12, C['faint']))
    for i, (key, name, pads) in enumerate(CHAINS):
        y = 122 + i * 43
        card.add('<rect x="16" y="%d" width="%d" height="39" fill="%s" fill-opacity="%s"/>' % (y, HALF - 32, C['bone'], '.05' if i % 2 == 0 else '0'))
        card.add(chain_mark(key, 26, y + 8, 22, 'c%d' % i))
        card.add(card.text(58, y + 18, name.upper(), 'display', 16, C['text'], ls=0.3))
        shown, more = [], 0
        for p in pads:
            if measure(' · '.join(shown + [p]) + ' +9', 'mono', 10) > 228 and shown:
                more = len(pads) - len(shown)
                break
            shown.append(p)
        line = ' · '.join(shown) + (' +%d' % more if more else '')
        card.add(card.text(58, y + 32, line, 'mono', 10, C['dim']))
        card.add(card.text(HALF - 26, y + 19, '%d' % len(pads), 'display', 18, C['cyan'], 'end'))
        card.add(card.text(HALF - 26, y + 32, 'launchpad' + ('s' if len(pads) != 1 else ''), 'mono', 9, C['faint'], 'end'))
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


def chip_rows(mods, width, size=10.5):
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
        heights.append(54 + n * 25)
    top = 96
    verdict_y = top + sum(heights) + gap * (len(heights) - 1) + 42
    card = Card(FULL, verdict_y + 72, 'What a DEFADE scan reads',
                '34 modules grouped by the six questions they answer, adding up to one rug pull probability from 0 to 100.')
    frame(card)
    card.add(label(card, pad, 38, 'WHAT A SCAN READS', '34 MODULES · SIX QUESTIONS'))
    card.add(heading(card, pad, 72, 'The rug is not in the contract. It is in the wallets.', 25))
    y = top
    for r, h in enumerate(heights):
        for c in range(cols):
            i = r * cols + c
            if i >= len(QUESTIONS):
                break
            ic, q, _ = QUESTIONS[i]
            x = pad + c * (tw + gap)
            card.add('<rect x="%s" y="%d" width="%s" height="%d" fill="%s" stroke="%s"/>' % (_n(x), y, _n(tw), h, C['bg'], C['line']),
                     '<rect x="%s" y="%d" width="3" height="%d" fill="%s"/>' % (_n(x), y, h, C['cyan']))
            card.add(icon(dfi[ic], x + 16, y + 14, 17, C['cyan']))
            card.add(heading(card, x + 42, y + 30, q, 18))
            for k, row in enumerate(laid[i]):
                cy = y + 56 + k * 25
                for ox, m, w in row:
                    cx = x + 16 + ox
                    card.add('<rect x="%s" y="%d" width="%s" height="19" fill="none" stroke="%s" stroke-opacity=".3"/>' % (
                        _n(cx), cy - 13, _n(w), C['bone']))
                    card.add(card.text(cx + 7, cy + 1, m, 'mono', 10.5, C['dim']))
        y += h + gap

    # The verdict: where every finding lands.
    y = verdict_y
    card.add(card.text(pad, y, 'ONE NUMBER', 'monob', 11, C['cyan'], ls=1.6))
    card.add(heading(card, pad, y + 24, 'Rug pull probability, 0 to 100', 19))
    card.add(card.text(pad, y + 42, 'and every finding that moved it', 'sans', 12, C['faint']))
    bx, bw = 300, FULL - pad - 300
    for lo, hi, name, col in BANDS:
        x = bx + bw * lo / 100
        w = bw * (hi - lo + 1) / 100 - 4
        card.add('<rect x="%s" y="%d" width="%s" height="10" fill="%s"/>' % (_n(x), y - 4, _n(w), col))
        words = name.split(' ')
        card.add(card.text(x, y + 24, words[0], 'display', 14, col, ls=0.3))
        card.add(card.text(x, y + 39, words[1], 'display', 14, col, ls=0.3))
        card.add(card.text(x, y + 54, '%d–%d' % (lo, hi), 'mono', 10, C['faint']))
    card.save('modules.svg')


# ----------------------------------------------------------------- pills ---

PILL_ICONS = {
    'web': '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 010 18M12 3a14 14 0 000 18"/>',
    'telegram': '<path d="M21 4L3 11l6 2.5M21 4l-3 16-9-6.5M21 4L9 13.5V19l3-3.5"/>',
    'phone': '<rect x="6" y="2.5" width="12" height="19"/><path d="M11 18.5h2"/>',
    'ext': '<path d="M10 3.5a2 2 0 014 0V6h4v4h-1.5a2 2 0 000 4H18v4.5H6V14h1.5a2 2 0 000-4H6V6h4z"/>',
    'api': '<path d="M8 4c-2 0-3 1-3 3v2.5c0 1.2-.8 2.5-2 2.5 1.2 0 2 1.3 2 2.5V17c0 2 1 3 3 3M16 4c2 0 3 1 3 3v2.5c0 1.2.8 2.5 2 2.5-1.2 0-2 1.3-2 2.5V17c0 2-1 3-3 3"/>',
}

# The first pill is the site's own SCAN button: solid cyan. The rest are keys
# outlined on the film.
PILLS = [
    ('scan', 'web', 'Scan a token', True),
    ('telegram', 'telegram', 'Telegram bot', False),
    ('apps', 'phone', 'iOS · Android', False),
    ('extension', 'ext', 'Chrome extension', False),
    ('api', 'api', 'API · MCP', False),
]


def pills():
    for name, ic, text, solid in PILLS:
        t = text.upper()
        tw = measure(t, 'display', 15, 0.4)
        w, h = int(math.ceil(tw + 50)), 34
        card = Card(w, h, text, text)
        fg = C['bg'] if solid else C['text']
        card.add('<rect x=".5" y=".5" width="%d" height="%d" fill="%s" stroke="%s"/>' % (
            w - 1, h - 1, C['cyan'] if solid else C['film'], C['cyan']))
        card.add('<g transform="translate(14 9) scale(.67)" fill="none" stroke="%s" stroke-width="2.3" stroke-linecap="square" stroke-linejoin="miter">%s</g>' % (
            fg if solid else C['cyan'], PILL_ICONS[ic]))
        card.add(card.text(37, 22.5, t, 'display', 15, fg, ls=0.4))
        card.save('pill-%s.svg' % name)


# The X mark (simple-icons, CC0), filled, on a 24-unit grid.
X_MARK = ('M18.901 1.153h3.68l-8.04 9.19L24 22.846h-7.406l-5.8-7.584-6.638 7.584H.474l8.6-9.83L0 1.154h7.594'
          'l5.243 6.932ZM17.61 20.644h2.039L6.486 3.24H4.298Z')


def byline():
    """The credit under the link pills: built by @dexbuilds, linked to the X account."""
    pre, handle = 'BUILT BY', '@dexbuilds'
    pw = measure(pre, 'mono', 10.5, 1.4)
    hw = measure(handle, 'monob', 13)
    w, h = int(math.ceil(18 + pw + 10 + 14 + 7 + hw + 18)), 32
    card = Card(w, h, 'Built by @dexbuilds', 'Built by @dexbuilds on X')
    card.add('<rect x=".5" y=".5" width="%d" height="%d" fill="%s" stroke="%s"/>' % (w - 1, h - 1, C['film'], C['line']))
    card.add(card.text(18, 20.5, pre, 'mono', 10.5, C['dim'], ls=1.4))
    x = 18 + pw + 10
    card.add('<path transform="translate(%s 9.5) scale(%s)" fill="%s" d="%s"/>' % (_n(x), _n(13 / 24), C['text'], X_MARK))
    card.add(card.text(x + 14 + 7, 21, handle, 'monob', 13, C['text']))
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
        # A file written before the cards dropped their counts: keep the
        # share, drop the counts.
        tot = old.get('survival', {}).pop('totals', None)
        if tot and 'shares' not in old['survival']:
            old['survival']['shares'] = {'ruggedOfFlagged': round(100 * tot['calledIt'] / tot['flagged'], 1)}
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
        'survival': {'shares': {'ruggedOfFlagged': round(100 * surv['totals']['calledIt'] / surv['totals']['flagged'], 1)},
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
