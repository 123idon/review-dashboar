"""One-time, user-operated Naver login. Sends only Naver session state to your server."""
import json
from pathlib import Path
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen

BASE = 'https://web-production-ce7ca1.up.railway.app'
URL = 'https://sell.smartstore.naver.com/#/review/search'


def main():
    from playwright.sync_api import sync_playwright
    config_path = Path(__file__).with_name('connection.json')
    if not config_path.exists():
        raise RuntimeError('전용 연결 파일(connection.json)이 없습니다. 새 연결 파일을 요청해 주세요.')
    token = json.loads(config_path.read_text(encoding='utf-8'))['token']
    print('네이버 자동 갱신 최초 연결 / GPT 호출 없음')
    print('지금 열리는 네이버 공식 창에서 직접 로그인하고 2단계 인증을 완료하세요.')
    print('백년화편 > 문의/리뷰관리 > 리뷰 관리 화면으로 이동하세요.')
    print('비밀번호와 인증번호는 네이버 화면에만 입력하세요.')
    print('이후 로그인 세션을 본인 대시보드 서버에 HTTPS로 전송해 자동 수집에 사용합니다.')
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        try:
            context = browser.new_context(locale='ko-KR', timezone_id='Asia/Seoul')
            page = context.new_page()
            page.goto(URL)
            input('\n리뷰 관리 화면이 열렸으면 이 창에서 Enter를 누르세요: ')
            pages = [p for p in context.pages if p.url.startswith('https://sell.smartstore.naver.com/')]
            if not pages:
                raise RuntimeError('판매자센터 로그인이 확인되지 않았습니다.')
            page = pages[-1]
            page.goto(URL, wait_until='domcontentloaded')
            page.get_by_text('6개월', exact=True).wait_for(timeout=60000)
            if '백년화편' not in page.locator('body').inner_text():
                raise RuntimeError('백년화편 스토어를 선택한 다음 다시 실행해 주세요.')
            state = context.storage_state()
            # No cookies from other websites are sent or saved on disk.
            def is_naver(host):
                host = host.lstrip('.').lower()
                return host == 'naver.com' or host.endswith('.naver.com')
            from urllib.parse import urlparse
            state['cookies'] = [c for c in state['cookies'] if is_naver(c['domain'])]
            state['origins'] = [o for o in state['origins'] if is_naver(urlparse(o['origin']).hostname or '')]
            print('서버에서 실제 후기 수집을 확인하고 있습니다. 최대 10분 정도 걸릴 수 있습니다.')
            req = Request(BASE + '/api/naver-automation/connect', data=json.dumps(state).encode(),
                          headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token})
            try:
                with urlopen(req, timeout=660) as response:
                    result = json.load(response)
            except HTTPError as exc:
                if exc.code == 401:
                    raise RuntimeError('연결 코드가 만료되었거나 사용되었습니다. 새 연결 파일을 요청해 주세요.') from None
                raise RuntimeError(f'서버 연결 오류({exc.code}). 대시보드 수집 상태를 확인해 주세요.') from None
            if not result.get('ok'):
                raise RuntimeError(result.get('message', '서버에서 로그인 상태를 확인하지 못했습니다. 자동 갱신은 아직 준비되지 않았습니다.'))
            config_path.unlink(missing_ok=True)
            print(f"\n연결 완료! {result['received']}건 확인, {result['added']}건 추가.")
            print('앞으로 매일 한국시간 00:00에 서버에서 실행합니다. PC를 꺼도 됩니다.')
        finally:
            browser.close()


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('\n연결 미완료: ' + str(exc))
        input('이 메시지를 알려주세요. Enter를 누르면 종료합니다.')
        sys.exit(1)
    input('Enter를 누르면 종료합니다.')
