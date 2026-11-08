import base64
import io

import pytest
from PIL import Image

from image_data import image_data_url
from image_fixture import encoded_image


@pytest.mark.parametrize('kind,mime', [('PNG', 'image/png'), ('JPEG', 'image/jpeg')])
def test_decodes_complete_image_and_matches_mime(kind, mime):
    encoded = encoded_image(kind)
    assert image_data_url(encoded) == f'data:{mime};base64,{encoded}'


@pytest.mark.parametrize('value', ['', 'not-base64', None, base64.b64encode(b'\x89PNG\r\n\x1a\n').decode()])
def test_malformed_data_is_not_an_image(value):
    with pytest.raises(ValueError):
        image_data_url(value)


def test_valid_base64_but_truncated_file_is_not_an_image():
    raw = base64.b64decode(encoded_image())
    with pytest.raises(ValueError):
        image_data_url(base64.b64encode(raw[:40]).decode())


def test_declared_png_cannot_contain_jpeg():
    with pytest.raises(ValueError):
        image_data_url(encoded_image('JPEG'), 'PNG')


def test_unexpected_image_type_is_not_delivered():
    stream = io.BytesIO()
    Image.new('RGB', (8, 8)).save(stream, format='GIF')
    with pytest.raises(ValueError):
        image_data_url(base64.b64encode(stream.getvalue()).decode())
