"""单元七：一个接了很多 MCP 服务器的 Agent 会看到的工具目录（40 个工具，名字带服务器前缀）。

只用来测“选工具”：工具不真的执行，返回一句占位结果。有几组故意相近的工具（指标、日志、建工单、发消息），
贴近真实情况：接的服务器一多，就会有好几个工具都“像是能干这件事”。
"""

def T(name, desc, **params):
    props = {k: {"type": "integer" if k in ("limit", "hours", "count") else "string", "description": v}
             for k, v in params.items()}
    return {"type": "function", "function": {"name": name, "description": desc,
                                             "parameters": {"type": "object", "properties": props, "required": list(params)[:1]}}}


CATALOG = [
    T("mysql__get_metrics", "查询一个 MySQL 实例当前的监控指标：连接数、最大连接数、CPU、QPS、慢查询数、行锁等待数", instance="实例名"),
    T("mysql__query_slow_log", "查询一个 MySQL 实例最近的慢查询日志明细", instance="实例名", limit="条数"),
    T("mysql__slow_query_digest", "按 SQL 模板汇总一个 MySQL 实例过去若干小时的慢查询统计", instance="实例名", hours="小时数"),
    T("mysql__query_error_log", "查询一个 MySQL 实例最近的错误日志", instance="实例名", limit="行数"),
    T("mysql__show_processlist", "查看一个 MySQL 实例当前正在执行的会话和 SQL", instance="实例名"),
    T("mysql__kill_query", "终止一个 MySQL 实例上正在执行的某个查询", instance="实例名", thread_id="线程号"),
    T("mysql__list_instances", "列出某个业务服务使用的 MySQL 实例", service="服务名"),
    T("mysql__get_variables", "查看一个 MySQL 实例的配置参数", instance="实例名", pattern="参数名模式"),
    T("mysql__table_stats", "查看一张表的行数、大小和索引", instance="实例名", table="表名"),
    T("redis__get_metrics", "查询一个 Redis 实例的内存、连接数、命中率、QPS", instance="实例名"),
    T("redis__big_keys", "扫描一个 Redis 实例里占用内存最大的 key", instance="实例名", count="返回个数"),
    T("redis__slowlog", "查看一个 Redis 实例的慢命令日志", instance="实例名"),
    T("redis__hot_keys", "统计一个 Redis 实例里访问最频繁的 key", instance="实例名"),
    T("k8s__get_pods", "查看某个服务在 Kubernetes 里的 pod 列表和状态", service="服务名"),
    T("k8s__get_logs", "查看某个 pod 的容器日志", pod="pod 名"),
    T("k8s__describe_pod", "查看某个 pod 的详细信息和事件", pod="pod 名"),
    T("k8s__rollout_restart", "滚动重启某个服务的所有 pod", service="服务名"),
    T("k8s__get_events", "查看某个命名空间最近的事件", namespace="命名空间"),
    T("prometheus__query", "执行一条 PromQL 查询，返回时序数据", promql="PromQL 语句"),
    T("prometheus__list_alerts", "列出当前正在触发的告警", severity="级别"),
    T("grafana__get_panel", "读取 Grafana 看板里某个面板的数据", dashboard="看板名", panel="面板名"),
    T("grafana__search_dashboards", "按关键词搜索 Grafana 看板", keyword="关键词"),
    T("es__search_logs", "在 Elasticsearch 里按关键词搜索应用日志", index="索引名", query="查询语句"),
    T("cmdb__search_assets", "在 CMDB 里按关键词搜索资产（服务、机器、数据库实例）及其归属关系", keyword="关键词"),
    T("cmdb__get_owner", "查询某个资产的负责人", asset="资产名"),
    T("change__list_recent", "列出某个服务最近的变更记录（发布、配置修改）", service="服务名", hours="小时数"),
    T("oncall__who_is_on_call", "查询某个团队当前的值班人", team="团队名"),
    T("oncall__page", "呼叫某个团队的值班人", team="团队名", message="内容"),
    T("jira__create_issue", "在 Jira 的某个项目里创建一个工单", project="项目", summary="标题"),
    T("jira__search_issues", "按 JQL 搜索 Jira 工单", jql="JQL 语句"),
    T("jira__add_comment", "给一个 Jira 工单添加评论", issue="工单号", body="内容"),
    T("github__create_issue", "在 GitHub 仓库里创建一个 issue", repo="仓库", title="标题"),
    T("github__search_code", "在 GitHub 仓库里搜索代码", repo="仓库", query="关键词"),
    T("github__list_prs", "列出 GitHub 仓库最近的 pull request", repo="仓库"),
    T("feishu__send_message", "在飞书群里发一条消息", chat="群名", text="内容"),
    T("feishu__create_task", "在飞书里创建一个任务并指派给某人", title="标题", assignee="负责人"),
    T("slack__send_message", "在 Slack 频道里发一条消息", channel="频道", text="内容"),
    T("fs__read_file", "读取本地文件", path="路径"),
    T("fs__search_files", "按文件名搜索本地文件", pattern="模式"),
    T("web__search", "在互联网上搜索", query="关键词"),
]

QUESTIONS = [
    ("order-mysql-01 现在的连接数和 CPU 多少？", {"mysql__get_metrics"}),
    ("pay-mysql-03 最近 5 条慢查询给我看看", {"mysql__query_slow_log"}),
    ("user-mysql-04 的错误日志里最近有什么报错？", {"mysql__query_error_log"}),
    ("cache-redis-02 有没有特别大的 key？", {"redis__big_keys"}),
    ("order-service 在 k8s 里的 pod 状态怎么样？", {"k8s__get_pods"}),
    ("帮我在 Jira 的 DBA 项目里建一个工单：order-mysql-01 连接数打满", {"jira__create_issue"}),
    ("order 服务用的是哪几台数据库实例？", {"cmdb__search_assets", "mysql__list_instances"}),
    ("report-mysql-02 现在有哪些正在执行的 SQL？", {"mysql__show_processlist"}),
]
