"""
Скрипт для получения OAuth-токена YooMoney.

Использование:
1. python get_yoomoney_token.py
2. Откроется браузер — авторизуйтесь в YooMoney
3. После редиректа скрипт покажет токен
4. Сохраните токен как yoomoney_secret_key в настройках бота
"""
import webbrowser
import http.server
import threading
import urllib.parse
import urllib.request
import json
import sys
import time

# ─── НАСТРОЙКИ ─────────────────────────────────────────────
# App ID (client_id) — создаётся на https://yoomoney.ru/myapps
# Если у вас уже есть — вставьте сюда. Если нет — скрипт поможет создать.
CLIENT_ID = ""  # Вставьте ваш client_id сюда (цифры)
REDIRECT_URI = "http://localhost:9876/callback"
SCOPES = "account-info operation-history"
# ───────────────────────────────────────────────────────────


class OAuthHandler(http.server.BaseHTTPRequestHandler):
    """Обработчик редиректа от YooMoney."""
    authorization_code = None

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        if 'code' in params:
            OAuthHandler.authorization_code = params['code'][0]
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(
                '<h2>Авторизация прошла успешно!</h2>'
                '<p>Можете закрыть это окно и вернуться в терминал.</p>'
                .encode('utf-8')
            )
        elif 'error' in params:
            self.send_response(400)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            error = params.get('error', ['unknown'])[0]
            self.wfile.write(f'<h2>Ошибка: {error}</h2>'.encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # Тихий режим


def get_access_token(client_id, authorization_code):
    """Обменивает authorization_code на access_token."""
    data = urllib.parse.urlencode({
        'grant_type': 'authorization_code',
        'client_id': client_id,
        'client_secret': client_id,  # Для YooMoney client_secret = client_id
        'code': authorization_code,
    }).encode()

    req = urllib.request.Request(
        'https://yoomoney.ru/api/token',
        data=data,
        headers={'Content-Type': 'application/x-www-form-urlencoded'}
    )

    with urllib.request.urlopen(req, timeout=15) as resp:
        result = json.loads(resp.read().decode())
        return result


def get_account_info(access_token):
    """Получает информацию о кошельке."""
    req = urllib.request.Request(
        'https://yoomoney.ru/api/account-info',
        headers={'Authorization': f'Bearer {access_token}'}
    )

    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def main():
    print("=" * 60)
    print("  Получение OAuth-токена YooMoney")
    print("=" * 60)
    print()

    client_id = CLIENT_ID

    if not client_id:
        print("Для получения токена нужен App ID (client_id).")
        print()
        print("Как получить:")
        print("  1. Откройте https://yoomoney.ru/myapps")
        print("  2. Войдите в аккаунт YooMoney")
        print("  3. Нажмите «Создать приложение»")
        print("  4. Название: любое (например 'VPN Bot')")
        print("  5. Callback URL: http://localhost:9876/callback")
        print("  6. Пермишены: account-info, operation-history")
        print("  7. Сохраните — получите Client ID (число)")
        print()
        client_id = input("Введите Client ID (цифры): ").strip()
        if not client_id:
            print("Client ID не введён. Выход.")
            sys.exit(1)

    # Запускаем локальный сервер для callback
    server = http.server.HTTPServer(('localhost', 9876), OAuthHandler)
    server_thread = threading.Thread(target=server.handle_request)
    server_thread.daemon = True
    server_thread.start()

    # Формируем URL для авторизации
    auth_params = urllib.parse.urlencode({
        'client_id': client_id,
        'redirect_uri': REDIRECT_URI,
        'response_type': 'code',
        'scope': SCOPES,
    })
    auth_url = f"https://yoomoney.ru/oauth/authorize?{auth_params}"

    print()
    print("Открываю браузер для авторизации...")
    print(f"URL: {auth_url}")
    print()
    webbrowser.open(auth_url)

    print("Ожидание авторизации в браузере...")

    # Ждём ответа (макс 120 секунд)
    start = time.time()
    while OAuthHandler.authorization_code is None and time.time() - start < 120:
        time.sleep(0.5)

    if OAuthHandler.authorization_code is None:
        print("Тайм-аут: авторизация не была выполнена за 120 секунд.")
        sys.exit(1)

    code = OAuthHandler.authorization_code
    print(f"Получен authorization code: {code[:10]}...")

    # Обмениваем код на токен
    print("Обмениваю код на access_token...")
    try:
        token_data = get_access_token(client_id, code)
    except Exception as e:
        print(f"Ошибка при получении токена: {e}")
        sys.exit(1)

    access_token = token_data.get('access_token')
    if not access_token:
        print(f"Ошибка: {json.dumps(token_data, indent=2)}")
        sys.exit(1)

    print()
    print("=" * 60)
    print("  ТОКЕН ПОЛУЧЕН!")
    print("=" * 60)
    print()
    print(f"Access Token: {access_token}")
    print()

    # Получаем инфо о кошельке
    try:
        info = get_account_info(access_token)
        print(f"Кошелёк: {info.get('account', '?')}")
        print(f"Баланс: {info.get('balance', '?')} ₽")
        print(f"Статус: {info.get('status', '?')}")
    except Exception:
        pass

    print()
    print("─" * 60)
    print("Сохраните этот токен в настройках бота:")
    print(f"  yoomoney_secret_key = {access_token}")
    print("─" * 60)
    print()
    print("Для сохранения в БД выполните:")
    print(f'  python -c "from database.db_settings import set_setting; set_setting(\'yoomoney_secret_key\', \'{access_token}\')"')
    print()


if __name__ == '__main__':
    main()
