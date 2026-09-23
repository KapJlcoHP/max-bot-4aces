from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI(title="4Aces Mini App")


@app.get("/", response_class=HTMLResponse)
async def index():
    return """<!doctype html>
<html lang="ru">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>4Aces Mini App</title>
    <script src="https://st.max.ru/js/max-web-app.js"></script>
  </head>
  <body>
    <main>Mini App</main>
  </body>
</html>"""
