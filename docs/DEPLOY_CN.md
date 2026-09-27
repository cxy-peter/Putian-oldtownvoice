# 国内访问部署说明（未实际部署）

选定路径：**Zeabur + 阿里云/腾讯云中国内地托管服务器 + GitHub 仓库 + Dockerfile**。不使用 Vercel，不把 GitHub Pages 当作后端。网页、HTTP API、WebSocket 都由同一个容器提供。

## 尚缺的部署权限

百炼 API Key 只用于识别与翻译，不等于 Zeabur 登录、服务器购买或域名配置权限。必须由账号所有者在平台完成登录、GitHub 仓库授权、服务器选择及费用确认。当前没有创建服务器、订阅或公共部署，也没有国内网络访问实测。

## 平台步骤

1. 登录 Zeabur，绑定 GitHub，授权访问 `cxy-peter/Putian-oldtownvoice`。
2. 选择中国内地的阿里云或腾讯云托管服务器。不要默认使用境外区域，也不要假设有永久免费内地实例。以控制台显示的区域、库存、收费为准；涉及订阅/自动续费需自己确认。
3. 在该服务器创建项目，从 GitHub 导入本仓库 `main`，项目根目录 `/`，使用根目录 `Dockerfile` 构建。HTTP 端口 `8080`，健康检查 `/healthz`，运行 **1 个副本**。
4. 创建持久存储卷，挂载目录 `/data`，环境变量 `DATA_DIR=/data`。SQLite 与音频都在这里。确认容器 UID `10001` 对挂载目录具有读写权限；不要用 `chmod 777` 绕过。挂载后新卷会遮住原目录，先做备份。**不要在无持久卷、多个副本或共享网络文件系统上使用本版 SQLite。**
5. 在平台“环境变量/Secret”中设置下表。不能写进 GitHub，不要在前端粘贴云密钥。
6. 绑定 HTTPS 域名，将准确的网站源写入 `PUBLIC_ORIGIN`，重新部署。WebSocket 必须可以升级到 `wss`；若平台要求显式开启长连接，开启并将空闲/请求超时设为大于 330 秒，或将本应用录音时长限制相应调短。
7. 用手机系统浏览器打开 HTTPS 地址，检查麦克风授权、完整录音、句尾收尾和刷新后的词库保存，再从实际中国内地网络验证。

| 环境变量 | 值 |
|---|---|
| `DASHSCOPE_API_KEY` | 百炼北京地域密钥，秘密变量 |
| `APP_ACCESS_CODE` | 自行生成至少 16 字符的随机访问码，秘密变量 |
| `DASHSCOPE_WORKSPACE_ID` | 通常留空；知道真实业务空间 ID 才填写，不能填 API Key 数字 ID |
| `PUBLIC_ORIGIN` | `https://你的实际域名`，不要含路径 |
| `HOST` | `0.0.0.0` |
| `PORT` | `8080` |
| `DATA_DIR` | `/data` |
| `MAX_DAILY_AUDIO_SECONDS` | `1800`，应用发送时长限制，非账单硬限额 |

首次部署可先不设置 `PUBLIC_ORIGIN` 以获取平台域名，但此时远程登录/识别会因来源限制被拒绝，这是预期的安全行为。拿到 HTTPS 域名后补齐再部署。

## 开发测试域名

Zeabur 官方提供有条件的“预备案子域名”：需要**从 Zeabur 购买的内地服务器、中国内地身份实名验证，以及受支持的服务器供应商**。不是任意海外账号免费开通的域名服务。官方将其定位为开发/临时测试，不建议用作正式商用域名。正式服务需按接入商与主管部门要求办理自己的域名备案等手续。

## 验收与运维

- `/healthz` 正常只证明进程存活，不证明百炼密钥或莆仙话识别有效。
- `/api/status` 不返回密钥；密钥配置为 true 也不是有效性验证。
- 登录后做一段 10–20 秒真实莆仙话试音。失败时核对北京地域、模型权限、余额与出口网络；先排除接口连接，再判断方言效果。
- 在词库中加一条测试词，保存、重启容器、重新登录，词条应仍存在。删掉该测试词。
- 浏览器开发者工具不得出现 `DASHSCOPE_API_KEY`。公网 `/data`、`/.env` 应为 404。
- 更新服务会中断正在录音的会话，界面保留已有文字但不会自动续接。平台持久卷模式本身可能不支持零停机更新。
- 用语料导出功能定期下载授权数据；敏感备份不要放进公开仓库。平台删除卷可能不可恢复。

## 其他国内平台

腾讯云 CloudBase **云托管**也可以承载 HTTP/WebSocket 容器，但仍需单实例、可写持久存储与账户授权。不要直接把这里的 Docker 参数当作“云函数”参数；本交付没有完成 CloudBase 配置或部署。

## 官方参考（2026-09-27 核对）

- https://zeabur.com/docs/zh-CN/deploy/github
- https://zeabur.com/docs/zh-CN/deploy/dockerfile
- https://zeabur.com/docs/zh-CN/server/purchase
- https://zeabur.com/docs/zh-CN/data-management/volumes
- https://zeabur.com/docs/zh-CN/networking/pre-icp-subdomain
- https://docs.cloudbase.net/run/introduction
