"""`app.data_import.orchestrator` — import / reconcile 调度层。

对 6 类 domain 提供统一入口：

- `import_domain(domain, *, source_path=None, dry_run=False, session=None) -> ImportOutcome`
- `reconcile_domain(domain, *, session=None) -> ReconcileReport`

内部走 `app.db.session.get_session()`；不新增 FastAPI 依赖注入；不新增路由。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .importers import IMPORTERS


SUPPORTED_DOMAINS: tuple[str, ...] = tuple(IMPORTERS.keys())


@dataclass(frozen=True)
class ImportOutcome:
    domain: str
    dry_run: bool
    source_count: int
    candidate_count: int
    inserted: int
    skipped: int
    extras: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        base = asdict(self)
        extras = base.pop("extras")
        base.update(extras)
        return base


@dataclass(frozen=True)
class ReconcileReport:
    domain: str
    counts: dict[str, int]
    missing: list[str]
    field_diffs: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "counts": self.counts,
            "missing": self.missing,
            "field_diffs": self.field_diffs,
        }


def _require(domain: str):
    if domain not in IMPORTERS:
        raise ValueError(
            f"unknown domain {domain!r}; supported: {SUPPORTED_DOMAINS}"
        )
    return IMPORTERS[domain]


def import_domain(
    domain: str,
    *,
    source_path: str | None = None,
    dry_run: bool = False,
) -> ImportOutcome:
    """幂等导入指定 domain 数据。

    - `dry_run=True`：不 commit，事务回滚；仍完整走一遍 insert-or-ignore
      逻辑，输出可预期的 `inserted / skipped` 数字。
    - `dry_run=False`：走 `get_session()` context，自动 commit。
    """
    importer = _require(domain)

    from app.db.session import get_session

    if dry_run:
        # 独立 connect + 显式 begin，最终 rollback 不落库。
        from app.db.engine import get_engine

        engine = get_engine()
        with engine.connect() as conn:
            trans = conn.begin()
            try:
                result = importer.import_records(conn, source_path=source_path)
            finally:
                trans.rollback()
    else:
        with get_session() as session:
            conn = session.connection()
            result = importer.import_records(conn, source_path=source_path)

    known_fields = {
        "domain",
        "source_count",
        "candidate_count",
        "inserted",
        "skipped",
    }
    extras = {k: v for k, v in result.items() if k not in known_fields}
    return ImportOutcome(
        domain=result["domain"],
        dry_run=dry_run,
        source_count=int(result.get("source_count", 0)),
        candidate_count=int(result.get("candidate_count", 0)),
        inserted=int(result.get("inserted", 0)),
        skipped=int(result.get("skipped", 0)),
        extras=extras,
    )


def reconcile_domain(domain: str) -> ReconcileReport:
    """输出 JSON vs DB 对账报告；稳定结构。

    输出 shape：`{"domain": "<name>", "counts": {"json": N, "db": M}, "missing": [...], "field_diffs": []}`

    `field_diffs` 本 PR 只承载 count-level 对账；字段级差异保留为未来 PR
    的扩展（例如 PR-4 shadow 双读引入 legacy vs snapshot 快照对比）。
    """
    importer = _require(domain)

    from app.db.session import get_session

    with get_session() as session:
        conn = session.connection()
        json_count, db_count, missing = importer.reconcile_counts(conn)

    return ReconcileReport(
        domain=domain,
        counts={"json": int(json_count), "db": int(db_count)},
        missing=list(missing),
        field_diffs=[],
    )


__all__ = [
    "SUPPORTED_DOMAINS",
    "ImportOutcome",
    "ReconcileReport",
    "import_domain",
    "reconcile_domain",
]
