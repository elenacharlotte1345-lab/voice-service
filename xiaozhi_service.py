import asyncio
import json
import uuid
import requests
import tempfile
import os
import wave
from urllib.parse import urlparse, parse_qs, urlunparse, urlencode
import websockets
from audio_utils import AudioProcessor, save_pcm_to_wav, SAMPLE_RATE, FRAME_DURATION_MS

OTA_URL = "http://127.0.0.1:8003/xiaozhi/ota/"

class XiaozhiService:
    def __init__(self):
        self.websocket = None
        self.session_id = None
        self.device_id = None
        self.client_id = None
        self.device_mac = None
        self.ws_token = None
        self.audio_processor = AudioProcessor()
        self._connected = False

    def _generate_device_info(self):
        self.device_id = f"voice_service_{uuid.uuid4().hex[:8]}"
        self.client_id = f"voice_service_{uuid.uuid4().hex[:8]}"
        self.device_mac = ":".join([f"{uuid.uuid4().hex[:2]}" for _ in range(6)]).upper()

    

    async def _get_websocket_url(self):
        self._generate_device_info()
        ota_body = {
            "version": 0, "uuid": "",
            "application": {
                "name": "voice-service",
                "version": "1.0.0",
                "compile_time": "2025-06-11 00:00:00"
            },
            "ota": {"label": "voice-service"},
            "board": {
                "type": "VoiceServiceClient",
                "mac": self.device_mac
            },
            "mac_address": self.device_mac
        }
        ota_headers = {
            "Content-Type": "application/json",
            "Device-Id": self.device_id,
            "Client-Id": self.client_id
        }
        try:
            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(None, lambda: requests.post(OTA_URL, json=ota_body, headers=ota_headers, timeout=5))
            if response.status_code == 200:
                ota_data = response.json()
                websocket_info = ota_data.get('websocket', {})
                ws_url = websocket_info.get('url', 'ws://127.0.0.1:8000/xiaozhi/v1/')
                self.ws_token = websocket_info.get('token', '')
                parsed = urlparse(ws_url)
                query_params = parse_qs(parsed.query)
                if self.ws_token:
                    query_params['authorization'] = [f"Bearer {self.ws_token}"]
                query_params['device-id'] = [self.device_id]
                query_params['client-id'] = [self.client_id]
                new_query = urlencode(query_params, doseq=True)
                return urlunparse(parsed._replace(query=new_query))
        except Exception as e:
            print(f"OTA请求失败: {e}")
        return "ws://127.0.0.1:8000/xiaozhi/v1/"

    async def connect(self):
        ws_url = await self._get_websocket_url()
        print(f"Connecting to {ws_url}")
        self.websocket = await websockets.connect(ws_url, subprotocols=["xiaozhi-esp32"])
        hello_msg = {
            "type": "hello",
            "device_id": self.device_id,
            "device_name": "Voice Service",
            "device_mac": self.device_mac,
            "token": self.ws_token,
            "features": {"mcp": True}
        }
        await self.websocket.send(json.dumps(hello_msg))
        response = await self.websocket.recv()
        data = json.loads(response)
        if data.get('type') == 'hello':
            self.session_id = data.get('session_id')
            self._connected = True
            print(f"✅ Handshake success, session_id={self.session_id}")
            return True
        return False

    async def _reset_session(self):
        """发送 abort 消息，清空接收缓冲区，重置会话状态"""
        if not self.websocket or not self._connected:
            return
        try:
            # 发送 abort
            await self.websocket.send(json.dumps({
                "session_id": self.session_id,
                "type": "abort"
            }))
            await asyncio.sleep(0.2)  # 等待服务器处理
            
            # 清空所有还在接收队列中的消息（重要！）
            while True:
                try:
                    msg = await asyncio.wait_for(self.websocket.recv(), timeout=0.1)
                    # 可选日志：print(f"丢弃残留消息: {type(msg)}")
                except asyncio.TimeoutError:
                    break
        except Exception as e:
            print(f"重置会话失败: {e}")

    async def ask_audio(self, pcm_bytes: bytes):
        """发送音频 PCM 字节，返回 (识别文本, AI回复, TTS音频文件路径)"""
        if not self._connected:
            raise RuntimeError("WebSocket not connected")
        
        # 重置之前的会话
        await self._reset_session()

        # 1. 编码为 Opus 包
        packets = self.audio_processor.encode_pcm_to_opus_packets(pcm_bytes)

        # 2. 发送 listen detect 和 start
        await self.websocket.send(json.dumps({
            "session_id": self.session_id,
            "type": "listen",
            "state": "detect"
        }))
        await self.websocket.send(json.dumps({
            "session_id": self.session_id,
            "type": "listen",
            "state": "start",
            "mode": "manual"
        }))

        # 3. 发送静音头
        silence_packets = self.audio_processor.generate_silence_packets(count=6)
        for sp in silence_packets:
            await self.websocket.send(sp)
            await asyncio.sleep(FRAME_DURATION_MS / 1000.0)

        # 4. 发送音频数据
        for packet in packets:
            await self.websocket.send(packet)
            await asyncio.sleep(FRAME_DURATION_MS / 1000.0)

        # 5. 发送静音尾
        for sp in silence_packets:
            await self.websocket.send(sp)
            await asyncio.sleep(FRAME_DURATION_MS / 1000.0)

        # 6. 停止录音
        await self.websocket.send(json.dumps({
            "session_id": self.session_id,
            "type": "listen",
            "state": "stop"
        }))

        # 7. 接收结果
        recognized_text = "小智你好"
        ai_reply = ""
        tts_texts = []
        audio_frames = []   # 收集二进制音频帧

        while True:
            try:
                msg = await asyncio.wait_for(self.websocket.recv(), timeout=60)
                if isinstance(msg, bytes):
                    audio_frames.append(msg)
                    continue

                data = json.loads(msg)
                msg_type = data.get('type')

                if msg_type == 'stt':
                    text = data.get('text', '')
                    print(f"🗣️ 识别文本: {text}")
                    if not text.startswith("%"):
                        recognized_text = text
                elif msg_type == 'llm':
                    ai_reply = data.get('text', '')
                    print(f"🤖 llm 回复: {ai_reply}")
                elif msg_type == 'tts':
                    state = data.get('state')
                    text = data.get('text', '')
                    if text:
                        tts_texts.append(text)
                        print(f"🔊 tts 文本: {text}")
                    if state == 'stop':
                        await asyncio.sleep(0.2)  # 让服务器完全结束
                        break
                elif msg_type in ('sentence_end', 'response_end', 'speech_end', 'session_end'):
                    break
                elif msg_type == 'error':
                    break
                elif msg_type == 'mcp':
                    break
                else:
                    print(f"⚠️ 未知消息 type={msg_type}: {data}")
            except asyncio.TimeoutError:
                print("接收超时，退出")
                break

        # 8. 保存 TTS 音频（如果有）
        audio_path = None
        if audio_frames:
            pcm_data = b''
            for opus_packet in audio_frames:
                pcm_data += self.audio_processor.decode_opus_to_pcm(opus_packet)

            # 保存为临时 WAV 文件
            fd, audio_path = tempfile.mkstemp(suffix=".wav", prefix="reply_")
            os.close(fd)
            save_pcm_to_wav(pcm_data, audio_path)
        else:
            print("未收到任何二进制音频数据")

        # 9. 合并 LLM 和 TTS 文本（如果 TTS 有文本，通常更完整）
        if tts_texts:
            ai_reply = ai_reply + " ".join(tts_texts)

        return recognized_text, ai_reply, audio_path

    async def ask_text(self, text: str):
        """发送纯文本，返回 (user_text, AI回复, TTS音频文件路径)"""
        if not self._connected:
            raise RuntimeError("WebSocket not connected")

        # 重置之前的会话
        await self._reset_session()

        # 发送 listen 消息并附加 text 字段（根据 test6.py 中的协议扩展）
        listen_msg = {
            "session_id": self.session_id,
            "type": "listen",
            "state": "detect",
            "mode": "manual",
            "text": text
        }
        await self.websocket.send(json.dumps(listen_msg))
        print(f"📝 发送文本消息: {text}")

        # 注意：某些服务器版本可能需要手动发送 start 和 stop，这里假设发送 text 后服务器自动处理
        # 为了兼容，可以立即发送 listen stop
        await self.websocket.send(json.dumps({
            "session_id": self.session_id,
            "type": "listen",
            "state": "stop"
        }))

        # 接收结果（逻辑与 ask_audio 相同）
        ai_reply = ""
        tts_texts = []
        audio_frames = []

        while True:
            try:
                msg = await asyncio.wait_for(self.websocket.recv(), timeout=20)
                if isinstance(msg, bytes):
                    audio_frames.append(msg)
                    continue

                data = json.loads(msg)
                msg_type = data.get('type')

                if msg_type == 'llm':
                    ai_reply = data.get('text', '')
                    print(f"🤖 llm 回复: {ai_reply}")
                elif msg_type == 'tts':
                    state = data.get('state')
                    tts_text = data.get('text', '')
                    if tts_text:
                        tts_texts.append(tts_text)
                        print(f"🔊 tts 文本: {tts_text}")
                    if state == 'stop':
                        await asyncio.sleep(0.2)  # 让服务器完全结束
                        break
                elif msg_type in ('sentence_end', 'response_end', 'speech_end', 'session_end'):
                    break
                elif msg_type == 'error':
                    print(f"❌ 错误: {data}")
                    break
            except asyncio.TimeoutError:
                print("接收超时")
                break

        # 保存音频
        audio_path = None
        if audio_frames:
            pcm_data = b''
            for opus_packet in audio_frames:
                pcm_data += self.audio_processor.decode_opus_to_pcm(opus_packet)
            fd, audio_path = tempfile.mkstemp(suffix=".wav", prefix="reply_")
            os.close(fd)
            save_pcm_to_wav(pcm_data, audio_path)
        if tts_texts:
            ai_reply = ai_reply + " ".join(tts_texts)

        return text, ai_reply, audio_path

    async def close(self):
        if self.websocket:
            await self.websocket.close()
        self._connected = False