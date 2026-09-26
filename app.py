# app.py
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from database import Base, engine
import models
from routes import router
from websocket import chat_websocket

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Anya Messenger")
app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(router)


@app.websocket("/ws/chat/{chat_id}")
async def ws_chat(websocket: WebSocket, chat_id: int):
    await chat_websocket(websocket, chat_id)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 401:
        return RedirectResponse("/login", status_code=302)
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)