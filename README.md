# 乡音 · 莆田老城声 v0.3

面向莆田 / 莆仙话的流式识别、人工校正、翻译和语料积累原型。**尚未完成真实百炼调用、莆仙话准确率验证或模型微调。**不能把闽南话支持当作莆仙话验收。

## Vercel 云端版

[从当前 GitHub 仓库导入 Vercel](https://vercel.com/new/import?s=https%3A%2F%2Fgithub.com%2Fcxy-peter%2FPutian-oldtownvoice)

选择本仓库、根目录、FastAPI，使用仓库配置；入口是 `cloud_app:app`，不是原本地版 `app.py`。采用 Vercel WebSocket/Fluid Compute，函数上限 300 秒，应用单段限制 240 秒，预留握手和句尾收尾时间。`hkg1` 是配置目标，未在账户中验证实际部署。

需要在 Vercel **Production** 环境设置：

| 变量 | 用途 |
|---|---|
| `DASHSCOPE_API_KEY` | 百炼密钥，只作为敏感环境变量 |
| `DASHSCOPE_WORKSPACE_ID` | 新业务空间导出中的 workspaceId，不是 API Key 数字 id |
| `APP_ACCESS_CODE` | 自行生成至少 24 位随机访问码，网页只填写它 |
| `SESSION_SECRET` | 建议另生成 32 位以上随机签名密钥 |
| `ALLOWED_ORIGINS` | 加自定义域名时填写精确 HTTPS 来源，多个用逗号分隔 |

默认 Vercel 部署/生产地址从平台环境读取。换 Cloudflare 域名后，必须更新 `ALLOWED_ORIGINS` 并重新部署，否则登录和 WebSocket 会被拒绝。请确认平台的系统环境变量可用；必要时显式添加真实生产地址。

### 带私有 CSV 的自动配置/部署脚本

在你自己的电脑安装 Python 3.12+、Node.js，并克隆本仓库；运行：

```bash
npm install -g vercel
python scripts/deploy_vercel.py --csv "你的百炼导出.csv"
```

脚本会要求官方 Vercel 登录，关联 `putian-oldtownvoice` 项目，使用标准输入写入敏感环境变量并部署，不购买域名或服务器。默认团队为 `cxy-peters-projects`，可用 `--scope` 更改。返回的访问码保存在 `deployment-private/app-access-code.txt`，不要公开。

凭据导入兼容 `apiKey` / `workspaceId` 字段及非 `sk-` 前缀的业务空间密钥，只连接预定义北京官方主机。CSV、私有配置及密钥不会提交或作为源码上传。成功解析不代表密钥有效或账户有余额。

## Cloudflare 入口

仓库包含 `cloudflare/worker.mjs` 和 `wrangler.toml`，可选部署为 **Cloudflare → Vercel** 的 HTTPS/WebSocket 入口；不是把完整 Python 后端搬到 Workers。

也可使用自己的 Cloudflare 托管域名直接绑定 Vercel。两条路径、SSL/缓存及授权步骤见 [部署说明](docs/VERCEL_CLOUDFLARE.md)。**自有域名需账号权限；换域名、开代理或 workers.dev 均不保证中国大陆可达。**

## 两种存储模式

| 功能 | 本地 `python app.py` | 云端 `cloud_app:app` |
|---|---|---|
| 实时识别 | WebSocket，单段最多 300 秒 | WebSocket，单段最多 240 秒 |
| 手动词库/标注音频 | 私有 SQLite / 本地数据目录 | 当前浏览器 IndexedDB |
| 设备间共享 | 同一私有服务内共享 | 不自动同步 |
| 备份 | JSON / 含音频 ZIP | JSON / 含音频 ZIP |

云端没有把 SQLite 写入临时函数目录。换设备、换域名、清理浏览器前务必导出。词库可 JSON 导入；完整音频 ZIP 是备份/训练准备数据，尚无整包回导界面。浏览器数据不加密，使用私人设备。

已保存热词从下一次识别生效；原始转写、人工校正和翻译分开保存。语料须为 0.3–60 秒，母语者核对并取得授权；同一说话人不跨 train/dev/test。语料积累不是微调。

云端实例内限流和音频预算**不是全局计费硬上限**，冷启动/扩容会改变计数。仅向可信测试者分享访问码，并在百炼及 Vercel 控制台设置可用的用量保护。更改访问码可使旧签名会话失效；退出仅清理当前浏览器 Cookie。

## 原本地版本

```bash
python -m pip install -r requirements.txt
python scripts/setup.py "你的百炼导出.csv"
python app.py
```

打开 `http://localhost:8787`。已有 `.env` 时保留旧配置；不要在公网直接暴露无访问控制服务。容器部署另见 [国内服务器方案](docs/DEPLOY_CN.md)。

## 验证

```bash
python -m pip install -r requirements.txt httpx==0.28.1
python -m unittest discover -s tests -p "test_*.py"
node --test tests/worklet.test.cjs tests/local_store.test.cjs tests/cloudflare.test.mjs
```

本次仓库测试集：75 项 Python、17 个 Node 测试条目通过。另有 16 项离线 DOM 检查。流式上游为模拟接口，浏览器存储使用事务夹具，**不是线上或莆仙话准确率验收**。详细结果与部署阻碍见 [验证记录](docs/CLOUD_VALIDATION.md)。
