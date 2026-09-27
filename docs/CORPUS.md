# 莆仙话改进：三种数据，不把词库当微调

## 1. 热词

“我的词库”中手动添加词语、权重与可选释义。默认只预置少量地名/文化专名，没有编造方言句子。

Qwen Audio 3.1 的即时词表按官方字段 `parameters.vocabulary` 发送；应用限制 500 词、超级热词 50 个。普通权重 1–5，50 仅给少量核心词。Qwen3 Realtime 不接收这些字段；Fun-ASR 对照使用领域上下文，本版未实现其预编译热词服务。

释义用于与原文匹配的翻译参考。调整词表可能改善专有名词，也可能过度匹配，须比较同一录音增强前后的**原始识别**，不能从译文流畅程度推断准确率。

## 2. 人工核对例句

由懂对应莆仙话地区的人填写“方言表达/转写文字 → 标准中文”。翻译时只选原文中匹配的已核对例句。不是正则全局强制替换，也不会回写原始 ASR 结果。语料存储授权不自动等于允许公开发布。

## 3. 带音频的真实标注

没有有效识别接口时，可在“实时翻译”页选择“仅录音采集”，录一段短句，再到“标注语料”填写：说话人匿名编号、地区、完整录音的人工转写、可选普通话释义、数据集划分。只在母语者核对及录音授权勾选后保存。

务必转写**整段音频**，不要把某个局部句子的文字配给整段音频。建议每段 5–20 秒，先覆盖日常问答、时间数字、否定句和人地名。人名电话等隐私需本人明确同意；尽量不用真实身份信息。

同一说话人不能同时出现在 train/dev/test，重复音频也不能换个名字进入测试集。界面会检查这两类冲突；它无法替代人工确保测试参考答案未进入热词/例句。

“导出私有语料”提供 `manifest.jsonl`、音频和词库，解压至私有目录，然后：

```bash
python scripts/prepare_training.py unpacked_private_export training-data
```

生成 train/dev/test 各自的 `*_wav.scp`、`*_text.txt`。脚本检查音频格式、SHA256、说话人隔离和授权，不会联网、训练或声称提高准确率。

在独立的训练环境中使用官方 Fun-ASR 工具，将上述文件转换为模型训练输入；帧数和 tokenizer token 数应由官方转换程序计算，不能用字数冒充：

```bash
# 在官方 QwenAudio/Fun-ASR 项目及其训练依赖安装完成后执行：
python tools/scp2jsonl.py \
  ++scp_file=/absolute/path/training-data/train_wav.scp \
  ++transcript_file=/absolute/path/training-data/train_text.txt \
  ++jsonl_file=/absolute/path/training-data/train_example.jsonl
```

验证集对应转换 dev；测试集只留给最终评测。随后按官方 `finetune.sh` 选择可训练模块、模型权重、硬件和参数。**本项目尚未下载训练权重、运行优化器、产生微调 checkpoint，也没有实现云端 API 权重微调。**

## 评测

在基线与增强模式分别识别同一批测试音频，导出**原始**识别文字，整理为：

```json
{"speaker":"test-speaker-01","split":"test","reference":"母语者统一书写规则的转写","hypothesis":"模型原始转写"}
```

运行 `python scripts/evaluate.py predictions.jsonl`。报告字符错误数、参考字符数、CER、说话人及片段数；没有测试样本就返回空指标，不显示虚构准确率。莆仙话书写方式可能不统一，先约定参考转写规则，同时人工评估语义、数字、否定和专名保留情况。漂亮的普通话译文不能修复从音频中丢失的信息。

官方微调参考：https://github.com/QwenAudio/Fun-ASR/blob/main/docs/finetune_zh.md
