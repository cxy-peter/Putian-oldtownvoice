# Vercel + Cloudflare 部署

## 当前状态

代码已提供云端适配，但本次执行环境的 Vercel 部署动作报 `Tool deploy_to_vercel not found`；没有可用的 Cloudflare 账号授权或已指定域名。**因此没有生产网址，没有购买域名、修改 DNS 或配置线上秘密。**

## 1. 先部署 Vercel

从 README 的导入按钮选择 `cxy-peter/Putian-oldtownvoice`，根目录保持仓库根目录，Framework 选择 FastAPI。`pyproject.toml` 指定 `cloud_app:app`，`vercel.json` 指定 300 秒函数时长。使用支持 WebSocket 的 Fluid Compute。不要把旧 `app.py` 当云端入口。

设置 Production 环境的 `DASHSCOPE_API_KEY`、`DASHSCOPE_WORKSPACE_ID`、至少 24 位的 `APP_ACCESS_CODE`、随机 `SESSION_SECRET`。不要把原 CSV 上传 GitHub或粘贴到前端。更便利的方式是在自己的电脑执行：

```bash
npm install -g vercel
python scripts/deploy_vercel.py --csv "你的百炼导出.csv"
```

脚本使用你的官方 CLI 登录，不需要把 Vercel Token 发到聊天。它兼容 apiKey/workspaceId 键值导出及非 sk- 前缀密钥，核对北京官方主机。只解析文件不验证凭据有效性。

成功后先打开平台返回的生产 URL，检查 `/healthz`，再用应用访问码登录。必须实际测试 WebSocket，不要只看首页。部署受保护时，可按你的分享意图在控制台配置访客权限；不要把平台绕过令牌写进公开代码。应用访问码仍必须保留。

## 2. 自有域名：Cloudflare DNS + Vercel

需要一个你拥有并已接入 Cloudflare 的域名。这里以 `voice.example.com` 为示意，不能直接使用它。

1. Vercel 项目 Settings → Domains 添加所选子域名。
2. 在 Cloudflare DNS 填入 **Vercel 为这个项目实际给出的记录类型、名称和目标**；不硬编码旧 A 记录/IP。
3. 初次验证可以 DNS only；确认 Vercel 域名及 TLS 证书均有效后再评估是否开启 Cloudflare Proxied。
4. 开代理时使用 Full (strict) SSL，不使用 Flexible；不要对 `/api/*`、`/ws` 或登录响应使用 Cache Everything。保留 WebSocket Upgrade。
5. Vercel 添加 `ALLOWED_ORIGINS=https://voice.example.com` 后重新部署。多个入口用逗号分隔，不使用通配符。不要信任任意 Host / Origin 来绕过来源校验。

DNS only 是使用 Cloudflare 解析，不等于流量经过 Cloudflare 代理。Vercel 官方不推荐在其前方额外放反向代理，因为会增加链路、缓存和安全可见性问题；在这里属于可选实验，需要实测。

## 3. 可选 Worker 入口

没有先做自有域名时，也可以通过 Cloudflare 账号部署测试用 Worker；`workers.dev` 不是国内可达保证，也不是中国大陆网络。

在 `cloudflare/wrangler.toml` 中，把 `UPSTREAM_ORIGIN` 改为**部署成功后实际返回的固定 Vercel 生产来源**，只含 `https://...vercel.app`，不能含路径。

```bash
cd cloudflare
npx wrangler login
npx wrangler deploy
```

只在你确认的平台账号和计划下运行。部署会使用该账号的额度，超出免费用量是否收费以控制台为准。

拿到实际 Worker HTTPS 来源后，将它添加到 Vercel `ALLOWED_ORIGINS`，再部署 Vercel。Worker 保留浏览器原始 Origin、Cookie 和 WebSocket 101 响应；只允许固定 Vercel 上游，不是任意 URL 开放代理。不在 Worker 放百炼密钥。

自有域名可在 Worker Settings → Domains & Routes 添加 Custom Domain。使用 Worker 路线时无需再把同一个域名反复 CNAME 到 Vercel；按所选路线配置，避免回源循环。Vercel 上游应能直接访问，不重定向回 Worker 域名。

## 4. 必须验收

电脑与国内手机：HTTPS 页面加载、访问码登录、麦克风授权、持续录音、草稿更新、最终句子、停录后最后一句、翻译失败保留原文。用真实莆仙话短句配人工答案评估，不能用普通话样本通过来宣称莆仙话准确。

云端单次录音 240 秒，Vercel 函数时长 300 秒；函数停止会中断 WebSocket。应用不自动重放音频，避免重复识别/扣费。

词库和语料保存在浏览器 IndexedDB，不跨设备或域名同步。变更入口域名前先导出词库 JSON 和完整音频 ZIP。实际浏览器持久性/配额与国内链路尚未在本次环境验收。

## 官方依据（2026-09-27 核对）

- [Vercel WebSocket / 函数时长与状态管理](https://vercel.com/docs/functions/websockets)
- [FastAPI 自定义入口](https://vercel.com/docs/frameworks/backend/fastapi)
- [Cloudflare 放在 Vercel 前的取舍](https://vercel.com/kb/guide/cloudflare-with-vercel)
- [Cloudflare Workers WebSocket](https://developers.cloudflare.com/workers/runtime-apis/websockets/)
- [Cloudflare China Network](https://developers.cloudflare.com/china-network/)

Cloudflare 的免费全球代理、DNS 与 workers.dev 均不同于单独的 China Network 企业服务。换域名可能改变路径，但没有由此保证国内可达。
