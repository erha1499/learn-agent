# CMDB：订单库 order-mysql-01
order-mysql-01 是订单主库，MySQL 8.0，承担全部下单写入。从库 order-mysql-02 供查询使用。负责人：周岚（交易数据库组）。使用它的服务：order-service、cart-service。max_connections 当前配置 1000。
