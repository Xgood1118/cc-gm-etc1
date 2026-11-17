# -*- coding: utf-8 -*-
"""ETC1 块编解码。

把 4x4 RGB 像素块编成 8 字节 (64 位) ETC1 块，并能独立解回近似像素。

位布局 (高 32 位在前，大端)::

    individual   (diff=0): R1[4] R2[4] G1[4] G2[4] B1[4] B2[4] T1[3] T2[3] diff flip
    differential (diff=1): R1[5] dR[3] G1[5] dG[3] B1[5] dB[3] T1[3] T2[3] diff flip

低 32 位为 16 个像素各 2 位的修正项码字 (先 16 个 MSB，再 16 个 LSB)，
像素按行优先编号 0..15。flip=0 左右分块 (x<2 为子块 0)，flip=1 上下分块
(y<2 为子块 0)。alpha 通道不参与编码，解码结果恒为 RGB 三元组。
"""

from dataclasses import dataclass
from itertools import product

__all__ = [
    "Block",
    "encode_block",
    "decode_block",
    "block_error",
    "block_mode",
    "MODIFIER_TABLES",
    "MODE_INDIVIDUAL",
    "MODE_DIFFERENTIAL",
    "MODE_AUTO",
]

MODE_INDIVIDUAL = "individual"
MODE_DIFFERENTIAL = "differential"
MODE_AUTO = "auto"

#: ETC1 修正表：每项 (a, b)，码字 0..3 对应修正量 (-a, -b, +a, +b)。
MODIFIER_TABLES = (
    (2, 8),
    (5, 17),
    (9, 29),
    (13, 42),
    (18, 60),
    (24, 80),
    (33, 106),
    (47, 183),
)


@dataclass
class Block:
    """4x4 像素块。"""
    pixels: list
    mode: str = "individual"


# ---------------------------------------------------------------- 基础工具

def _clamp8(v):
    return 0 if v < 0 else 255 if v > 255 else v


def _expand4(v):
    """4 位基色扩展到 8 位。"""
    return (v << 4) | v


def _expand5(v):
    """5 位基色扩展到 8 位。"""
    return (v << 3) | (v >> 2)


def _modifiers(table_idx):
    a, b = MODIFIER_TABLES[table_idx]
    return (-a, -b, a, b)


def _sign3(v):
    """3 位补码 -> 有符号整数。"""
    return v - 8 if v >= 4 else v


def _normalize(pixels):
    """校验并规范化 4x4 像素；接受 RGB 或 RGBA 元组，丢弃 alpha。"""
    if len(pixels) != 4 or any(len(row) != 4 for row in pixels):
        raise ValueError("需要 4x4 像素块")
    out = []
    for row in pixels:
        orow = []
        for p in row:
            if len(p) < 3:
                raise ValueError("像素至少需要 R,G,B 三个通道")
            orow.append(tuple(_clamp8(int(p[c])) for c in range(3)))
        out.append(orow)
    return out


def _split(px, flip):
    """按 flip 把 4x4 块分成两个 8 像素的子块 (行优先顺序)。"""
    sub0, sub1 = [], []
    for y in range(4):
        for x in range(4):
            second = (x >= 2) if flip == 0 else (y >= 2)
            (sub1 if second else sub0).append(px[y][x])
    return sub0, sub1


def _avg(pixels):
    n = float(len(pixels))
    return [sum(p[c] for p in pixels) / n for c in range(3)]


def _quant_candidates(avg, bits):
    """围绕平均值的量化候选级别 (最近值及其邻居)，升序去重。"""
    maxv = (1 << bits) - 1
    q = int(round(avg * maxv / 255.0))
    return sorted({v for v in (q - 1, q, q + 1) if 0 <= v <= maxv})


# ---------------------------------------------------------------- 子块拟合

def _best_indices(pixels, base, table_idx):
    """给定 8 位基色与修正表，为每个像素选最优码字。

    返回 (总平方误差, 码字列表)。误差按解码端 clamp 后的真实输出计算。
    """
    mods = _modifiers(table_idx)
    total = 0
    indices = []
    for r, g, b in pixels:
        best_c = 0
        best_e = None
        for c in range(4):
            m = mods[c]
            dr = _clamp8(base[0] + m) - r
            dg = _clamp8(base[1] + m) - g
            db = _clamp8(base[2] + m) - b
            e = dr * dr + dg * dg + db * db
            if best_e is None or e < best_e:
                best_e = e
                best_c = c
        total += best_e
        indices.append(best_c)
    return total, indices


def _fit_subblock_individual(pixels):
    """individual 子块：搜 4 位基色候选 x 8 张表。

    返回 (误差, (qr,qg,qb), 表号, 码字)。
    """
    avg = _avg(pixels)
    cand = [_quant_candidates(avg[c], 4) for c in range(3)]
    best = None
    for qr, qg, qb in product(*cand):
        base = (_expand4(qr), _expand4(qg), _expand4(qb))
        for t in range(len(MODIFIER_TABLES)):
            err, idx = _best_indices(pixels, base, t)
            if best is None or err < best[0]:
                best = (err, (qr, qg, qb), t, idx)
    return best


def _diff_channel_candidates(avg0, avg1):
    """differential 单通道的 (q0, delta) 候选，delta 须在 [-4, 3]。"""
    out = set()
    q1 = int(round(avg1 * 31 / 255.0))
    for q0 in _quant_candidates(avg0, 5):
        for dd in (-1, 0, 1):
            d = q1 - q0 + dd
            if -4 <= d <= 3 and 0 <= q0 + d <= 31:
                out.add((q0, d))
    return sorted(out)


def _fit_differential(sub0, sub1):
    """differential 整块拟合。无法表示 (delta 超范围) 时返回 None。

    返回 (误差, ((q0,d) x3), 表0, 码字0, 表1, 码字1)。
    """
    avg0, avg1 = _avg(sub0), _avg(sub1)
    chan = [_diff_channel_candidates(avg0[c], avg1[c]) for c in range(3)]
    if any(not c for c in chan):
        return None
    best = None
    for (r0, dr), (g0, dg), (b0, db) in product(*chan):
        base0 = (_expand5(r0), _expand5(g0), _expand5(b0))
        base1 = (_expand5(r0 + dr), _expand5(g0 + dg), _expand5(b0 + db))
        for t0 in range(len(MODIFIER_TABLES)):
            e0, i0 = _best_indices(sub0, base0, t0)
            for t1 in range(len(MODIFIER_TABLES)):
                e1, i1 = _best_indices(sub1, base1, t1)
                err = e0 + e1
                if best is None or err < best[0]:
                    best = (err, ((r0, dr), (g0, dg), (b0, db)), t0, i0, t1, i1)
    return best


# ---------------------------------------------------------------- 位流打包

def _pack(flip, diff, payload, t0, t1, idx0, idx1):
    """把高 32 位载荷、表号与两个子块的码字打包成 8 字节。"""
    hi = (payload << 8) | (t0 << 5) | (t1 << 2) | (diff << 1) | flip
    codewords = [0] * 16
    i0 = i1 = 0
    for i in range(16):
        y, x = divmod(i, 4)
        second = (x >= 2) if flip == 0 else (y >= 2)
        if second:
            codewords[i] = idx1[i1]
            i1 += 1
        else:
            codewords[i] = idx0[i0]
            i0 += 1
    msb = lsb = 0
    for i, c in enumerate(codewords):
        msb |= ((c >> 1) & 1) << (15 - i)
        lsb |= (c & 1) << (15 - i)
    word = (hi << 32) | (msb << 16) | lsb
    return word.to_bytes(8, "big")


def _encode_individual(px):
    """两种 flip 都试，返回 (误差, 字节)。"""
    best = None
    for flip in (0, 1):
        sub0, sub1 = _split(px, flip)
        e0, q0, t0, i0 = _fit_subblock_individual(sub0)
        e1, q1, t1, i1 = _fit_subblock_individual(sub1)
        payload = (
            (q0[0] << 20) | (q1[0] << 16)
            | (q0[1] << 12) | (q1[1] << 8)
            | (q0[2] << 4) | q1[2]
        )
        cand = (e0 + e1, _pack(flip, 0, payload, t0, t1, i0, i1))
        if best is None or cand[0] < best[0]:
            best = cand
    return best


def _encode_differential(px):
    """两种 flip 都试，返回 (误差, 字节)；不可表示时返回 None。"""
    best = None
    for flip in (0, 1):
        sub0, sub1 = _split(px, flip)
        fit = _fit_differential(sub0, sub1)
        if fit is None:
            continue
        err, chan, t0, i0, t1, i1 = fit
        (r0, dr), (g0, dg), (b0, db) = chan
        payload = (
            (r0 << 19) | ((dr & 7) << 16)
            | (g0 << 11) | ((dg & 7) << 8)
            | (b0 << 3) | (db & 7)
        )
        cand = (err, _pack(flip, 1, payload, t0, t1, i0, i1))
        if best is None or cand[0] < best[0]:
            best = cand
    return best


# ---------------------------------------------------------------- 公开接口

def encode_block(pixels, mode=MODE_AUTO):
    """编码一块 4x4 像素为 8 字节。

    mode 为 "individual" / "differential" / "auto"。auto 按平方误差
    在两种模式间择优。强制 differential 而 delta 超出 [-4,3] 无法表示时，
    回退到 individual，保证输出始终可独立解码。编码过程无随机性，
    同一输入连编两次结果一致。
    """
    px = _normalize(pixels)
    if mode not in (MODE_INDIVIDUAL, MODE_DIFFERENTIAL, MODE_AUTO):
        raise ValueError("未知模式: %r" % (mode,))
    candidates = []
    if mode in (MODE_INDIVIDUAL, MODE_AUTO):
        candidates.append(_encode_individual(px))
    if mode in (MODE_DIFFERENTIAL, MODE_AUTO):
        d = _encode_differential(px)
        if d is None and mode == MODE_DIFFERENTIAL:
            d = _encode_individual(px)
        if d is not None:
            candidates.append(d)
    return min(candidates, key=lambda c: c[0])[1]


def decode_block(data):
    """把 8 字节 ETC1 块解回 4x4 RGB 像素 (行优先的列表的列表)。

    individual 与 differential 两条解码路径各自独立解析基色，
    不共享任何中间状态。
    """
    if len(data) != 8:
        raise ValueError("ETC1 块必须是 8 字节")
    word = int.from_bytes(data, "big")
    hi = word >> 32
    payload = (hi >> 8) & 0xFFFFFF
    t0 = (hi >> 5) & 7
    t1 = (hi >> 2) & 7
    diff = (hi >> 1) & 1
    flip = hi & 1

    if diff:
        # differential: 5 位基色 + 3 位有符号 delta
        r0 = (payload >> 19) & 31
        dr = _sign3((payload >> 16) & 7)
        g0 = (payload >> 11) & 31
        dg = _sign3((payload >> 8) & 7)
        b0 = (payload >> 3) & 31
        db = _sign3(payload & 7)
        base0 = (_expand5(r0), _expand5(g0), _expand5(b0))
        base1 = (
            _expand5((r0 + dr) & 31),
            _expand5((g0 + dg) & 31),
            _expand5((b0 + db) & 31),
        )
    else:
        # individual: 两个独立的 4 位基色
        base0 = (
            _expand4((payload >> 20) & 15),
            _expand4((payload >> 12) & 15),
            _expand4((payload >> 4) & 15),
        )
        base1 = (
            _expand4((payload >> 16) & 15),
            _expand4((payload >> 8) & 15),
            _expand4(payload & 15),
        )

    bases = (base0, base1)
    tables = (t0, t1)
    msb = (word >> 16) & 0xFFFF
    lsb = word & 0xFFFF
    out = []
    for y in range(4):
        row = []
        for x in range(4):
            i = y * 4 + x
            second = (x >= 2) if flip == 0 else (y >= 2)
            s = 1 if second else 0
            c = (((msb >> (15 - i)) & 1) << 1) | ((lsb >> (15 - i)) & 1)
            m = _modifiers(tables[s])[c]
            base = bases[s]
            row.append(tuple(_clamp8(base[k] + m) for k in range(3)))
        out.append(row)
    return out


def block_mode(data):
    """返回 8 字节块的编码模式 ("individual" 或 "differential")。"""
    if len(data) != 8:
        raise ValueError("ETC1 块必须是 8 字节")
    return MODE_DIFFERENTIAL if (data[3] & 2) else MODE_INDIVIDUAL


def block_error(a, b):
    """算两个 4x4 块的误差。

    返回 dict:
      - "max": 所有像素所有通道的最大绝对误差
      - "per_channel": (R, G, B) 各通道最大绝对误差
      - "sum_sq": 全块平方误差和
      - "worst_pixel": 平方误差最大的像素坐标 (x, y)
    """
    max_ch = [0, 0, 0]
    sum_sq = 0
    worst = None
    worst_e = -1
    for y in range(4):
        for x in range(4):
            pa, pb = a[y][x], b[y][x]
            e = 0
            for c in range(3):
                d = abs(int(pa[c]) - int(pb[c]))
                if d > max_ch[c]:
                    max_ch[c] = d
                e += d * d
            sum_sq += e
            if e > worst_e:
                worst_e = e
                worst = (x, y)
    return {
        "max": max(max_ch),
        "per_channel": tuple(max_ch),
        "sum_sq": sum_sq,
        "worst_pixel": worst,
    }
