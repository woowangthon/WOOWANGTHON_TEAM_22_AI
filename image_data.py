"""Validate provider image bytes before review or delivery; no file writes."""
import base64
import binascii
import io
import struct
import warnings

from PIL import Image, UnidentifiedImageError


def image_data_url(encoded, expected_format=None):
    try:
        if not isinstance(encoded, str) or len(encoded) > 28_000_000:
            raise ValueError('invalid image size')
        raw = base64.b64decode(encoded, validate=True)
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as picture:
                kind = picture.format
                if kind not in {'PNG', 'JPEG'} or (expected_format and kind != expected_format):
                    raise ValueError('invalid image format')
                if picture.width * picture.height > 16_777_216:
                    raise ValueError('invalid image dimensions')
                picture.verify()
            with Image.open(io.BytesIO(raw)) as picture:
                picture.load()
        mime = 'image/png' if kind == 'PNG' else 'image/jpeg'
        return f'data:{mime};base64,{encoded}'
    except (ValueError, TypeError, binascii.Error, OSError, UnidentifiedImageError,
            SyntaxError, EOFError, struct.error,
            Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise ValueError('이미지 파일 형식이나 데이터를 확인하지 못했습니다.') from None
