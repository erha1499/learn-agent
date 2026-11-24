"""库存服务：扣减、预占、释放库存。单元五的改文件实验用它当被改的文件。"""
import logging
import time
from dataclasses import dataclass, field

log = logging.getLogger("inventory")

DEFAULT_WAREHOUSE = "sh-01"
MAX_BATCH = 200


class InventoryError(Exception):
    """库存操作失败。"""


class OutOfStock(InventoryError):
    def __init__(self, sku_id, want, have):
        super().__init__(f"sku {sku_id} 库存不足：需要 {want}，剩余 {have}")
        self.sku_id, self.want, self.have = sku_id, want, have


@dataclass
class StockItem:
    sku_id: int
    warehouse: str
    on_hand: int
    reserved: int = 0
    updated_at: float = field(default_factory=time.time)

    @property
    def available(self):
        return self.on_hand - self.reserved


class Inventory:
    def __init__(self, db, cache=None, warehouse=DEFAULT_WAREHOUSE):
        self.db = db
        self.cache = cache
        self.warehouse = warehouse

    # ---------- 查询 ----------

    def get(self, sku_id):
        if self.cache is not None:
            hit = self.cache.get(self._key(sku_id))
            if hit is not None:
                return hit
        row = self.db.query_one(
            "SELECT sku_id, warehouse, on_hand, reserved, updated_at FROM inventory "
            "WHERE sku_id = %s AND warehouse = %s", (sku_id, self.warehouse))
        if row is None:
            raise InventoryError(f"sku {sku_id} 不存在")
        item = StockItem(*row)
        if self.cache is not None:
            self.cache.set(self._key(sku_id), item, ttl=30)
        return item

    def get_many(self, sku_ids):
        if len(sku_ids) > MAX_BATCH:
            raise InventoryError(f"一次最多查 {MAX_BATCH} 个 sku")
        return {sku_id: self.get(sku_id) for sku_id in sku_ids}

    # ---------- 扣减 ----------

    def deduct(self, sku_id, qty, order_id):
        if qty <= 0:
            raise InventoryError("扣减数量必须大于 0")
        with self.db.transaction() as tx:
            item = self._lock_row(tx, sku_id)
            if item.available < qty:
                raise OutOfStock(sku_id, qty, item.available)
            tx.execute("UPDATE inventory SET on_hand = on_hand - %s, updated_at = %s "
                       "WHERE sku_id = %s AND warehouse = %s", (qty, time.time(), sku_id, self.warehouse))
            tx.execute("INSERT INTO inventory_log (sku_id, warehouse, delta, order_id, kind) "
                       "VALUES (%s, %s, %s, %s, 'deduct')", (sku_id, self.warehouse, -qty, order_id))
        self._invalidate(sku_id)
        log.info("deduct sku=%s qty=%s order=%s", sku_id, qty, order_id)

    # ---------- 预占和释放 ----------

    def reserve_stock(self, sku_id, qty, order_id):
        """下单时先预占库存，支付成功后再真正扣减；超时没支付就释放。"""
        if qty <= 0:
            raise InventoryError("预占数量必须大于 0")
        deadline = time.time() + 3
        while True:
            try:
                with self.db.transaction(lock_timeout=1) as tx:
                    item = self._lock_row(tx, sku_id)
                    if item.available < qty:
                        raise OutOfStock(sku_id, qty, item.available)
                    tx.execute("UPDATE inventory SET reserved = reserved + %s, updated_at = %s "
                               "WHERE sku_id = %s AND warehouse = %s", (qty, time.time(), sku_id, self.warehouse))
                    tx.execute("INSERT INTO inventory_log (sku_id, warehouse, delta, order_id, kind) "
                               "VALUES (%s, %s, %s, %s, 'reserve')", (sku_id, self.warehouse, qty, order_id))
                break
            except self.db.LockTimeout:
                if time.time() > deadline:
                    raise InventoryError(f"预占 sku {sku_id} 超时")
                time.sleep(0.05)
        self._invalidate(sku_id)
        log.info("reserve sku=%s qty=%s order=%s", sku_id, qty, order_id)

    def release(self, sku_id, qty, order_id):
        with self.db.transaction() as tx:
            item = self._lock_row(tx, sku_id)
            qty = min(qty, item.reserved)
            if qty == 0:
                return
            tx.execute("UPDATE inventory SET reserved = reserved - %s, updated_at = %s "
                       "WHERE sku_id = %s AND warehouse = %s", (qty, time.time(), sku_id, self.warehouse))
            tx.execute("INSERT INTO inventory_log (sku_id, warehouse, delta, order_id, kind) "
                       "VALUES (%s, %s, %s, %s, 'release')", (sku_id, self.warehouse, -qty, order_id))
        self._invalidate(sku_id)
        log.info("release sku=%s qty=%s order=%s", sku_id, qty, order_id)

    def confirm(self, sku_id, qty, order_id):
        """支付成功：把预占转成真正的扣减。"""
        with self.db.transaction() as tx:
            item = self._lock_row(tx, sku_id)
            if item.reserved < qty:
                raise InventoryError(f"sku {sku_id} 预占不足：预占 {item.reserved}，要确认 {qty}")
            tx.execute("UPDATE inventory SET reserved = reserved - %s, on_hand = on_hand - %s, updated_at = %s "
                       "WHERE sku_id = %s AND warehouse = %s", (qty, qty, time.time(), sku_id, self.warehouse))
            tx.execute("INSERT INTO inventory_log (sku_id, warehouse, delta, order_id, kind) "
                       "VALUES (%s, %s, %s, %s, 'confirm')", (sku_id, self.warehouse, -qty, order_id))
        self._invalidate(sku_id)
        log.info("confirm sku=%s qty=%s order=%s", sku_id, qty, order_id)

    # ---------- 盘点 ----------

    def adjust(self, sku_id, new_on_hand, operator, reason):
        if new_on_hand < 0:
            raise InventoryError("盘点后的库存不能小于 0")
        with self.db.transaction() as tx:
            item = self._lock_row(tx, sku_id)
            if new_on_hand < item.reserved:
                raise InventoryError(f"盘点数 {new_on_hand} 小于已预占 {item.reserved}")
            delta = new_on_hand - item.on_hand
            tx.execute("UPDATE inventory SET on_hand = %s, updated_at = %s WHERE sku_id = %s AND warehouse = %s",
                       (new_on_hand, time.time(), sku_id, self.warehouse))
            tx.execute("INSERT INTO inventory_audit (sku_id, warehouse, delta, operator, reason) "
                       "VALUES (%s, %s, %s, %s, %s)", (sku_id, self.warehouse, delta, operator, reason))
        self._invalidate(sku_id)
        log.warning("adjust sku=%s delta=%s by %s: %s", sku_id, delta, operator, reason)

    def low_stock(self, threshold=10, limit=100):
        rows = self.db.query_all(
            "SELECT sku_id, warehouse, on_hand, reserved, updated_at FROM inventory "
            "WHERE warehouse = %s AND on_hand - reserved < %s ORDER BY on_hand - reserved LIMIT %s",
            (self.warehouse, threshold, limit))
        return [StockItem(*r) for r in rows]

    # ---------- 内部 ----------

    def _lock_row(self, tx, sku_id):
        row = tx.query_one(
            "SELECT sku_id, warehouse, on_hand, reserved, updated_at FROM inventory "
            "WHERE sku_id = %s AND warehouse = %s FOR UPDATE", (sku_id, self.warehouse))
        if row is None:
            raise InventoryError(f"sku {sku_id} 不存在")
        return StockItem(*row)

    def _key(self, sku_id):
        return f"inv:{self.warehouse}:{sku_id}"

    def _invalidate(self, sku_id):
        if self.cache is not None:
            self.cache.delete(self._key(sku_id))
