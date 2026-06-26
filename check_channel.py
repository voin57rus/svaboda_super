import sqlite3, json
conn = sqlite3.connect('database/vpn_bot.db')
c = conn.cursor()
c.execute("SELECT buttons_custom FROM pages WHERE page_key='main'")
row = c.fetchone()
custom = json.loads(row[0]) if row[0] else []
for b in custom:
    if b.get('id') == 'btn_channel':
        print(repr(b))
conn.close()
