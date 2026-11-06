"""개발자용 음성 대화 화면. 제품 FE와 별도로 localhost에서만 제공합니다."""
import os
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse


def attach_voice_demo(app, base_dir):
    files = Path(base_dir) / 'devtools' / 'voice'

    def local_only(request):
        if os.getenv('ENABLE_VOICE_DEMO', '0') != '1':
            raise HTTPException(404, 'Not Found')
        if not request.client or request.client.host not in {'127.0.0.1', '::1'}:
            raise HTTPException(403, '개발용 화면은 로컬에서만 사용할 수 있습니다.')

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
