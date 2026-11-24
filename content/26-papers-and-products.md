# 单元二十六 论文和产品地图：从 ReAct 到 Claude Code

本单元的核心：面试不考你读过多少篇论文，考你能不能把一篇放进一条主线：它解决了循环、工具、上下文、协作、评测、训练里的哪个问题，今天的系统里还留着它的什么。产品也一样：每一次产品形态的转折，背后都是一次模型能力的变化。

**学完这个单元，你能：**

- 把二十多篇代表性论文放进六条主线，每篇说出一句“它留下了什么”。
- 按时间讲出 Agent 产品和框架的几次转折，以及每次转折背后的模型能力变化；知道怎么跟进厂商的工程文章。
- 被问到“最近读了什么论文、用过什么产品”时，按“解决什么、怎么做、局限、我在哪用到”回答。

前面的单元多次提到 ReAct、τ-bench、SWE-bench、《Building effective agents》这些名字，每次只讲用到的那一点。本单元把它们放到一张地图上。这一块变化最快，文中的日期和数字以原文为准；论文只写它的核心贡献，细节请读原文。先看一条时间线，然后按六条主线看论文，再看产品和框架的几次转折和怎么跟进厂商的工程文章，最后讲面试里怎么用。

## 26.1 一条时间线

| 年份 | 方法和论文 | 协议、文章 | 产品和框架 |
|---|---|---|---|
| 2021 | HumanEval（pass@k） | | Codex 模型 |
| 2022 | 思维链（CoT）、InstructGPT（RLHF）、ReAct | | LangChain、ChatGPT |
| 2023 | Toolformer、Reflexion、Generative Agents、Voyager、Tree of Thoughts、Gorilla、ToolLLM、CAMEL、AutoGen、MetaGPT、MemGPT、Lost in the Middle、WebArena、SWE-bench、GAIA | | ChatGPT 插件、AutoGPT、OpenAI Function Calling 接口 |
| 2024 | SWE-agent、OSWorld、τ-bench、SWE-bench Verified | MCP（11 月）、《Building effective agents》（12 月） | Devin、LangGraph、Claude computer use |
| 2025 | DeepSeek-R1、BrowseComp、Terminal-Bench | A2A（4 月）、多 Agent 调研系统与《Don't Build Multi-Agents》（6 月）、Agent Skills（10 月发布，12 月作为开放标准发布） | Operator、Deep Research、Claude Code、Manus、OpenAI Agents SDK、Codex CLI、Google ADK、Gemini CLI、Claude Agent SDK、pi |
| 2026 | | Anthropic 的一批工程文章：评测（1 月）、长任务 harness（3 月）、Managed Agents（4 月）、隔离（5 月）、Agent 记忆（11 月），见 26.9 | Claude Code 自动模式、Claude Managed Agents（带记忆）、Claude Cowork |

读这张表抓住两点：

- **2023 年是方法爆发的一年，2025 年是产品爆发的一年。** 2023 年大部分想法（反思、记忆、多 Agent、技能库）都已经提出来了，但模型撑不起长循环；2025 年模型的推理、长上下文和工具调用都被专门训练过，这些想法才真正变成好用的产品。
- **协议和工程文章集中在 2024 年底以后。** 说明行业的重心从“能不能做”转到了“怎么做得可靠、怎么接起来”。

## 26.2 主线一：让模型边想边做

| 论文 | 解决什么 | 留下了什么 |
|---|---|---|
| 思维链 CoT（Wei 等，2022） | 多步推理题直接答容易错 | 先写推理过程再给答案；今天推理模型把它训练成了默认行为（单元二十四） |
| ReAct（Yao 等，2022） | 只推理会编事实，只行动没有计划 | 推理和行动交替，用工具返回的观察纠正推理；今天原生工具调用的思路来源（单元三） |
| Reflexion（Shinn 等，2023） | 失败了再试，还是犯同样的错 | 失败后让模型用文字写下反思，存进记忆，带着反思再试 |
| Tree of Thoughts（Yao 等，2023） | 一条推理路径走错就回不来 | 把推理展开成树，评估每个分支再搜索；思路被后来的“多采样 + 评判”继承 |

## 26.3 主线二：让模型会用工具

| 论文或标准 | 解决什么 | 留下了什么 |
|---|---|---|
| Toolformer（Schick 等，2023） | 模型不知道什么时候该调工具 | 让模型自己标注“在哪插入一次调用能让后文更好预测”，学会何时、怎么调用 |
| Gorilla（Patil 等，2023） | 模型调 API 时编造不存在的接口和参数 | 检索 API 文档再生成调用，减少接口幻觉；同一团队后来维护了函数调用排行榜 BFCL |
| ToolLLM（Qin 等，2023） | 真实 API 太多、组合太复杂 | 一万多个真实 API 的训练和评测集，用搜索树找调用路径 |
| SWE-agent（Yang 等，2024） | 让模型直接用 shell 改代码，效果差 | 提出“Agent-计算机接口”：为模型专门设计的查看、搜索、编辑命令，比如编辑后自动做语法检查、搜索结果限制条数。**工具界面本身就是要设计的对象**（单元二、单元五） |
| MCP（Anthropic，2024） | 每个 Agent 都要为每个系统手写工具 | 工具的发现和调用标准化，一次实现、多处复用（单元五） |

## 26.4 主线三：记忆和上下文

| 论文或文章 | 解决什么 | 留下了什么 |
|---|---|---|
| Generative Agents（Park 等，2023） | 让 25 个虚拟角色在小镇里像人一样长期生活 | 记忆流：所有经历都记下来，按“新近、重要、相关”打分取回；定期把记忆总结成更高层的反思 |
| MemGPT（Packer 等，2023） | 上下文窗口装不下长对话和大文档 | 借鉴操作系统的虚拟内存：上下文是“内存”，外部存储是“磁盘”，模型自己调用函数换入换出 |
| Voyager（Wang 等，2023） | 在《我的世界》里长期探索，学到的本事下次用不上 | 技能库：把成功的行为存成可执行的代码，按描述检索复用，是今天 Skills 的前身之一（单元五） |
| Lost in the Middle（Liu 等，2023） | 长上下文里的信息都能被用上吗 | 不能：相关信息在开头或结尾时效果最好，在中间时明显变差。上下文不是越长越好 |
| 《Effective context engineering for AI agents》（Anthropic，2025） | 长任务的上下文怎么管 | 把上下文当成有限资源，用压缩、结构化笔记、子 Agent 三种手段（单元五） |
| 《The components of agent memory》（Anthropic，2026） | 跨会话的记忆怎么组织、怎么维护 | 分层：每次注入的一小段、wiki、笔记、原始记录；离线“做梦”整理；告诉模型记忆的用途，而不是规定死规则（单元九） |

## 26.5 主线四：多 Agent

| 论文或文章 | 做法 | 今天怎么看 |
|---|---|---|
| CAMEL（Li 等，2023） | 两个 Agent 分别扮演用户和助手，互相对话完成任务 | 角色扮演式协作的早期代表 |
| AutoGen（Wu 等，2023） | 一个框架，让多个“能对话的 Agent”按规则轮流发言 | 2025 年 10 月，微软宣布把它和 Semantic Kernel 合并为 Microsoft Agent Framework |
| MetaGPT（Hong 等，2023） | 把软件公司的流程写成角色（产品经理、架构师、工程师），每个角色输出结构化文档 | “把标准流程编进分工”，其实更接近 Workflow |
| 多 Agent 调研系统（Anthropic，2025） | 主 Agent 拆任务，并行派出子 Agent 搜索，汇总成报告 | 适合能拆成独立方向的任务，token 约为普通对话的 15 倍（单元二十五） |
| 《Don't Build Multi-Agents》（Cognition，2025） | 反对把任务拆给互相看不到上下文的多个 Agent | 上下文共享是多 Agent 的根本难题；并行写同一份东西尤其危险 |
| A2A（Google，2025） | Agent 之间互相委托任务的协议 | 和 MCP 互补：MCP 是 Agent 调工具，A2A 是 Agent 调 Agent |

## 26.6 主线五：评测

| 基准 | 测什么 | 留下了什么 |
|---|---|---|
| HumanEval（Chen 等，2021） | 164 道手写的 Python 函数题，用单元测试判定 | pass@k 的无偏估计（单元十三） |
| WebArena（Zhou 等，2023） | 在自建的电商、论坛、代码托管网站上完成任务 | 用可交互的环境代替静态问答，按最终状态判定 |
| SWE-bench（Jimenez 等，2023） | 真实 GitHub 仓库里的真实 issue，用仓库自己的测试判定修没修好 | 编程 Agent 的标准基准；2024 年 OpenAI 人工筛出 500 道可靠的题，叫 SWE-bench Verified |
| GAIA（Mialon 等，2023） | 对人很简单、但要用搜索和工具的通用助手问题 | 发布时人和模型的差距巨大；答案短，可以自动判 |
| OSWorld（Xie 等，2024） | 在真实的操作系统里完成任务 | 电脑操作类 Agent 的基准 |
| τ-bench（Yao 等，2024） | 零售、航空客服：模拟用户多轮对话，Agent 按业务规则调工具 | pass^k：每次都对才算稳（单元十三） |
| BrowseComp（OpenAI，2025） | 很难搜到、但答案很短可验证的问题 | 测深度搜索和坚持能力 |
| Terminal-Bench（2025） | 在终端环境里完成真实任务 | 终端编程 Agent 的基准 |

读这条主线抓住两点：从“答题”到“在环境里做事”，判定方式从比对答案变成检查最终状态；从“平均做对多少”到“稳不稳”（pass^k）。基准都会被“刷”：题目可能出现在训练数据里，标准答案本身也可能有错，所以出现了人工筛选的子集。自己的场景还是要有自己的评测集（单元十三）。

## 26.7 主线六：训练

| 论文 | 做法 | 对 Agent 的意义 |
|---|---|---|
| InstructGPT（Ouyang 等，2022） | 监督微调 + 奖励模型 + 强化学习（RLHF） | 模型学会听指令；“对话模型”从这里开始 |
| DeepSeek-R1（DeepSeek，2025） | 用规则能判对错的任务（数学、代码）做大规模强化学习 | 长推理能力可以靠强化学习练出来；“可验证的奖励”成为训练 Agent 能力的主流思路（单元二十四） |

## 26.8 产品和框架：几次转折

| 阶段 | 代表 | 发生了什么 | 背后的模型能力 |
|---|---|---|---|
| 2023：自主循环热潮 | AutoGPT、BabyAGI、LangChain | 让模型自己定目标、拆任务、无限循环；演示惊艳，实际很快跑偏、停不下来 | 模型不擅长长程规划，没有原生工具调用，格式靠正则解析 |
| 2024：工程化 | Function Calling 接口、Devin、SWE-agent、LangGraph、《Building effective agents》 | 从“全自主”回到“可控”：图式编排、写死的 Workflow、为模型设计工具界面 | 原生工具调用稳定了，但长任务仍不可靠 |
| 2025：harness 的时代 | Claude Code、Codex CLI、Gemini CLI、pi、Deep Research、Manus；MCP、A2A、Skills；Claude Agent SDK、OpenAI Agents SDK、Google ADK | 一个简单循环 + 好工具 + 上下文管理，就能完成几十上百步的任务；各家把自己的 harness 做成 SDK 开放出来 | 推理模型、长上下文、在 Agent 环境里专门训练过的工具调用 |
| 2026：harness 变成平台 | Claude Managed Agents、Claude Code 自动模式、Claude Cowork | 会话、harness、沙箱拆成稳定接口，托管运行；权限从逐个审批走向沙箱加分类器；记忆成了平台能力 | 模型能连续工作数小时，harness 里的假设过时得更快 |

读这张表抓住两点：

- **harness 越来越薄，是因为模型越来越强。** 2023 年需要大量编排代码弥补模型的不足；2025 年的编程 Agent 回到了一个循环加几个工具（单元三、五），learn-claude-code 和 pi 的立场都来自这个变化。
- **但薄不等于没有。** 2025 年以后的产品都把工程花在了边界和上下文上：权限、沙箱、压缩、技能、hooks。单元四讲的正是这一部分。
- **也不是一直变薄。** Anthropic 2026 年 3 月的说法是：模型变强以后，有些部件成了多余，但模型又能做以前做不了的事，值得尝试的 harness 组合不是变少了，而是换了位置。

## 26.9 跟上前沿：读厂商的工程文章

Agent 的很多问题还没有定论：记忆怎么组织、什么时候拆多 Agent、上下文满了是压缩还是重开、权限交给人还是交给分类器，各家每隔几个月就有新做法。比论文更新得快的是厂商的工程博客。Anthropic 这两年的文章，基本能串起本书的每个部分：

| 时间 | 文章 | 核心观点 | 本书在哪用到 |
|---|---|---|---|
| 2024-12 | Building effective agents | 先用最简单的形态；分清 Workflow 和 Agent | 单元三 |
| 2025-06 | How we built our multi-agent research system | 并行调研的 token 约是对话的 15 倍，适合可拆的高价值任务 | 单元八 |
| 2025-09 | Effective context engineering for AI agents；Writing effective tools for agents | 找最小的一组高信号 token；工具为 Agent 设计，用评测和 Agent 自己改进工具 | 单元五、六、七、九 |
| 2025-10 | Equipping agents with Agent Skills；Beyond permission prompts | 技能分三层加载；先划沙箱边界，减少审批 | 单元五、十一 |
| 2025-11 | Code execution with MCP；Advanced tool use；Effective harnesses for long-running agents | 工具搜索、用代码调工具；跨会话的功能清单和进度文件 | 单元五、六、七 |
| 2026-01 | Demystifying evals for AI agents；Designing AI-resistant technical evaluations | 任务、运行、打分器；从 20 到 50 条起步；评测会被模型做穿 | 单元十三、十四 |
| 2026-02 | Building a C compiler with parallel Claudes；Infrastructure noise in agentic coding evals | 无主管的并行，测试当裁判；资源配置能让成绩差 6 个点 | 单元八、十三 |
| 2026-03 | Harness design for long-running apps；Claude Code auto mode；Eval awareness on BrowseComp | 生成和评审分开，部件会过时；分类器代替逐个审批；联网评测会被找到答案 | 单元四、八、十一、十四 |
| 2026-04 | Scaling Managed Agents；Claude Code quality postmortem | 会话、harness、沙箱解耦；harness 的改动也会让效果变差 | 单元四、六、九、十二 |
| 2026-05 | How we contain Claude across products | 风险是可能性乘以波及范围；白名单就是授权 | 单元十一 |
| 2026-11 | The components of agent memory；Building strong safety evaluations | 记忆分层和做梦；安全评测的构念、评委校准和样本量 | 单元九、十一、十四 |

读这些文章时注意三点：

- **看日期和模型。** 同一个问题，结论会随模型变：2025 年 11 月的文章说只靠压缩撑不起长任务；2026 年 3 月的文章说 Sonnet 4.5 需要定期清空上下文，Opus 4.5 只靠自动压缩就够了。引用时带上日期和模型版本。
- **数字多是内部测的。** 很多结果来自厂商自己的评测集，样本不大、外人无法复现，比如自动模式“漏掉 17%”的那个测试集只有 52 条。它们说明方向，不是定论；放到自己的场景里，要用自己的评测再验证一遍。
- **后来的文章会修正前面的。** 2025 年 10 月的沙箱文章认为，注入即使成功也会被关在沙箱里；2026 年 5 月的文章披露了一次从白名单域名把数据外发出去的事故，把白名单重新看成一种授权。读新文章时，留意它推翻了什么。

## 26.10 面试里怎么用

被问到“最近读了什么论文”“用过哪些 Agent 产品”时：

1. **少而深。** 准备四五篇讲得透的，比报二十个名字有用。推荐：ReAct（循环的来源）、SWE-agent（工具界面设计）、τ-bench（稳定性评测）、《Building effective agents》（形态选择）、再加一篇和你项目最相关的。
2. **每篇按四句话讲：** 它解决什么问题；核心做法；局限是什么；我在哪里用到或者验证过。
3. **能接上自己的实测最好。** 比如：“τ-bench 提出 pass^k，因为客服场景用户只问一次。我在一个 20 条的排障评测集上算过，pass@3 是 95%，pass^3 只有 75%，说明五分之一的用例做不稳，所以我用 pass^k 当发布门禁。”

产品也一样：说你用过 Claude Code，最好能说出它的一个设计和你看到的效果，比如“它改文件用字符串替换，我测过比重写整个文件少了约三分之二的输出，也不会顺手改别的地方”。

## 自测

1. ReAct 解决了什么问题？今天的原生工具调用和它是什么关系？
2. SWE-agent 提出的“Agent-计算机接口”是什么意思？和本书里改文件用字符串替换有什么联系？
3. Generative Agents、MemGPT、Voyager 分别用什么办法处理“记忆”？哪一个是今天 Skills 的前身？
4. Lost in the Middle 发现了什么？对上下文工程意味着什么？
5. 从 HumanEval 到 τ-bench，Agent 评测发生了哪两个变化？
6. Agent 产品经历了哪几个阶段？为什么 2025 年的编程 Agent 反而回到了“一个简单循环”？
7. 面试时怎么讲一篇论文？用 τ-bench 举一个例子。
8. 读厂商的工程文章时要注意哪三点？举一个后来的文章修正前面文章的例子。
