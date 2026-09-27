# 验证记录 · 2026-09-27

| 范围 | 结果 |
|---|---|
| Python 单元 / HTTP / WebSocket 测试 | 42 项通过 |
| 连续重采样 | 16k / 44.1k / 48k 三种输入采样率通过，含下混、帧数、量化与停止收尾 |
| 浏览器离线 DOM/UI 测试 | 16 项通过；1440px 桌面与 390px 手机宽度、词库/标注交互、最终结果替换、校正不覆盖原文 |
| 百炼真实 API | 未验证；运行环境无法解析/连接百炼域名，未成功发出识别调用 |
| 真实莆仙话音频 | 未提供，未测字错率或语义正确率 |
| 浏览器到本机 HTTP 全链路/真实麦克风 | 当前浏览器策略阻止本机网址加载，完整 browser_smoke.py 未完成；离线 UI 检查不是其替代证明 |
| 真机 iOS / Android | 未测试；390px 检查只是浏览器布局，不是真机兼容认证 |
| Docker build / 云平台运行 | 已提供配置，当前环境无 Docker，未执行构建或部署 |
| 微调 | 未执行，没有模型权重产物 |

后端 WebSocket 测试使用真实本机双向连接和模拟上游：发送二进制 PCM、收到草稿、发送 finish-task、收到最后完整句子再完成。没有把本地模拟结果当作云端识别。

离线浏览器检查用内存 API fixtures 和显式“模拟上游”文字，无真实声音识别。用于检查 UI 的音频是合成测试数据，不进入用户语料。

复现：

```bash
python -m unittest discover -s tests -v
node tests/worklet.test.cjs
# 可选浏览器测试需另装 playwright 与浏览器：
python tests/browser_render.py
# 有允许本机浏览器联网/麦克风的开发环境后再执行：
python tests/browser_smoke.py
```

测试不读取 `.env`，不会自动调用计费接口。`scripts/live_check.py` 是单独的、需要真实授权录音的计费测试入口。
