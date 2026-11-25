"""单元二十一 · 值班 Agent 的最小骨架：配置、存储、网关、执行、队列、轨迹、导出。只用标准库。

    config.py    配置和指纹：会改变输出的进指纹，只影响快慢的不进
    store.py     SQLite：configs（每个指纹的完整配置）、deploys（线上指针）、jobs（任务状态和租约）、events（只追加的事件日志）
    gateway.py   模型网关：并发上限、重试（尊重 retry-after）、记用量；重试只在这一处
    runner.py    执行一个任务：从事件日志恢复，每一步先写事件再往下走
    worker.py    worker 池：领任务、续租约；同一个会话同一时间只跑一个任务
    trace.py     从事件日志生成轨迹（OpenTelemetry GenAI 的命名），默认不带正文
    export.py    把跑完的任务导出成评测题：录下工具返回，脱敏
    gate.py      发布门禁：指纹、记分卡、回归题、和线上版本配对比较（单元二十二）
    rollout.py   灰度分流（按会话哈希）和回滚时把排队中的任务改回稳定版本（单元二十二）
"""
