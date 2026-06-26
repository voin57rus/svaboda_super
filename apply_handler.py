with open('bot/handlers/admin/system.py', 'r') as f:
    content = f.read()

with open('handler_code.txt', 'r') as f:
    handler = f.read()

# Remove the broken handler if exists
start = content.find('@router.callback_query(F.data.startswith("edit_image:"))')
end = content.find('@router.callback_query(F.data.startswith("edit_text:"))')
if start != -1 and end != -1:
    content = content[:start] + content[end:]
    print("Removed old broken handler")

# Insert new handler before edit_text_start
marker = '@router.callback_query(F.data.startswith("edit_text:"))'
pos = content.find(marker)
if pos != -1:
    content = content[:pos] + handler + content[pos:]
    print("Handler inserted!")

with open('bot/handlers/admin/system.py', 'w') as f:
    f.write(content)

print("Done!")
