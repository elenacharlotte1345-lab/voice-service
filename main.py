from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
import os
import shutil
import uuid
import json
import numpy as np
from xiaozhi_service import XiaozhiService
from audio_utils import convert_audio_to_pcm

# 临时音频存储目录
AUDIO_DIR = "temp_audio"
os.makedirs(AUDIO_DIR, exist_ok=True)

# 全局 WebSocket 客户端
service = XiaozhiService()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时连接
    await service.connect()

    yield
    # 关闭时清理
    await service.close()

app = FastAPI(title="Voice Q&A Service", lifespan=lifespan)
app.mount("/audio", StaticFiles(directory=AUDIO_DIR), name="audio")

@app.post("/ask")
async def ask(
    audio_file: UploadFile = File(None),
    text: str = Form(None)
):
    if not audio_file and not text:
        raise HTTPException(status_code=400, detail="Provide audio_file or text")
    
    try:
        if audio_file:
            # 语音输入
            contents = await audio_file.read()
            pcm_bytes = convert_audio_to_pcm(contents, audio_file.filename)
            recognized, reply, audio_path = await service.ask_audio(pcm_bytes)
        else:
            # 文本输入
            recognized, reply, audio_path = await service.ask_text(text)
        
        # 处理返回的音频文件，提供可访问 URL
        audio_url = None
        if audio_path and os.path.exists(audio_path):
            # 复制到静态目录
            new_filename = f"reply_{uuid.uuid4().hex}.wav"
            dest_path = os.path.join(AUDIO_DIR, new_filename)
            shutil.move(audio_path, dest_path)  # 移动而非复制，避免残留
            audio_url = f"/audio/{new_filename}"
        
        return {
            "recognized_text": recognized,
            "reply_text": reply,
            "reply_audio_url": audio_url
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health():
    return {"status": "ok"}