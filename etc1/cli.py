# -*- coding: utf-8 -*-
"""命令行入口：python -m etc1.cli data/block.txt --out block.bin"""

import argparse

from .core import encode_block, decode_block, block_error, block_mode


def read_blocks(path):
    """读取空白分隔的 RGB 整数，每 48 个数为一个 4x4 块。"""
    with open(path, encoding="utf-8") as f:
        nums = [int(t) for t in f.read().split()]
    if not nums or len(nums) % 48 != 0:
        raise SystemExit("输入必须是 48 的倍数个整数 (每块 16 像素 x RGB)")
    blocks = []
    for off in range(0, len(nums), 48):
        v = nums[off:off + 48]
        blocks.append([
            [tuple(v[(y * 4 + x) * 3:(y * 4 + x) * 3 + 3]) for x in range(4)]
            for y in range(4)
        ])
    return blocks


def main():
    ap = argparse.ArgumentParser(description="ETC1 块编解码")
    ap.add_argument("input", help="文本文件：空白分隔的 RGB 整数")
    ap.add_argument("--out", required=True, help="输出的二进制位流文件")
    a = ap.parse_args()

    blocks = read_blocks(a.input)
    blob = bytearray()
    max_ch = [0, 0, 0]
    worst_i, worst_err = -1, -1
    modes = []
    for i, px in enumerate(blocks):
        data = encode_block(px, "auto")
        blob += data
        err = block_error(px, decode_block(data))
        mode = block_mode(data)
        modes.append(mode)
        for c in range(3):
            if err["per_channel"][c] > max_ch[c]:
                max_ch[c] = err["per_channel"][c]
        if err["max"] > worst_err:
            worst_err = err["max"]
            worst_i = i
        print("块 %d: 模式=%s 每通道最大误差=%s 块最大误差=%d"
              % (i, mode, err["per_channel"], err["max"]))

    with open(a.out, "wb") as f:
        f.write(bytes(blob))

    print("块数: %d" % len(blocks))
    print("选用模式: %s" % ", ".join(modes))
    print("每通道最大误差: R=%d G=%d B=%d" % tuple(max_ch))
    print("最坏块: #%d 最大误差=%d" % (worst_i, worst_err))
    print("位流长度: %d 位 (%d 字节) -> %s" % (len(blob) * 8, len(blob), a.out))


if __name__ == "__main__":
    main()
