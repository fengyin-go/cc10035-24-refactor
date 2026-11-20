"""分布计数解释数据集：实体与情感分类计数共用的贡献累加骨架。

实体统计和情感摘要原本各自手写「按类别计数」的循环；这里把聚合分类记录的
公共部分收拢成同一份「分布计数解释数据集」：每条记录的有效类别贡献只累加
一次，类别计数与贡献明细（定位依据）同步写入、始终一致。各旧接口再按原
口径从数据集投影，聚合视图则直接消费数据集，并把定位依据回写进当次聚合
的明细清单。

口径约定（与历史实现完全一致，可通过原始记录复算）：
- 类别字段缺失时归入 MISSING_CATEGORY（默认 "未知"）；
- 类别字段为空字符串时保持 "" 类别键（空类别口径）；
- 参与聚合的记录不重复计数：total == len(contributions) == sum(counts.values())；
- 每个类别的计数与成员清单互相复算：counts[c] == len(members[c])。
"""
from __future__ import annotations

from typing import Any, Iterable

MISSING_CATEGORY = "未知"


def new_distribution_dataset(field: str) -> dict[str, Any]:
    """创建一份空的分布计数解释数据集。"""
    return {
        "field": field,
        "total": 0,
        "counts": {},
        "members": {},
        "contributions": [],
    }


def accumulate_contribution(
    dataset: dict[str, Any], record_id: Any, category: Any
) -> None:
    """把一条记录的类别贡献汇入数据集，计数与定位明细同步累加。"""
    counts = dataset["counts"]
    counts[category] = counts.get(category, 0) + 1
    dataset["members"].setdefault(category, []).append(record_id)
    dataset["contributions"].append({"id": record_id, "category": category})
    dataset["total"] += 1


def build_distribution_dataset(
    rows: Iterable[dict[str, Any]],
    field: str,
    *,
    missing_label: str = MISSING_CATEGORY,
) -> dict[str, Any]:
    """按类别字段聚合记录，产出当轮的分布计数解释数据集。

    每条记录只贡献一次；类别取值沿用历史口径：字段缺失归入
    missing_label，字段为空字符串保持 "" 类别键。
    """
    dataset = new_distribution_dataset(field)
    for row in rows:
        accumulate_contribution(dataset, row.get("id"), row.get(field, missing_label))
    return dataset


def dataset_counts(dataset: dict[str, Any]) -> dict[str, int]:
    """把数据集投影回旧接口返回的类别计数字典。"""
    return dict(dataset["counts"])
