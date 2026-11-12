"""제품 FE와 별도로 로컬 개발 화면을 제공합니다."""
import os
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse


def attach_voice_demo(app, base_dir):
    files = Path(base_dir) / 'devtools' / 'voice'

    def local_only(request, flag='ENABLE_VOICE_DEMO'):
        if os.getenv(flag, '0') != '1':
            raise HTTPException(404, 'Not Found')
        if not request.client or request.client.host not in {'127.0.0.1', '::1'}:
            raise HTTPException(403, '개발용 화면은 로컬에서만 사용할 수 있습니다.')

    @app.get('/dev/worry', include_in_schema=False)
    def worry_demo(request: Request):
        local_only(request, 'ENABLE_WORRY_DEMO')
        return FileResponse(Path(base_dir) / 'devtools' / 'worry' / 'index.html',
                            headers={'Cache-Control': 'no-store'})

    @app.get('/dev/worry/mascot.svg', include_in_schema=False)
    def worry_mascot(request: Request):
        local_only(request, 'ENABLE_WORRY_DEMO')
        # FE의 Fluent Emoji 마스코트. 라이선스는 자산 옆에 보관합니다.
        return FileResponse(Path(base_dir) / 'devtools' / 'worry' / 'mascot_default.svg',
                            media_type='image/svg+xml', headers={'Cache-Control': 'no-store'})

    @app.get('/dev/voice', include_in_schema=False)
    def voice_demo(request: Request):
        local_only(request)
        return FileResponse(files / 'index.html', headers={'Cache-Control': 'no-store'})

    @app.get('/dev/voice/{name}', include_in_schema=False)
    def voice_asset(name: str, request: Request):
        local_only(request)
        if name not in {'app.js', 'core.mjs', 'illustration.mjs', 'drawing.mjs', 'style.css'}:
            raise HTTPException(404, 'Not Found')
        media = 'text/css' if name.endswith('.css') else 'text/javascript'
        return FileResponse(files / name, media_type=media, headers={'Cache-Control': 'no-store'})
