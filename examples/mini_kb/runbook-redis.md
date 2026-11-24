# Redis 大 key 排查手册
用 big_keys 工具扫描。单个 key 超过 10MB 视为大 key，超过 1MB 的 hash 或 list 要关注。处理：拆分成多个 key，或改成分页读取；不要在高峰期直接 DEL 大 key，用 UNLINK 异步删除。
