# ЮMoney Integration Fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix YooMoney integration to use only Client ID + Secret Key authentication (remove API Token requirement)

**Architecture:** Modify existing YooMoney integration in place — update credentials retrieval, payment creation, and status checking to use Client ID + Secret Key instead of Bearer token.

**Tech Stack:** Python, aiohttp, SQLite

## Global Constraints

- Do NOT break existing payment methods (Stars, Cards, QR, WATA, Platega, Cardlink)
- Do NOT change database schema without necessity
- Use existing models, tables, and handlers
- Only fix issues and missing parts

---

## Task 1: Update YooMoney Credentials Functions

**Covers:** Remove API Token requirement, use Client ID + Secret Key only

**Files:**
- Modify: `database/db_settings.py:316-349`

**Interfaces:**
- Consumes: `get_setting()` from db_settings
- Produces: `get_yoomoney_credentials()` returns tuple[str, str] (client_id, secret_key)

- [ ] **Step 1: Update `is_yoomoney_configured()` to check only client_id and secret_key**

```python
def is_yoomoney_configured() -> bool:
    """
    Проверяет, настроена ли оплата через YooMoney полностью.

    Returns:
        True если YooMoney включена И есть client_id и secret_key
    """
    if not is_yoomoney_enabled():
        return False
    client_id = get_setting('yoomoney_client_id', '')
    secret_key = get_setting('yoomoney_secret_key', '')
    return bool(
        client_id and client_id.strip() and
        secret_key and secret_key.strip()
    )
```

- [ ] **Step 2: Update `get_yoomoney_credentials()` to return only client_id and secret_key**

```python
def get_yoomoney_credentials() -> tuple[str, str]:
    """
    Возвращает учётные данные YooMoney для API.

    Returns:
        Кортеж (client_id, secret_key)
    """
    client_id = get_setting('yoomoney_client_id', '') or ''
    secret_key = get_setting('yoomoney_secret_key', '') or ''
    return client_id, secret_key
```

- [ ] **Step 3: Commit**

```bash
git add database/db_settings.py
git commit -m "fix: update YooMoney credentials to use Client ID + Secret Key only"
```

---

## Task 2: Update YooMoney Payment Creation

**Covers:** Update payment creation to use Client ID + Secret Key authentication

**Files:**
- Modify: `bot/services/billing.py:1369-1472`

**Interfaces:**
- Consumes: `get_yoomoney_credentials()` returns (client_id, secret_key)
- Produces: `create_yoomoney_payment()` returns dict with payment details

- [ ] **Step 1: Update `create_yoomoney_payment()` to use Client ID + Secret Key**

```python
async def create_yoomoney_payment(
    amount_rub: float,
    order_id: str,
    description: str,
    bot_name: str
) -> Dict[str, Any]:
    """
    Создаёт платёжную ссылку в YooMoney.

    POST https://yoomoney.ru/api/checkout

    Args:
        amount_rub: Сумма в рублях
        order_id: Наш внутренний order_id
        description: Описание платежа
        bot_name: Username бота (для построения successRedirectUrl)

    Returns:
        Словарь с ключами:
            - yoomoney_label: label платежа (= order_id)
            - qr_image_data: PNG-байты QR-кода
            - qr_url: Ссылка для оплаты
            - status: Статус платежа

    Raises:
        ValueError: Если учётные данные не настроены
        RuntimeError: Если API вернул ошибку
    """
    client_id, secret_key = get_yoomoney_credentials()
    if not client_id or not secret_key:
        raise ValueError("YooMoney: не настроены client_id или secret_key")

    label = order_id

    payload = {
        "amount": f"{float(amount_rub):.2f}",
        "currency": "RUB",
        "label": label,
        "description": description[:128],
    }

    # Use Basic Auth with client_id:secret_key
    credentials = base64.b64encode(f"{client_id}:{secret_key}".encode()).decode()
    headers = {
        "Authorization": f"Basic {credentials}",
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
    }

    url = f"{YOOMONEY_API_URL}/checkout"

    async with aiohttp.ClientSession() as session:
        async with session.post(url, data=payload, headers=headers) as response:
            try:
                data = await response.json()
            except Exception:
                text = await response.text()
                logger.error(f"YooMoney API: невозможно разобрать ответ ({response.status}): {text}")
                raise RuntimeError("YooMoney API вернул некорректный ответ")

            if response.status not in (200, 201):
                error_desc = (
                    data.get('error')
                    or data.get('message')
                    or data.get('description')
                    or str(data)
                )
                logger.error(f"YooMoney API ошибка {response.status}: {error_desc} | payload={payload}")
                raise RuntimeError(f"YooMoney API ошибка: {error_desc}")

            # Ответ содержит paymentId и confirmation URL
            payment_id = data.get('id') or data.get('paymentId')
            confirmation = data.get('confirmation', {})
            qr_url = confirmation.get('confirmation_url') or data.get('pay_url', '')

            if not qr_url:
                logger.error(f"YooMoney API не вернул confirmation URL: {data}")
                raise RuntimeError("YooMoney API не вернул ссылку для оплаты")

            # Генерируем QR-код из ссылки
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_L,
                box_size=10,
                border=4,
            )
            qr.add_data(qr_url)
            qr.make(fit=True)

            img = qr.make_image(fill_color="black", back_color="white")
            bio = io.BytesIO()
            img.save(bio, format="PNG")
            qr_image_data = bio.getvalue()

            logger.info(
                f"YooMoney платёж создан: payment_id={payment_id}, order_id={order_id}, "
                f"amount={amount_rub} RUB, label={label}"
            )

            return {
                'yoomoney_payment_id': str(payment_id) if payment_id else '',
                'yoomoney_label': label,
                'qr_image_data': qr_image_data,
                'qr_url': qr_url,
                'status': str(data.get('status', 'pending')).lower(),
            }
```

- [ ] **Step 2: Commit**

```bash
git add bot/services/billing.py
git commit -m "fix: update YooMoney payment creation to use Client ID + Secret Key"
```

---

## Task 3: Update YooMoney Status Check

**Covers:** Update status checking to use Client ID + Secret Key authentication

**Files:**
- Modify: `bot/services/billing.py:1475-1540`

**Interfaces:**
- Consumes: `get_yoomoney_credentials()` returns (client_id, secret_key)
- Produces: `check_yoomoney_payment_status()` returns status string

- [ ] **Step 1: Update `check_yoomoney_payment_status()` to use Client ID + Secret Key**

```python
async def check_yoomoney_payment_status(order_id: str) -> str:
    """
    Проверяет статус платежа YooMoney по label.

    Uses YooMoney API to check if a payment with the given label exists
    and has status 'succeeded'.

    Args:
        order_id: Наш внутренний order_id (= label)

    Returns:
        Нормализованный статус: 'pending' | 'succeeded' | 'canceled'

    Raises:
        ValueError: Если учётные данные не настроены
        RuntimeError: Если API вернул ошибку
    """
    client_id, secret_key = get_yoomoney_credentials()
    if not client_id or not secret_key:
        raise ValueError("YooMoney: не настроены client_id или secret_key")

    # Use Basic Auth with client_id:secret_key
    credentials = base64.b64encode(f"{client_id}:{secret_key}".encode()).decode()
    headers = {
        "Authorization": f"Basic {credentials}",
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
    }

    # Проверяем последний платеж пользователя по label через operation-history
    history_url = f"{YOOMONEY_API_URL}/operation-history"
    history_payload = {
        "label": order_id,
        "records": 10,
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(history_url, data=history_payload, headers=headers) as response:
            try:
                data = await response.json()
            except Exception:
                text = await response.text()
                logger.error(f"YooMoney история: невозможно разобрать ответ ({response.status}): {text}")
                raise RuntimeError("YooMoney API вернул некорректный ответ")

            if response.status != 200:
                error_desc = data.get('error') or data.get('message') or str(data)
                logger.error(f"YooMoney история ошибка {response.status}: {error_desc}")
                raise RuntimeError(f"YooMoney API ошибка: {error_desc}")

            operations = data.get('operations', [])
            if not operations:
                return 'pending'

            # Ищем операцию с нужным label
            for op in operations:
                if op.get('label') == order_id:
                    status = str(op.get('status', '')).lower()
                    logger.debug(f"YooMoney operation {order_id}: status={status}")
                    if status == 'succeeded':
                        return 'succeeded'
                    if status in ('canceled', 'aborted', 'failed'):
                        return 'canceled'

            return 'pending'
```

- [ ] **Step 2: Commit**

```bash
git add bot/services/billing.py
git commit -m "fix: update YooMoney status check to use Client ID + Secret Key"
```

---

## Task 4: Verify Compilation

**Covers:** Ensure no syntax errors after changes

**Files:**
- None (verification only)

- [ ] **Step 1: Run compilation check**

```bash
python -m compileall .
```

Expected: No errors

- [ ] **Step 2: Commit if needed**

```bash
git add -A
git commit -m "chore: verify compilation after YooMoney fixes"
```

---

## Task 5: Test YooMoney Integration

**Covers:** Verify the complete payment flow works

**Files:**
- None (testing only)

- [ ] **Step 1: Start the bot**

```bash
python main.py
```

- [ ] **Step 2: Test the payment flow**

1. Click "💳 Купить ключ"
2. Click "💳 ЮMoney"
3. Select a tariff
4. Click "💳 Оплатить YooMoney"
5. Complete payment
6. Click "✅ Я оплатил"
7. Verify VPN key is issued

- [ ] **Step 3: Verify no regression in other payment methods**

Test at least one other payment method (Stars or Cards) to ensure it still works.

---

## Summary

After completing all tasks:
- YooMoney integration uses only Client ID + Secret Key
- API Token field is removed from configuration
- Payment creation and status checking work with new authentication
- All other payment methods remain functional
