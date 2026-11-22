"""Writes the three figures of docs/bitcoin-mining-v1.md as standalone SVG files.

Usage: python3 figures.py OUT_DIR
"""
import os, sys

STYLE = """<style>
text{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;fill:#444441}
.th{font-size:14px;font-weight:600}
.ts{font-size:12px}
.tl{font-size:12px;fill:#5f5e5a}
.search rect{fill:#e1f5ee;stroke:#0f6e56}.search text{fill:#04342c}
.quantum rect{fill:#eeedfe;stroke:#534ab7}.quantum text{fill:#26215c}
.classical rect{fill:#f1efe8;stroke:#5f5e5a}.classical text{fill:#2c2c2a}
.constant rect{fill:#ffffff;stroke:#888780;stroke-dasharray:4 3}.constant text{fill:#444441}
.result rect{fill:#faeeda;stroke:#854f0b}.result text{fill:#412402}
rect{stroke-width:1}
.arr{stroke:#5f5e5a;stroke-width:1.5;fill:none}
.leader{stroke:#888780;stroke-width:1;fill:none}
.rule{stroke:#d3d1c7;stroke-width:1}
</style>"""

ARROW = ('<defs><marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" '
         'orient="auto-start-reverse"><path d="M2 1L8 5L2 9" fill="none" stroke="#5f5e5a" stroke-width="1.5" '
         'stroke-linecap="round" stroke-linejoin="round"/></marker></defs>')


class Fig:
    def __init__(self, width, height, title, desc):
        self.w, self.h = width, height
        self.out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" '
                    f'height="{height}" role="img">', f'<title>{title}</title>', f'<desc>{desc}</desc>', STYLE, ARROW,
                    f'<rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="10" fill="#ffffff" stroke="#d3d1c7"/>']

    def box(self, kind, x, y, w, h, title=None, sub=None, rx=4, small=False):
        parts = [f'<g class="{kind}"><rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}"/>']
        cx = x + w / 2
        if title and sub:
            parts.append(f'<text class="th" x="{cx}" y="{y + h / 2 - 9}" text-anchor="middle" dominant-baseline="central">{title}</text>')
            parts.append(f'<text class="ts" x="{cx}" y="{y + h / 2 + 9}" text-anchor="middle" dominant-baseline="central">{sub}</text>')
        elif title:
            cls = 'ts' if small else 'th'
            parts.append(f'<text class="{cls}" x="{cx}" y="{y + h / 2}" text-anchor="middle" dominant-baseline="central">{title}</text>')
        parts.append('</g>')
        self.out.append(''.join(parts))

    def text(self, x, y, s, cls='tl', anchor='start'):
        self.out.append(f'<text class="{cls}" x="{x}" y="{y}" text-anchor="{anchor}" dominant-baseline="central">{s}</text>')

    def arrow(self, *points):
        d = 'M' + ' L'.join(f'{x} {y}' for x, y in points)
        self.out.append(f'<path d="{d}" class="arr" marker-end="url(#arrow)"/>')

    def line(self, x1, y1, x2, y2, cls='leader'):
        self.out.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" class="{cls}"/>')

    def legend(self, x, y, entries, step=22):
        for i, (kind, label) in enumerate(entries):
            self.out.append(f'<g class="{kind}"><rect x="{x}" y="{y + i * step}" width="14" height="14" rx="2"/></g>')
            self.text(x + 22, y + i * step + 7, label)

    def save(self, path):
        open(path, 'w').write('\n'.join(self.out) + '\n</svg>\n')


def merkle():
    f = Fig(680, 322, 'The merkle root of a usual block and of a coinbase-only block',
            'Left: in a usual block the transactions are hashed in pairs, level by level, down to one 32-byte merkle '
            'root that goes in the header. Right: in a block whose only transaction is the coinbase, the merkle root '
            'is the double SHA-256 of the coinbase, so there is no tree.')
    f.text(190, 26, 'A usual block', 'th', 'middle')
    f.box('quantum', 110, 46, 160, 50, 'Merkle root', '32 bytes, in the header', rx=8)
    f.box('quantum', 30, 146, 150, 50, 'Hash of 0 and 1', 'double SHA-256', rx=8)
    f.box('quantum', 200, 146, 150, 50, 'Hash of 2 and 3', 'double SHA-256', rx=8)
    xs = [22, 106, 190, 274]
    for x, kind, name in zip(xs, ['search', 'classical', 'classical', 'classical'], ['Coinbase', 'Tx 1', 'Tx 2', 'Tx 3']):
        f.box(kind, x, 246, 78, 44, name, rx=8, small=True)
    f.arrow((61, 246), (92, 202))
    f.arrow((145, 246), (118, 202))
    f.arrow((229, 246), (262, 202))
    f.arrow((313, 246), (288, 202))
    f.arrow((105, 146), (160, 102))
    f.arrow((275, 146), (220, 102))
    f.line(378, 20, 378, 302, 'rule')
    f.text(530, 26, 'A coinbase-only block: this problem', 'th', 'middle')
    f.box('quantum', 430, 46, 200, 50, 'Merkle root', '= the coinbase\'s id', rx=8)
    f.box('search', 430, 240, 200, 50, 'Coinbase', 'holds the extranonce', rx=8)
    f.arrow((530, 240), (530, 102))
    f.text(540, 162, 'double SHA-256,')
    f.text(540, 180, 'no tree')
    return f


def header():
    f = Fig(680, 420, 'The 80-byte block header across two SHA-256 blocks, drawn to scale',
            'The first 64-byte SHA-256 block holds the version, the previous block hash and the first 28 bytes of the '
            'merkle root. The second holds the last 4 bytes of the merkle root, the time, bits and the nonce, then 48 '
            'bytes of constant padding. The nonce is part of the search register, the merkle root is computed from '
            'the search register, and the other fields are classical inputs.')
    f.text(40, 28, 'Header, first block: bytes 0 to 63')
    f.box('classical', 40, 40, 37.5, 56)
    f.box('classical', 77.5, 40, 300, 56, 'prev_hash', '32 bytes')
    f.box('quantum', 377.5, 40, 262.5, 56, 'Merkle root', 'first 28 of its 32 bytes')
    f.line(59, 96, 59, 116)
    f.text(67, 120, 'version, 4 bytes')
    f.text(40, 164, 'Header, second block: bytes 64 to 79, then padding')
    f.box('quantum', 40, 176, 37.5, 56)
    f.box('classical', 77.5, 176, 37.5, 56)
    f.box('classical', 115, 176, 37.5, 56)
    f.box('search', 152.5, 176, 37.5, 56)
    f.box('constant', 190, 176, 450, 56, 'pad640', '48 bytes of SHA-256 padding, not part of the header')
    for x, y, label in ((171, 254, 'nonce, 4 bytes'), (134, 276, 'bits, 4 bytes: the target'), (96, 298, 'time, 4 bytes'),
                        (59, 320, 'Merkle root, last 4 bytes')):
        f.line(x, 232, x, y - 4)
        f.text(x + 8, y, label)
    f.legend(360, 262, [('search', 'Search register (qubits)'), ('quantum', 'Computed from the search register'),
                        ('classical', 'Classical input'), ('constant', 'Constant')])
    f.line(40, 352, 640, 352, 'rule')
    f.text(40, 376, 'Drawn to scale: each row is one 64-byte SHA-256 block.')
    f.text(40, 396, 'The other 6 bytes of the search register are in the coinbase, which the merkle root is the hash of.')
    return f


def oracle():
    f = Fig(680, 676, 'The five SHA-256 compressions of the Bitcoin mining oracle',
            'Compression 1 starts from the classical midstate and hashes the coinbase\'s last block: the extranonce '
            'and the tail. Compression 2 hashes that result again from the IV, giving the merkle root. The root\'s '
            'first 28 bytes join the version and previous hash in compression 3. Its last 4 bytes join the time, '
            'bits, the nonce and padding in compression 4, which starts from the output of compression 3. '
            'Compression 5 hashes that result again from the IV, giving the block hash. The mask is XORed into the '
            'hash, and the phase is flipped when the result is below the target that bits gives.')
    # Compression 1: the coinbase's last block.
    f.box('classical', 225, 24, 120, 28, 'midstate', small=True)
    f.arrow((285, 52), (285, 74))
    f.box('search', 52, 74, 150, 28, 'extranonce, 6 bytes', small=True)
    f.box('classical', 52, 102, 150, 28, 'tail, 58 bytes', small=True)
    f.arrow((202, 102), (224, 102))
    f.box('quantum', 230, 80, 110, 44, 'Compress 1', rx=8)
    f.arrow((340, 102), (366, 102))
    # Compression 2: the merkle root.
    f.box('quantum', 372, 88, 134, 28, 'inner1, 32 bytes', small=True)
    f.box('constant', 372, 116, 134, 28, 'pad256', small=True)
    f.arrow((506, 116), (524, 116))
    f.box('constant', 555, 40, 60, 28, 'IV', small=True)
    f.arrow((585, 68), (585, 88))
    f.box('quantum', 530, 94, 110, 44, 'Compress 2', rx=8)
    f.arrow((585, 138), (585, 172), (30, 172), (30, 356), (46, 356))
    f.arrow((30, 302), (46, 302))
    f.text(400, 160, 'root: the merkle root, 32 bytes', anchor='middle')
    # Compression 3: the header's first block.
    f.box('constant', 255, 198, 60, 28, 'IV', small=True)
    f.arrow((285, 226), (285, 246))
    f.box('classical', 52, 232, 150, 28, 'version, 4 bytes', small=True)
    f.box('classical', 52, 260, 150, 28, 'prev_hash, 32 bytes', small=True)
    f.box('quantum', 52, 288, 150, 28, 'root, bytes 0–27', small=True)
    f.arrow((202, 274), (224, 274))
    f.box('quantum', 230, 252, 110, 44, 'Compress 3', rx=8)
    f.arrow((285, 296), (285, 384))
    f.text(293, 340, 'mid')
    # Compression 4: the header's second block.
    f.box('quantum', 52, 342, 150, 28, 'root, bytes 28–31', small=True)
    f.box('classical', 52, 370, 150, 28, 'time, 4 bytes', small=True)
    f.box('classical', 52, 398, 150, 28, 'bits, 4 bytes', small=True)
    f.box('search', 52, 426, 150, 28, 'nonce, 4 bytes', small=True)
    f.box('constant', 52, 454, 150, 28, 'pad640', small=True)
    f.arrow((202, 412), (224, 412))
    f.box('quantum', 230, 390, 110, 44, 'Compress 4', rx=8)
    f.arrow((340, 412), (366, 412))
    # Compression 5: the block hash.
    f.box('quantum', 372, 398, 134, 28, 'inner2, 32 bytes', small=True)
    f.box('constant', 372, 426, 134, 28, 'pad256', small=True)
    f.arrow((506, 426), (524, 426))
    f.box('constant', 555, 350, 60, 28, 'IV', small=True)
    f.arrow((585, 378), (585, 398))
    f.box('quantum', 530, 404, 110, 44, 'Compress 5', rx=8)
    f.arrow((585, 448), (585, 496))
    f.text(593, 472, 'hash')
    # Mask and comparison.
    f.box('classical', 372, 516, 112, 28, 'mask, 12 bytes', small=True)
    f.arrow((484, 530), (504, 530))
    f.box('quantum', 510, 502, 150, 56, 'Masked hash', 'XOR into H5, H6, H7', rx=8)
    f.arrow((585, 558), (585, 590))
    f.box('classical', 372, 610, 112, 28, 'target, from bits', small=True)
    f.arrow((484, 624), (504, 624))
    f.box('result', 510, 596, 150, 56, 'Below the target?', 'then flip the phase', rx=8)
    f.legend(52, 548, [('search', 'Search register: 80 qubits'), ('quantum', 'Depends on the search register'),
                       ('classical', 'Classical input'), ('constant', 'Constant'), ('result', 'The answer, as a phase')])
    return f


if __name__ == '__main__':
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    for name, fig in (('merkle-root', merkle()), ('header', header()), ('oracle', oracle())):
        fig.save(os.path.join(out, f'bitcoin-mining-v1-{name}.svg'))
        print('wrote', name)
