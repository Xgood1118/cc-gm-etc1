# ETC1 块编解码

一个能把 4x4 像素块编成 ETC1 并解回近似像素的块压缩器。纯标准库实现，
每块编码为 8 字节 (64 位)，支持 individual / differential 两种模式，
`auto` 模式按平方误差自动择优；强制 differential 但 delta 超出 [-4,3]
不可表示时回退 individual，保证输出始终可独立解码。

## 保留签名

- `Block`
- `encode_block(pixels, mode)`
- `decode_block(data)`
- `block_error(a, b)`

另提供 `block_mode(data)` 读取已编码块的模式。

## 格式说明

- 高 32 位：individual 为两组 4 位基色；differential 为 5 位基色 + 3 位
  有符号 delta；之后是两个 3 位修正表号、diff 位、flip 位。
- 低 32 位：16 个像素各 2 位修正项码字 (先 MSB 后 LSB)，像素行优先编号。
- 修正表为标准 ETC1 的 8 张表，码字 0..3 对应 (-a, -b, +a, +b)。
- 每像素只能加一个标量修正量 (三通道相同)，因此高饱和混色块存在固有
  误差；每通道误差理论上限 255 (输出恒 clamp 在 [0,255])。
- alpha 通道不参与编码：全透明块按 RGB 编码，解码恒为 RGB 三元组，
  结果确定。

## 实测结果 (data/block.txt，纯红块)

```
$ python -m etc1.cli data/block.txt --out block.bin
块 0: 模式=individual 每通道最大误差=(2, 0, 0) 块最大误差=2
块数: 1
选用模式: individual
每通道最大误差: R=2 G=0 B=0
最坏块: #0 最大误差=2
位流长度: 64 位 (8 字节) -> block.bin
```

- 选用模式：individual
- 每通道最大误差：R=2, G=0, B=0 (ETC1 修正量最小非零步长为 2，
  纯红 255 的固有误差)
- 最坏块误差：#0，最大误差 2
- 位流长度：64 位 (8 字节)

## 自测

```
python -m pytest tests -q
python -m etc1.cli data/block.txt --out block.bin
```
