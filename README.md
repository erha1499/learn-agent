# learn-agent

从零学 Agent 工程和 Agent 评测，目标是下一个 Agent 项目能做出**有评测、能上线、能持续观察**的系统，而不只是一个本地 Demo。

姊妹篇：[learn-juc](https://github.com/erha1499/learn-juc)（Java 并发）、[learn-jvm](https://github.com/erha1499/learn-jvm)（JVM）。写法一样：先看现象（能跑的代码和真实结果），再讲原理，最后是面试和自测。

## 怎么读

| 入口 | 内容 |
| --- | --- |
| [完整文字版](content/)（`content/`） | 导读和各单元，每个单元一个文件 |
| 网页版（`docs/index.html`） | `python scripts/build.py` 生成，正文 + 可展开的「深入一层」+ 带答案的自测题 |

## 学习路线

全书三部分、二十一个单元，单元表见 [content/README.md](content/README.md)。现在是**试点**，写完了：

| 单元 | 主题 | 一句话 |
| --- | --- | --- |
| 一 | 大模型基础 | 每次调用都花钱花时间，同样的输入不保证同样的输出，写出来的不保证是真的 |
| 十 | Agent 为什么难评 | 一次成功只是一次抽样：评的是能不能稳定做对、做对的方式靠不靠得住 |

## 仓库结构

```
content/            正文：README.md 是导读，NN-*.md 是各单元，answers.json 是自测答案（键是题目原文）
examples/           例子：u01_* 调模型（真实输出录在 output/，--replay 只看录好的），u10_* 读项目数据
data/               从 oncall-agent-mvp 评测平台导出的真实运行数据（例子和正文里的数字都从这里来）
scripts/build.py    把 content/ 生成网页 docs/index.html（只用标准库）
```

## 跑例子

```bash
python examples/u01_sampling.py --replay     # 看录好的真实结果，不需要 key
python examples/u10_repeats.py               # 读项目数据，不调模型
```

要自己调模型：在仓库根目录建 `.env`，写 `OPENAI_API_KEY=...`（默认走阿里云百炼的 OpenAI 兼容接口和 qwen-plus，可用 `OPENAI_BASE_URL`、`LLM_MODEL` 换）。单元一的例子全部跑一遍约 150 次很短的调用，花费几分钱。
