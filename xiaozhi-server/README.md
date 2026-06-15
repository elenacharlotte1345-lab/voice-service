## 安装依赖

```bash
# 进入 xiaozhi-server 目录
cd main/xiaozhi-server

# 安装依赖
pip install -r requirements.txt
```

**注意**：如果下载速度慢，可使用国内镜像源：
```bash
pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/
pip install -r requirements.txt
```

## 安装系统级依赖（重要）

需要安装 `opus`、`libopus` 和 `ffmpeg`：

```bash
# Ubuntu / Debian / WSL
sudo apt update
sudo apt install libopus0 opus-tools ffmpeg -y

# macOS
brew install opus ffmpeg

# Windows（使用 WSL2）同上
```

## 下载离线语音识别模型（FunASR + SenseVoiceSmall）

默认使用 FunASR 离线语音识别，需下载模型文件：

```bash
# 创建模型目录
mkdir -p models/SenseVoiceSmall

# 下载模型（约 1GB）
wget https://modelscope.cn/models/iic/SenseVoiceSmall/resolve/master/model.pt \
  -O models/SenseVoiceSmall/model.pt
```

> 如果网络问题无法下载，可使用 HuggingFace 源：
```bash
wget https://huggingface.co/FunAudioLLM/SenseVoiceSmall/resolve/main/model.pt \
  -O models/SenseVoiceSmall/model.pt
```

## 配置 config.yaml

将配置文件模板放置到正确位置：

```bash
# 将 config.yaml 复制到 data 目录并重命名为 .config.yaml
cp config.yaml data/.config.yaml
```

> **重要**：配置文件必须是 `.config.yaml`（注意开头的点），程序启动时从 `data/.config.yaml` 读取配置。

配置文件核心配置说明：

**1. 基础服务器设置**
```yaml
server:
  ip: 0.0.0.0                    # 监听所有网卡
  port: 8000                     # WebSocket 端口
  only_esp32_xiaozhi_connect: false  # 生产环境建议设为 true
```
> **注意**：如果要在局域网内被其他设备访问，`ip` 不能写 `127.0.0.1`，要写 `0.0.0.0` 或本机局域网 IP。

**2. 模块选择**
```yaml
selected_module:
  ASR: FunASR                    # 语音识别：FunASR（本地离线）
  VAD: SileroVAD                 # 语音活动检测
  LLM: ChatGLMLLM                # 大语言模型（可改为 DeepSeekLLM、AliyunLLM）
  TTS: EdgeTTS                   # 语音合成（免费，无需密钥）
```

**3. ASR 配置（FunASR + SenseVoiceSmall）**
```yaml
ASR:
  FunASR:
    model_dir: models/SenseVoiceSmall
    output_dir: tmp/
```

**4. LLM 配置（以智谱 ChatGLM 为例）**
```yaml
ChatGLMLLM:
  api_key: "你的智谱 API Key"        # 必填，从 https://bigmodel.cn/usercenter/proj-mgmt/apikeys 获取
  model: "glm-4-plus"
```

其他 LLM 配置示例：
- **DeepSeekLLM**：`api_key: "你的 DeepSeek API Key"`，`model: "deepseek-chat"`
- **阿里百炼（Qwen）**：`api_key: "你的阿里云 API Key"`，`model: "qwen-plus"`

**5. TTS 配置（EdgeTTS，免费无需密钥）**
```yaml
TTS:
  EdgeTTS:
    voice: "zh-CN-XiaoxiaoNeural"
```
> EdgeTTS 是免费的 Windows 语音服务，无需任何 API Key，开箱即用，适合快速测试。

**6. VAD 配置（语音活动检测，可选调整）**
```yaml
VAD:
  SileroVAD:
    threshold: 0.5
    min_silence_duration_ms: 700
```

## 启动服务

```bash
# 在 main/xiaozhi-server 目录下执行
python app.py
```

启动成功后的输出示例：
```
Server is running at ws://0.0.0.0:8000
server listening on 0.0.0.0:8000
```
> 记住你的服务器 WebSocket 地址（例如：`ws://192.168.1.100:8000`），后续其他服务需要用这个地址连接。

**后台启动方式**：
```bash
nohup python app.py > server.log 2>&1 &
```

## 验证服务是否正常运行

```bash
# 检查端口是否在监听
netstat -an | grep 8000

# 访问 OTA 接口，确认服务已启动（应返回 JSON）
curl http://127.0.0.1:8003/xiaozhi/ota/
```

