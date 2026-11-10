"""python check_setup.py: 키 값 출력·외부 호출 없이 기능별 설정을 점검합니다."""
from pathlib import Path
from dotenv import load_dotenv
from providers import ProviderRouter, setting


def main():
    load_dotenv(Path(__file__).resolve().parent / '.env')
    router=ProviderRouter()
    for label, provider, key in [
        ('대화/일기',router.text_provider,'GROQ_API_KEY' if router.text_provider=='groq' else 'OPENAI_API_KEY'),
        ('음성 인식',router.stt_provider,'GROQ_API_KEY' if router.stt_provider=='groq' else 'OPENAI_API_KEY'),
        ('그림 검토',router.vision_provider,'GROQ_API_KEY' if router.vision_provider=='groq' else 'OPENAI_API_KEY'),
        ('그림 생성',router.image_provider,'CLOUDFLARE_API_TOKEN' if router.image_provider=='cloudflare' else 'OPENAI_API_KEY'),
        ('음성 출력',router.tts_provider,'OPENAI_API_KEY'),
    ]:
        if label=='그림 검토' and router.image_provider=='cloudflare':
            print('그림 검토: 사용자 확인 / 자동 모델 호출 없음')
            continue
        status='비활성화' if provider=='disabled' else ('키 설정됨' if setting(key) else f'{key} 필요')
        print(f'{label}: {provider} / {status}')
    if router.image_provider=='cloudflare':
        print('Cloudflare 계정 ID: '+('설정됨' if setting('CLOUDFLARE_ACCOUNT_ID') else '미설정'))
    print('키 존재 여부만 확인했습니다. 실제 권한·잔액·모델 응답은 /docs에서 검사하세요.')


if __name__=='__main__':
    main()
