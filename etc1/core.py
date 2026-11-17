# -*- coding: utf-8 -*-
"""ETC1 块编解码"""

from dataclasses import dataclass


@dataclass
class Block:
    """4x4 像素块。"""
    pixels: list
    mode: str = "individual"


def Block:
    """class"""
    raise NotImplementedError("Block 尚未实现")


def encode_block(pixels, mode):
    """编码一块"""
    raise NotImplementedError("encode_block 尚未实现")


def decode_block(data):
    """解码一块"""
    raise NotImplementedError("decode_block 尚未实现")


def block_error(a, b):
    """算块误差"""
    raise NotImplementedError("block_error 尚未实现")

