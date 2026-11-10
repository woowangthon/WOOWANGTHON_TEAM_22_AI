"""외부 API 없이 이미지 속 글자를 탐지합니다. 인식한 문자열은 기록하지 않습니다."""
import base64
import io
import threading
from functools import lru_cache

from PIL import Image
from engine import ProviderError

_OCR_LOCK = threading.Lock()


@lru_cache(maxsize=1)
def _ocr_engine():
    from rapidocr import RapidOCR
    return RapidOCR(params={'Global.log_level': 'error'})


def has_lettering(data_url):
    """인식 신뢰도 0.6 이상인 글자가 있으면 합본 전체를 다시 만듭니다."""
    try:
        import numpy as np
        with Image.open(io.BytesIO(base64.b64decode(data_url.split(',', 1)[1], validate=True))) as image:
            pixels = np.array(image.convert('RGB'))
        with _OCR_LOCK:
            result = _ocr_engine()(pixels)
        texts = result.txts
        scores = result.scores
        if texts is None:
            return False
        if scores is None or len(texts) != len(scores):
            raise ValueError('incomplete OCR output')
        return any(isinstance(text, str) and any(char.isalnum() for char in text)
                   and float(score) >= 0.6 for text, score in zip(texts, scores))
    except Exception:
        # OCR 장애를 검사 통과로 취급하지 않습니다. 원본 예외/이미지/인식 문구는 노출하지 않습니다.
        raise ProviderError('문자 검사 준비 또는 실행에 실패했습니다. 의존성 설치 후 python prepare_ocr.py를 실행해 주세요.',
                            reason='configuration') from None


def remove_lettering(data_url):
    """고신뢰 글자 영역만 국소 복원합니다. 넓은 영역은 훼손하지 않고 원본을 돌려줍니다."""
    try:
        import cv2
        import numpy as np
        with Image.open(io.BytesIO(base64.b64decode(data_url.split(',', 1)[1], validate=True))) as image:
            pixels = np.array(image.convert('RGB'))
        with _OCR_LOCK:
            result = _ocr_engine()(pixels)
        if result.txts is None:
            return data_url
        if result.boxes is None or result.scores is None:
            raise ValueError('incomplete OCR output')
        mask = np.zeros(pixels.shape[:2], dtype=np.uint8)
        for box, text, score in zip(result.boxes, result.txts, result.scores):
            if isinstance(text, str) and any(c.isalnum() for c in text) and float(score) >= 0.6:
                cv2.fillPoly(mask, [np.asarray(box, dtype=np.int32)], 255)
        mask = cv2.dilate(mask, np.ones((5, 5), dtype=np.uint8), iterations=1)
        # 넓은 영역이나 삽화 전체를 지우지 않습니다. 이 경우 재생성/거절로 처리합니다.
        if not mask.any() or np.count_nonzero(mask) / mask.size > 0.08:
            return data_url
        cleaned = cv2.inpaint(pixels, mask, 3, cv2.INPAINT_TELEA)
        stream = io.BytesIO()
        Image.fromarray(cleaned).save(stream, format='PNG')
        return 'data:image/png;base64,' + base64.b64encode(stream.getvalue()).decode()
    except Exception:
        raise ProviderError('이미지 문자 제거에 실패했습니다. 이 만화를 다시 만들어 주세요.') from None
