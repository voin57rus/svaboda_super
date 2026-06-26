import sqlite3
conn = sqlite3.connect('database/vpn_bot.db')
c = conn.cursor()
c.execute("SELECT length(buttons_custom), length(buttons_default) FROM pages WHERE page_key='main'")
row = c.fetchone()
print('buttons_custom length:', row[0])
print('buttons_default length:', row[1])
c.execute("SELECT buttons_custom FROM pages WHERE page_key='main'")
row2 = c.fetchone()
bc = row2[0] if row2 else None
if bc:
    print('First 100 chars of buttons_custom:', bc[:100])
else:
    print('buttons_custom is NULL')
conn.close()
