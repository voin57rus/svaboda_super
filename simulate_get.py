import sqlite3, json

# Simulate what _get_help_button does
conn = sqlite3.connect('database/vpn_bot.db')
c = conn.cursor()

c.execute("SELECT buttons_custom, buttons_default FROM pages WHERE page_key='main'")
row = c.fetchone()

buttons_custom = row[0] if row[0] else None
buttons_default = row[1] if row[1] else '[]'

print('buttons_custom type:', type(buttons_custom))
print('buttons_custom truthy:', bool(buttons_custom))

# This is what _get_help_button does
buttons_json = buttons_custom or buttons_default
print('buttons_json type:', type(buttons_json))
print('buttons_json first 50:', buttons_json[:50] if buttons_json else 'EMPTY')

buttons = json.loads(buttons_json)
btn_id = 'btn_channel'
found = False
for btn in buttons:
    if btn.get('id') == btn_id:
        print(f'Found {btn_id}: is_hidden={btn.get("is_hidden")}')
        found = True
        break

if not found:
    print(f'{btn_id} NOT FOUND')
    print('Available ids:', [b.get('id') for b in buttons])

conn.close()
