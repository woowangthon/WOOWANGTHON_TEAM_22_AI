import base64
import io
from PIL import Image


def encoded_image(kind='PNG'):
    stream = io.BytesIO()
    Image.new('RGB', (8, 8), 'white').save(stream, format=kind)
    return base64.b64encode(stream.getvalue()).decode()
