# -*- coding: utf-8 -*-
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import etc1 as mod  # noqa: E402


def test_block_roundtrip():
    b = etc1.Block([[ (255, 0, 0) for _ in range(4)] for _ in range(4)])
    data = etc1.encode_block(b.pixels, "individual")
    back = etc1.decode_block(data)
    err = etc1.block_error(b.pixels, back)
    assert err["max"] <= 32


def test_single_color_block():
    b = etc1.Block([[(128, 128, 128) for _ in range(4)] for _ in range(4)])
    data = etc1.encode_block(b.pixels, "differential")
    assert len(data) == 8
