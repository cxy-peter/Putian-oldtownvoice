# 语料工作台：接入现有本地项目

## 已经实际导入什么

首次启动自动载入 `corpus_lab/seed.jsonl` 中 5 条公开字词编码摘例：飯、食飯、莆田、莆田話、莆仙話。源文件为 Yaryou/HinghuaFactory 的 `Pouleng.dict.yaml`，blob `c6fdf391c8ff653a71d05991d9dc9d71de4aa691`。原始来源和状态在页面可见。

**内置真人音频为 0。没有取得或导入 e-dialect 全库、《莆仙方言大词典》全文、贴吧录音；没有微调模型，没有实测莆仙话识别准确率。**搜索“吃饭”找到“食飯 / sia2 mue5”是字词参考查询（应用增加了搜索别名），不是音频识别结果。五条参考没有伪造人工审核标签。

## 安装到你已经下载的项目

先关闭正在运行的本地服务 / Cloudflare 启动器。把 `corpus_lab/` 文件夹、`install_corpus.py`、`安装语料工作台.bat` 复制到现有 `app.py` 同一级。

```bash
python install_corpus.py
python -m pip install -r corpus_lab/requirements.txt
python app.py
```

打开 `http://localhost:8787/corpus`。沿用原 `.env` 的 `APP_ACCESS_CODE`，不用重新运行 `setup.py`，不用换 API Key。没有安装 numpy 也能查词、导入、保存录音、调用云直译；只有本机声音检索需要 numpy。

Windows 也可以双击 `安装语料工作台.bat`；脚本优先使用已有 `.venv`，只安装挂载代码，不自动安装依赖或启动服务。

安装器只给现有 `app.py` 增加模块挂载并在首页加入口，修改前保留 `.before-corpus.bak`；重复安装安全。不会覆盖 `.env`、用户 CSV、旧语料或原密钥。旧版若有 `audio_first/server.py`，会尝试另外挂载 `/corpus`，不适配时保留不改。主要入口仍是本地 aiohttp `app.py`，本轮没有改 Vercel 的 `cloud_app.py`。

## 原来的 Cloudflare 方式

先 Ctrl+C 关闭单独的 `python app.py`，再用原来的脚本：

```bash
python scripts/share_local.py
```

在新生成的公网网址后加 `/corpus`。本补丁沿用项目现有 Origin / Cookie / 访问码，不关闭认证。没有在此次环境中启动真实公网隧道；国内链路需用实际手机测试。不要把 access code 放到公开前端。

## 看到什么、怎么用

1. 查词与来源：搜索“吃饭”“莆田话”或 `sia2 mue5`，查看源文件标音、口音范围、尚无录音和审核状态。无法匹配的输入不会强行套一个意思。
2. 听音与补录：选择词条补录，或直接保存自然短句。录音最多 20 秒自动停止；上传允许 0.3–30 秒。回听后填写完整普通话含义、匿名说话人/审核人/地区，并分别确认本地保存、检索或训练用途。
3. 本机声音检索：只比较已允许参考的本地录音；相同 PCM 文件、dev/test、未允许参考的样本不参与。MFCC+DTW 只是待验证短句基线，返回候选和距离（不是概率）。不同说话人和声调的可靠性尚未验证。
4. 原音直译：按用户明确同意，将原音发送到已有北京地域百炼接口。直接模式不读取人工答案、所选字典词条或错误 ASR 稿。“原音＋所选参考释义”是另一个实验按钮，另行征得向云端发送参考释义的同意，不能称作微调。
5. 导入语料：直接选 e-dialect 的词条和发音 JSON，或通用 JSON/JSONL；按 `word_id` 关联，跳过重复、不覆盖旧记录、不带入贡献者个人资料。不能用顶层 `Word.source` 的同音回退当作严格音义配对。导入音频 URL 只增加元数据，不下载录音，也不增加本机录音计数。
6. 私有备份：导出本地 JSON 和用户录音 ZIP，不要上传公开 GitHub。默认新存储为 `data/corpus_lab/`（遵从原项目 DATA_DIR）；不覆盖、也不自动迁移旧工作流的语料。

## 边界和用量保护

原 `.env` 密钥始终在后端。现有共享访问码意味着持码者可以访问本实例语料，不是多用户隔离系统。工作台最多 5000 条元数据、200 段本地录音；单次声音比较最多 80 条参考；每 UTC 日工作台云请求计数上限 60，失败请求也计数。原翻译器有独立用量逻辑，因此此数不是整个百炼账户的硬计费上限。

外部资料的查询、缓存、训练、商业使用和再分发需分别核对许可。录音的真人身份和语义由用户确认，系统不能独立保证其正确性。导入和人工标签都不会自动改变模型权重。

## 验证

2026-09-27：49 项新增 Python 测试通过；42 项原有本地服务测试通过。22 项界面检查通过，使用离线 Chromium DOM 和 Python 到本机真实 API 的桥接，因为环境策略禁止浏览器直接访问 localhost。不是手机真机或真实公网验收。

```bash
python install_corpus.py
python -m pip install -r requirements.txt -r corpus_lab/requirements.txt
python -m unittest corpus_lab.test_lab -q
python -m unittest discover -s tests -p "test_app.py" -q
```

测试使用合成音和模拟/本机接口，仅检验软件行为。合成音没有随补丁发放、不会混入初始语料。没有真实百炼调用、实际 Puxian 音义验证或模型训练结果。
