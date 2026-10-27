"""Static SVG charts for the DORA report, written with the standard library only.

Byte-stable output, so CI can regenerate the charts and compare them with the committed files.
Light and dark colors switch with the viewer's color scheme. Every chart in the report has a
table with the same numbers below it, so no value depends on reading a color.
"""

from __future__ import annotations

from collections.abc import Callable
from html import escape

WIDTH = 720
FONT = "system-ui, -apple-system, 'Segoe UI', sans-serif"

STYLE = """
svg { --surface: #fcfcfb; --ink: #0b0b0b; --ink-2: #52514e; --muted: #898781;
  --grid: #e1e0d9; --axis: #c3c2b7; --s1: #2a78d6; --s2: #eb6834; --dim: #c3c2b7; }
@media (prefers-color-scheme: dark) {
  svg { --surface: #1a1a19; --ink: #f0efec; --ink-2: #c3c2b7; --muted: #898781;
    --grid: #2c2c2a; --axis: #383835; --s1: #3987e5; --s2: #d95926; --dim: #4a4a46; }
}
text { font-family: FONT; fill: var(--ink-2); font-size: 12px; }
.title { fill: var(--ink); font-size: 15px; font-weight: 600; }
.value { fill: var(--ink); font-variant-numeric: tabular-nums; }
.tick { fill: var(--muted); font-size: 11px; font-variant-numeric: tabular-nums; }
.grid { stroke: var(--grid); stroke-width: 1; }
.axis { stroke: var(--axis); stroke-width: 1; }
.ref { stroke: var(--ink-2); stroke-width: 1; }
""".replace("FONT", FONT)


def _num(x: float) -> str:
    return f"{x:.1f}".rstrip("0").rstrip(".")


def _svg(height: int, title: str, desc: str, body: list[str]) -> str:
    return "\n".join(
        [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{height}" '
            f'viewBox="0 0 {WIDTH} {height}" role="img">',
            f"<title>{escape(title)}</title>",
            f"<desc>{escape(desc)}</desc>",
            f"<style>{STYLE}</style>",
            f'<rect width="{WIDTH}" height="{height}" rx="8" fill="var(--surface)"/>',
            f'<text class="title" x="20" y="30">{escape(title)}</text>',
            *body,
            "</svg>",
            "",
        ]
    )


def _column(x: float, y: float, w: float, h: float, color: str) -> str:
    """A column with a 4px rounded top, square at the baseline."""
    if h <= 0:
        return ""
    r = min(4, h, w / 2)
    b = y + h
    return (
        f'<path fill="var({color})" d="M{_num(x)},{_num(b)} V{_num(y + r)} '
        f"Q{_num(x)},{_num(y)} {_num(x + r)},{_num(y)} H{_num(x + w - r)} "
        f'Q{_num(x + w)},{_num(y)} {_num(x + w)},{_num(y + r)} V{_num(b)} Z"/>'
    )


def _bar(x: float, y: float, w: float, h: float, color: str) -> str:
    """A horizontal bar with a 4px rounded end, square at the baseline."""
    if w <= 0:
        return ""
    r = min(4, w, h / 2)
    e = x + w
    return (
        f'<path fill="var({color})" d="M{_num(x)},{_num(y)} H{_num(e - r)} '
        f"Q{_num(e)},{_num(y)} {_num(e)},{_num(y + r)} V{_num(y + h - r)} "
        f'Q{_num(e)},{_num(y + h)} {_num(e - r)},{_num(y + h)} H{_num(x)} Z"/>'
    )


def _nice_max(v: float, steps: int = 4) -> tuple[float, float]:
    raw = max(v, 1e-9) / steps
    mag = 10 ** len(str(int(raw))) / 10 if raw >= 1 else 1
    for m in (1, 2, 2.5, 5, 10):
        step = m * mag
        if step >= raw:
            return step * steps, step
    return v, v / steps


def columns(
    title: str,
    desc: str,
    labels: list[str],
    values: list[float],
    *,
    fmt: Callable[[float], str] = _num,
    ref: tuple[float, str] | None = None,
    brackets: list[tuple[int, int, str]] | None = None,
) -> str:
    """Column chart, one series. `ref` draws a labelled reference line; `brackets` group
    columns under a caption (first index, last index, text)."""
    left, right, top, plot_h = 48, 20, 56, 220
    top_value = max([*values, ref[0] if ref else 0])
    ymax, step = _nice_max(top_value * 1.12)
    plot_w = WIDTH - left - right
    slot = plot_w / len(labels)
    bar_w = min(24, slot - 2)
    base = top + plot_h

    def y(v: float) -> float:
        return base - v / ymax * plot_h

    body = []
    tick = 0.0
    while tick <= ymax + 1e-9:
        body.append(
            f'<line class="grid" x1="{left}" x2="{WIDTH - right}" y1="{_num(y(tick))}" '
            f'y2="{_num(y(tick))}"/>'
        )
        body.append(
            f'<text class="tick" x="{left - 8}" y="{_num(y(tick) + 4)}" '
            f'text-anchor="end">{fmt(tick)}</text>'
        )
        tick += step
    for i, (label, v) in enumerate(zip(labels, values, strict=True)):
        cx = left + slot * (i + 0.5)
        body.append(_column(cx - bar_w / 2, y(v), bar_w, base - y(v), "--s1"))
        body.append(
            f'<text class="value" x="{_num(cx)}" y="{_num(y(v) - 6)}" '
            f'text-anchor="middle">{fmt(v)}</text>'
        )
        body.append(
            f'<text class="tick" x="{_num(cx)}" y="{base + 18}" '
            f'text-anchor="middle">{escape(label)}</text>'
        )
    body.append(f'<line class="axis" x1="{left}" x2="{WIDTH - right}" y1="{base}" y2="{base}"/>')
    if ref:
        ry = _num(y(ref[0]))
        body.append(f'<line class="ref" x1="{left}" x2="{WIDTH - right}" y1="{ry}" y2="{ry}"/>')
        body.append(
            f'<text x="{WIDTH - right}" y="{_num(y(ref[0]) - 6)}" '
            f'text-anchor="end">{escape(ref[1])}</text>'
        )
    height = base + 40
    for first, last, text in brackets or []:
        x1, x2 = left + slot * first + 4, left + slot * (last + 1) - 4
        by = base + 32
        body.append(
            f'<path class="axis" fill="none" d="M{_num(x1)},{by - 4} V{by} H{_num(x2)} V{by - 4}"/>'
        )
        body.append(
            f'<text x="{_num((x1 + x2) / 2)}" y="{by + 16}" '
            f'text-anchor="middle">{escape(text)}</text>'
        )
        height = base + 64
    return _svg(height, title, desc, body)


def bars(
    title: str,
    desc: str,
    rows: list[tuple[str, float, str]],
    *,
    fmt: Callable[[float], str] = _num,
    refs: list[tuple[float, str]] | None = None,
    legend: list[tuple[str, str]] | None = None,
    label_w: int = 230,
    tick_fmt: Callable[[float], str] | None = None,
) -> str:
    """Horizontal bars. Each row is (label, value, color token: --s1, --s2 or --dim)."""
    left, right, top, row_h, bar_h = 20 + label_w, 70, 56, 30, 18
    if legend:
        top += 24
    ymax, step = _nice_max(max([0, *(v for _, v, _ in rows), *(r for r, _ in refs or [])]) * 1.05)
    plot_w = WIDTH - left - right
    bottom = top + row_h * len(rows)

    def x(v: float) -> float:
        return left + v / ymax * plot_w

    body = []
    if legend:
        lx = 20
        for text, color in legend:
            body.append(
                f'<rect x="{lx}" y="{top - 30}" width="10" height="10" rx="2" fill="var({color})"/>'
            )
            body.append(f'<text x="{lx + 16}" y="{top - 21}">{escape(text)}</text>')
            lx += 24 + 7 * len(text)
    tick = 0.0
    while tick <= ymax + 1e-9:
        body.append(
            f'<line class="grid" x1="{_num(x(tick))}" x2="{_num(x(tick))}" '
            f'y1="{top - 4}" y2="{bottom}"/>'
        )
        body.append(
            f'<text class="tick" x="{_num(x(tick))}" y="{bottom + 16}" '
            f'text-anchor="middle">{(tick_fmt or fmt)(tick)}</text>'
        )
        tick += step
    for i, (label, v, color) in enumerate(rows):
        y = top + i * row_h + (row_h - bar_h) / 2
        body.append(
            f'<text x="{left - 10}" y="{_num(y + bar_h / 2 + 4)}" '
            f'text-anchor="end">{escape(label)}</text>'
        )
        body.append(_bar(left, y, x(v) - left, bar_h, color))
        body.append(
            f'<text class="value" x="{_num(x(v) + 6)}" y="{_num(y + bar_h / 2 + 4)}">'
            f"{fmt(v)}</text>"
        )
    body.append(f'<line class="axis" x1="{left}" x2="{left}" y1="{top - 4}" y2="{bottom}"/>')
    for value, text in refs or []:
        rx = _num(x(value))
        body.append(f'<line class="ref" x1="{rx}" x2="{rx}" y1="{top - 8}" y2="{bottom}"/>')
        body.append(f'<text x="{_num(x(value) + 4)}" y="{top - 12}">{escape(text)}</text>')
    return _svg(bottom + 34, title, desc, body)
