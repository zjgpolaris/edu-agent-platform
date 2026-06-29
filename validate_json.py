import json

try:
    with open('knowledge_base/history/geo_events.json', 'r', encoding='utf-8') as f:
        json.load(f)
    print('JSON valid')
except json.JSONDecodeError as e:
    print(f'JSON invalid at line {e.lineno}, column {e.colno}: {e.msg}')
except Exception as e:
    print(f'Error: {e}')
