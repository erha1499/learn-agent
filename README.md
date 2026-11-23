# learn-agent

从“只会调大模型”学到能讲清、能做出、能评测一个 Agent：Agent 基础、Agent 工程、Agent 评测，以及面试专题。目标是下一个 Agent 项目能做出**有评测、能上线、能持续观察**的系统，面试时能把原理、实测数字和项目串起来讲。

姊妹篇：[learn-juc](https://github.com/erha1499/learn-juc)（Java 并发）、[learn-jvm](https://github.com/erha1499/learn-jvm)（JVM）。写法一样：先看现象（能跑的代码和真实结果），再讲原理，最后是面试和自测。

## 怎么读

| 入口 | 内容 |
| --- | --- |
| [完整文字版](content/)（`content/`） | 导读和各单元，每个单元一个文件 |
| 网页版（`docs/index.html`） | `python scripts/build.py` 生成，正文 + 可展开的「深入一层」+ 带答案的自测题 |

| 目标 | 读 |
| --- | --- |
| 只会调大模型，想弄懂 Agent 和 harness | 第一部分（单元一到五） |
| 准备面试 | 第一部分 → 单元十三 → 第五部分 |
| 要做一个能上线的 Agent | 从头按顺序 |

## 学习路线

全书五部分、二十七个单元，单元表见 [content/README.md](content/README.md)：

| 部分 | 讲什么 |
| --- | --- |
| 一 Agent 基础 | 从一次模型调用长出一个 Agent：工具调用、循环、harness，最后拆开一个 Coding Agent |
| 二 Agent 工程 | 提示词和结构化输出、工具和协议（MCP、Skills）、多 Agent、上下文和记忆、RAG、安全、生产化 |
| 三 Agent 评测 | 为什么难评、评测集、打分器、大模型评委、结论能不能信、基准和红队、线上评测 |
| 四 做一个能上线的 Agent | 立项、搭骨架、上线、上线以后 |
| 五 面试专题 | 模型侧的能力来源、系统设计题、论文和产品地图、高频题速查 |

已经写完：

| 单元 | 主题 | 一句话 |
| --- | --- | --- |
| 一 | 大模型 | 每次调用都花钱花时间，同样的输入不保证同样的输出，写出来的不保证是真的 |
| 二 | 工具调用 | 模型只会输出“想调哪个函数、参数是什么”；执行、校验、把结果送回去，全是你的代码 |
| 三 | Agent 循环 | 模型要工具就执行、结果追加回去、再问一次，直到它不再要工具；什么时候停、停下来交了什么，要你兜底 |
| 四 | Harness | 模型管判断，harness 管其余一切；机制挂在循环的固定位置上，管边界和验收，不替模型做决定 |
| 十三 | Agent 为什么难评 | 一次成功只是一次抽样：评的是能不能稳定做对、做对的方式靠不靠得住 |

## 仓库结构

```
content/            正文：README.md 是导读，NN-*.md 是各单元，answers.json 是自测答案（键是题目原文）
examples/           例子，文件名前缀是单元号：
                      _llm.py          最小模型客户端（只用标准库）
                      mini_world.py    迷你值班现场：4 个故障场景、3 个查询工具（单元二到四共用）
                      mini_agent.py    最小 Agent 循环（单元三），带四个挂钩子的位置（单元四）
                      mini_harness.py  挂在循环上的三个机制：参数守卫、结果压缩、证据账本和提交门（单元四）
                      uNN_*.py         调模型的例子把真实输出录在 output/，--replay 只看录好的；u13_* 读项目数据
data/               从 oncall-agent-mvp 评测平台导出的真实运行数据（单元一、十三里的项目数字都从这里来）
scripts/build.py    把 content/ 生成网页 docs/index.html（只用标准库）
```

## 跑例子

```bash
python examples/u03_workflow_vs_agent.py --replay
```

```bash
python examples/u13_repeats.py
```

第一条看录好的真实结果，不需要 key；第二条读项目数据，不调模型。

要自己调模型：在仓库根目录建 `.env`，写 `OPENAI_API_KEY=...`（默认走阿里云百炼的 OpenAI 兼容接口和 qwen-plus，可用 `OPENAI_BASE_URL`、`LLM_MODEL` 换）。单元一的例子全部跑一遍约 150 次很短的调用，单元二、三约 300 次，加起来花费不到一块钱。
