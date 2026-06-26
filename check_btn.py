import sqlite3, json

conn = sqlite3.connect('database/vpn_bot.db')
c = conn.cursor()

c.execute("SELECT buttons_custom FROM pages WHERE page_key='main'")
row = c.fetchone()
buttons_json = row[0] if row[0] else '[]'

buttons = json.loads(buttons_json)
for btn in buttons:
    if btn.get('id') == 'btn_channel':
        print('Found btn_channel:', repr(btn))
        break
else:
    print('btn_channel NOT FOUND in buttons_custom')
    print('All button ids:', [b.get('id') for b in buttons])

conn.close()
