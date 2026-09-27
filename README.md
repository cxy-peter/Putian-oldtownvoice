# 乡音 · 莆田老城声

面向莆田话 / 莆仙话的流式转写、人工校正与语料积累原型。电脑和手机共用网页；Python + aiohttp 后端提供真实双向 WebSocket。不是 Streamlit 截图，也不是按字播放预置答案。

**状态：代码与本地协议测试已完成；百炼真实请求、莆仙话准确率、手机实机和国内公网部署尚未验证。没有运行微调，没有声称 90% 准确率。**

## 功能

- 麦克风 AudioWorklet 持续发送 16kHz 单声道 PCM16；约 100ms 一帧。停止后等上游最终句尾再关闭；断网不伪造结果。
- 三种云端引擎可选：Qwen Audio 3.1 Streaming（默认、即时热词、保留方言）、Qwen3 ASR Realtime（对照、不传无效热词参数）、Fun-ASR Realtime（上下文对照）。
- 单次识别最多 5 分钟；上传音频在浏览器转码后按原速流式发送，不是高速批量文件转写。
- 原始转写、人工校正、标准中文 / 英文译文分开。翻译可按最终句子自动触发；朗读使用浏览器系统语音，不是云端千问 TTS。
- 手动热词、权重、释义、经母语者核对的例句；JSON 导入导出、版本冲突保护、SQLite 持久化。识别中改词库从下一次会话生效。
- 独立“仅录音采集”模式不调用 ASR。单条 0.3–60 秒的真实音频，经授权与核对后保存到私有语料库；支持导出、删除、说话人隔离的 train/dev/test 划分。MVP 限 100 条音频，不用于大规模存储。
- 所有 API Key 仅在服务端。共享应用访问码用于小范围内测；**不是多租户系统**，持码者可查看、编辑、导出和删除该实例的语料。不要公开访问码。

## 为什么没有直接照抄“完整指南”

官方明确支持即时热词与 `keep_dialect` 的是 `qwen-audio-3.1-asr-flash-streaming`。它的 `run-task` 协议不同于 `qwen3-asr-flash-realtime` 的 `session.update` 协议，也不同于非实时 `qwen3-asr-flash`。不能把这些模型参数互相混用。

`zh` 是中文提示，不是“莆仙话专用模型”的证明。“支持闽南语”“训练覆盖闽语”都不能替代真实莆仙话评测。当前默认模型只是待验证候选；地区下拉框是录音者提供的信息，不是自动方言分类结果。

官方资料（核对日期 2026-09-27）：
- [模型与语言列表](https://help.aliyun.com/zh/model-studio/asr-model)
- [新流式 / Fun-ASR 客户端事件](https://help.aliyun.com/zh/model-studio/fun-asr-client-events)
- [对应服务端事件](https://help.aliyun.com/zh/model-studio/fun-asr-server-events)
- [Qwen3 实时客户端事件](https://help.aliyun.com/zh/model-studio/qwen-asr-realtime-client-events)
- [Qwen3 实时服务端事件](https://help.aliyun.com/zh/model-studio/qwen-asr-realtime-server-events)

## 本地运行

Python 3.11+，推荐 3.12。与上个 Node 版是独立项目，不要沿用旧的 `npm start`。

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS / Linux:
# source .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/setup.py "你的百炼密钥.csv"
python app.py
```

打开 `http://localhost:8787`，在“连接设置”填配置脚本生成的**应用访问码**，不是 API Key。Windows 也可运行 `start_windows.bat`。没有 CSV 时运行 `python scripts/setup.py`，通过隐藏输入配置密钥。

CSV 中的 API Key 数字 ID **不是业务空间 Workspace ID**。默认使用北京地域兼容接入地址；只在确知实际业务空间 ID 时配置 `DASHSCOPE_WORKSPACE_ID`。地区或权限不匹配时会明确失败，不会自动换模型掩盖错误。

`.env` 不在源码包和 GitHub 中。部署到另一台服务器时仍需在其秘密环境变量中配置密钥。本地 `.env` 不会随 GitHub 自动同步。

没有密钥也可配置 `.env.example` 中的长访问码，使用“仅录音采集”和语料整理。云端识别、翻译不可用时不会返回假结果。

## 国内部署，不使用 Vercel

参考 [国内部署说明](docs/DEPLOY_CN.md)。准备了 Dockerfile；目标是有长连接能力的容器平台，不是静态网页托管。

建议采用 **Zeabur + 中国内地托管服务器** 的 GitHub 导入方式，挂载持久卷 `/data`，配置秘密环境变量和 HTTPS。需要平台账号、服务器与域名/测试域名条件；本仓库不包含部署授权，也没有已上线网址。

## 测试与后续改进

```bash
python -m unittest discover -s tests -v
# 可选，Node 18+，不需要 npm install：
node tests/worklet.test.cjs
```

[验证记录](docs/VALIDATION.md) 区分本地测试、离线界面检查、未执行的真实识别。真实连接自检会调用计费 API，须自行确认录音授权与账户额度：

```bash
python scripts/live_check.py consented_16k_mono.wav qwen31
```

[语料、评测与微调说明](docs/CORPUS.md) 提供训练格式转换入口。热词和例句不是修改模型权重；在没有真实音频、人工标注与独立测试说话人之前，不标记为“已微调莆仙话模型”。

## 边界

这是单实例、单进程、小范围验证 MVP。前端不依赖海外 CDN。服务端只向固定的阿里云北京地域主机发送请求，不接受任意音频 URL。音频默认仅保留在浏览器当前会话，只有确认保存语料才持久化；识别本身仍会发送至百炼。请按照录音者授权范围处理、删除数据，并查看云服务方的数据条款。

默认最多两个同时识别任务、每日发送音频 1800 秒。这个应用内限额不是阿里云计费硬上限，翻译另计；请同时在云端设置预算与额度。公网开放前应补独立用户权限、审计、可靠备份与基础设施监控。
