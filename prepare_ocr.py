"""최초 설치/배포 때 실행해 OCR 모델을 준비합니다. 사용자 자료나 API 키는 쓰지 않습니다."""
from image_quality import _ocr_engine

if __name__ == '__main__':
    _ocr_engine()
    print('로컬 OCR 모델 준비 완료')
