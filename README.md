# PetShop

Сайт на FastAPI без Jinja2. HTML/CSS формируются напрямую, база данных предпочитает файл Access KyrsovaFA1.accdb, а если драйвер недоступен — автоматически работает SQLite fallback.

Установка:
pip install -r requirements.txt
uvicorn main:app --reload      # http://127.0.0.1:8000

Демо: покупець alina@mail.com / 12345678, продавець seller@petshop.ua / seller123
