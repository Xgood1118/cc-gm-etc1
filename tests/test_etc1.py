# -*- coding: utf-8 -*-
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import etc1 as mod  # noqa: E402
etc1 = mod

DATA_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "data", "block.txt")


def read_text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def read_hex(path):
    with open(path, encoding="utf-8") as f:
        return f.read().strip()


def read_bytes(path):
    with open(path, "rb") as f:
        return f.read()


def read_blocks(path):
    nums = [int(t) for t in read_text(path).split()]
    assert len(nums) % 48 == 0
    blocks = []
    for off in range(0, len(nums), 48):
        v = nums[off:off + 48]
        blocks.append([
            [tuple(v[(y * 4 + x) * 3:(y * 4 + x) * 3 + 3]) for x in range(4)]
            for y in range(4)
        ])
    return blocks


def roundtrip_error(px, mode="auto"):
    return etc1.block_error(px, etc1.decode_block(etc1.encode_block(px, mode)))


# ---------------------------------------------------------------- 原有用例

def test_block_roundtrip():
    b = etc1.Block([[(255, 0, 0) for _ in range(4)] for _ in range(4)])
    data = etc1.encode_block(b.pixels, "individual")
    back = etc1.decode_block(data)
    err = etc1.block_error(b.pixels, back)
    assert err["max"] <= 32


def test_single_color_block():
    b = etc1.Block([[(128, 128, 128) for _ in range(4)] for _ in range(4)])
    data = etc1.encode_block(b.pixels, "differential")
    assert len(data) == 8


# ---------------------------------------------------------------- 两模式择优

def test_auto_picks_lower_error_mode():
    # 每个子块内像素分散 (60/90 灰)，differential 的 5 位基色更占优
    px = [[(60, 60, 60) if (x + y) % 2 == 0 else (90, 90, 90)
           for x in range(4)] for y in range(4)]
    d_ind = etc1.encode_block(px, "individual")
    d_dif = etc1.encode_block(px, "differential")
    d_auto = etc1.encode_block(px, "auto")
    e_ind = etc1.block_error(px, etc1.decode_block(d_ind))["sum_sq"]
    e_dif = etc1.block_error(px, etc1.decode_block(d_dif))["sum_sq"]
    e_auto = etc1.block_error(px, etc1.decode_block(d_auto))["sum_sq"]
    assert e_auto == min(e_ind, e_dif)
    assert e_dif < e_ind  # 该块上 differential 确实更好
    assert etc1.block_mode(d_auto) == "differential"


def test_auto_falls_back_when_delta_out_of_range():
    # 左半纯红右半纯蓝，auto 应选 individual 且误差很小
    px = [[(255, 0, 0), (255, 0, 0), (0, 0, 255), (0, 0, 255)]
          for _ in range(4)]
    data = etc1.encode_block(px, "auto")
    assert etc1.block_mode(data) == "individual"
    assert etc1.block_error(px, etc1.decode_block(data))["max"] <= 32


def test_forced_differential_infeasible_falls_back():
    # R 通道在两个方向上的子块均值都差 127.5 (delta=-16，超出 [-4,3])，
    # differential 两种 flip 都不可表示，强制时必须回退 individual。
    px = [[(255, 0, 0) if (x < 2 or y < 2) else (0, 0, 0)
           for x in range(4)] for y in range(4)]
    forced = etc1.encode_block(px, "differential")
    assert len(forced) == 8
    assert etc1.block_mode(forced) == "individual"
    # 红/黑混在一个子块内，标量修正量无法同时逼近 (255,0,0) 与 (0,0,0)，
    # 误差天然存在 (实测 55)，断言确定性的上界。
    assert etc1.block_error(px, etc1.decode_block(forced))["max"] <= 64


# ---------------------------------------------------------------- 往返误差上界

def test_roundtrip_error_bounded():
    rng = random.Random(42)
    px = [[(rng.randrange(256), rng.randrange(256), rng.randrange(256))
           for _ in range(4)] for _ in range(4)]
    for mode in ("individual", "differential", "auto"):
        back = etc1.decode_block(etc1.encode_block(px, mode))
        err = etc1.block_error(px, back)
        # 每通道误差上界：理论上限 255 (输出恒在 [0,255])，
        # 本编码器在该随机块上实测最大 131，留裕量取 160。
        assert err["max"] <= 160
        # per_channel 与逐像素重算一致
        assert err["per_channel"] == tuple(
            max(abs(px[y][x][c] - back[y][x][c])
                for y in range(4) for x in range(4))
            for c in range(3)
        )


def test_data_file_roundtrip():
    for px in read_blocks(DATA_FILE):
        err = roundtrip_error(px)
        assert err["max"] <= 32


# ---------------------------------------------------------------- 最坏块统计

def test_worst_block_stats():
    rng = random.Random(7)
    blocks = [
        [[(0, 0, 0)] * 4 for _ in range(4)],
        [[(255, 255, 255)] * 4 for _ in range(4)],
        [[(rng.randrange(256), rng.randrange(256), rng.randrange(256))
          for _ in range(4)] for _ in range(4)],
        [[(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)]
         for _ in range(4)],
    ]
    errs = [roundtrip_error(px) for px in blocks]
    worst = max(range(len(blocks)), key=lambda i: errs[i]["max"])
    assert errs[worst]["max"] == max(e["max"] for e in errs)
    x, y = errs[worst]["worst_pixel"]
    assert 0 <= x < 4 and 0 <= y < 4
    # 最坏像素的平方误差确实不小于其他像素
    back = etc1.decode_block(etc1.encode_block(blocks[worst], "auto"))
    wp = sum((blocks[worst][y][x][c] - back[y][x][c]) ** 2 for c in range(3))
    for yy in range(4):
        for xx in range(4):
            e = sum((blocks[worst][yy][xx][c] - back[yy][xx][c]) ** 2
                    for c in range(3))
            assert e <= wp


# ---------------------------------------------------------------- 边界：单色 / 极值 / 全透明

def test_solid_and_extreme_blocks():
    for v in (0, 255, 128):
        px = [[(v, v, v) for _ in range(4)] for _ in range(4)]
        for mode in ("individual", "differential", "auto"):
            data = etc1.encode_block(px, mode)
            assert len(data) == 8
            err = etc1.block_error(px, etc1.decode_block(data))
            assert err["max"] <= 8


def test_mixed_extremes_block():
    # 饱和绿/品红同处一个子块时，ETC1 每像素只能加标量修正量，
    # 误差天然较大 (实测 174)，这里断言确定性的上界。
    px = [[(0, 0, 0), (255, 255, 255), (0, 255, 0), (255, 0, 255)]
          for _ in range(4)]
    err = roundtrip_error(px)
    assert err["max"] <= 200


def test_fully_transparent_block():
    # RGBA 全透明：alpha 不参与编码，结果确定且等同于黑色块
    px = [[(0, 0, 0, 0) for _ in range(4)] for _ in range(4)]
    d1 = etc1.encode_block(px, "auto")
    d2 = etc1.encode_block(px, "auto")
    assert d1 == d2
    back = etc1.decode_block(d1)
    assert all(len(p) == 3 for row in back for p in row)
    black = [[(0, 0, 0) for _ in range(4)] for _ in range(4)]
    assert etc1.block_error(black, back)["max"] == 0


# ---------------------------------------------------------------- 两次一致

def test_encode_twice_identical():
    rng = random.Random(123)
    px = [[(rng.randrange(256), rng.randrange(256), rng.randrange(256))
           for _ in range(4)] for _ in range(4)]
    for mode in ("individual", "differential", "auto"):
        assert etc1.encode_block(px, mode) == etc1.encode_block(px, mode)
