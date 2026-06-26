import sqlite3, json

conn = sqlite3.connect('database/vpn_bot.db')
c = conn.cursor()

# Проверю текущее состояние
c.execute("SELECT buttons_custom FROM pages WHERE page_key='main'")
row = c.fetchone()
custom = json.loads(row[0]) if row[0] else []
for b in custom:
    if b.get('id') == 'btn_channel':
        print('Before toggle:', repr(b.get('is_hidden')))
        b['is_hidden'] = True
        print('Set to True:', repr(b.get('is_hidden')))
        break

# Сохраняем через прямой SQL
buttons_json = json.dumps(custom, ensure_ascii=False)
c.execute("UPDATE pages SET buttons_custom = ?, updated_at = CURRENT_TIMESTAMP WHERE page_key = 'main'", (buttons_json,))
print('Rows updated:', c.rowcount)
conn.commit()

# Проверяем
c.execute("SELECT buttons_custom FROM pages WHERE page_key='main'")
row = c.fetchone()
custom2 = json.loads(row[0]) if row[0] else []
for b in custom2:
    if b.get('id') == 'btn_channel':
        print('After save:', repr(b.get('is_hidden')))
        break

conn.close()
