#!/usr/bin/env python3
"""Compatibility CLI for product images; all generation uses ai_image.main."""
from __future__ import annotations

import argparse
import sys
import time
import uuid
from pathlib import Path

# Both repository (skills/builtin/...) and synced OpenClaw workspace layouts.
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'shared' / 'scripts'))
import ai_image


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='电商图片生成：复用统一生图配置和执行入口')
    prompt = parser.add_mutually_exclusive_group(required=True)
    prompt.add_argument('--prompt', help='图片提示词')
    prompt.add_argument('--prompt-file', help='UTF-8 提示词文件')
    parser.add_argument('--output-dir', default='outputs/电商商品图', help='outputs/<具体项目>/ 下的目录')
    parser.add_argument('--provider', help='媒体实例 ID；省略使用设置页默认，legacy 使用旧配置')
    parser.add_argument('--env-file', help='项目 .env 文件')
    parser.add_argument('--image', help='参考产品图片；调用统一图片编辑接口')
    parser.add_argument('--mask', help='可选编辑遮罩')
    parser.add_argument('--size', default='1:1', help='比例或像素尺寸，默认 1:1 → 1024x1024')
    parser.add_argument('--resolution', choices=ai_image.VALID_RESOLUTIONS, default='2k', help='仅旧异步接口使用的分辨率档位')
    parser.add_argument('--quality', help='服务支持的图片质量参数')
    parser.add_argument('--n', type=int, default=1, help='生成张数')
    parser.add_argument('--mode', choices=('sync', 'async'), help='传给统一入口的接口模式')
    parser.add_argument('--poll-interval', type=int, default=5, help='旧异步接口轮询间隔')
    parser.add_argument('--timeout', type=int, help='请求超时；省略使用统一入口/实例默认')
    parser.add_argument('--format', choices=('png', 'jpeg', 'webp'), default='png')
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    try:
        prompt = (args.prompt if args.prompt is not None else Path(args.prompt_file).read_text(encoding='utf-8')).strip()
        if not prompt:
            raise ValueError('prompt 不能为空')
        if args.n < 1:
            raise ValueError('生成张数必须大于0')
        if args.mask and not args.image:
            raise ValueError('遮罩必须与参考图片一起使用')
        size = args.size
        if ':' in size:
            size = next((pixels for pixels, ratio in ai_image.PIXEL_TO_RATIO.items() if ratio == size), '')
            if not size:
                raise ValueError('不支持的比例，请指定模型支持的像素尺寸')
        # Unique per invocation: a quality rerun must not overwrite the previous image.
        filename = f'image-{time.strftime("%Y%m%d-%H%M%S")}-{uuid.uuid4().hex[:8]}.{args.format}'
        output = Path(args.output_dir) / filename
        forwarded = ['img2img' if args.image else 'text2img', '--prompt', prompt,
                     '--output', str(output), '--size', size, '--n', str(args.n),
                     '--format', args.format, '--resolution', args.resolution,
                     '--poll-interval', str(args.poll_interval)]
        for key in ('provider', 'env_file', 'image', 'mask', 'quality', 'mode', 'timeout'):
            value = getattr(args, key)
            if value is not None:
                forwarded.extend(['--' + key.replace('_', '-'), str(value)])
        ai_image.main(forwarded)
    except (OSError, ValueError) as exc:
        ai_image.fail(str(exc))


if __name__ == '__main__':
    main()
