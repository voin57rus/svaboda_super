import sqlite3, json

conn = sqlite3.connect('database/vpn_bot.db')
c = conn.cursor()

c.execute("SELECT buttons_custom FROM pages WHERE page_key='main'")
row = c.fetchone()
custom = json.loads(row[0]) if row[0] else []

for b in custom:
    if b.get('id') == 'btn_channel':
        b['is_hidden'] = not b.get('is_hidden', False)
        print('Toggled to:', b['is_hidden'])
        break

c.execute("UPDATE pages SET buttons_custom = ?, updated_at = CURRENT_TIMESTAMP WHERE page_key = 'main'", 
          (json.dumps(custom, ensure_ascii=False),))
conn.commit()

c.execute("SELECT buttons_custom FROM pages WHERE page_key = 'main'")
row = c.fetchone()
custom2 = json.loads(row[0]) if row[0] else []
for b in custom2:
    if b.get('id') == 'btn_channel':
        print('After save, is_hidden:', b.get('is_hidden'))
        break

conn.close()
