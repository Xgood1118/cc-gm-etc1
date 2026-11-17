# ETC1 块编解码

一个能把 4x4 像素块编成 ETC1 并解回近似像素的块压缩器

## 保留签名

- `Block`
- `encode_block(pixels, mode)`
- `decode_block(data)`
- `block_error(a, b)`

## 自测

```
python -m pytest tests -q
python -m etc1.cli data/block.txt --out block.bin
```
