"""分布计数重构验证脚本。

对照重构前的旧实现，验证两个旧分布接口（实体类型分布 / 情感分布摘要）
口径不变，以及当轮分布计数解释数据集、聚合视图明细清单的一致性。

覆盖场景：
1. 正常数据 —— 种子记录直接参与聚合；
2. 缺类别数据 —— 记录缺少类别字段，旧口径归入「未知」；
3. 空类别数据 —— 类别字段为空字符串，旧口径保持 "" 类别键；
4. 实体补录类别 —— 同一来源出现两版数据，聚合视图先读到旧计数，
   情感摘要批次保持不动，参与聚合的记录不重复计数。

用法：.venv/bin/python tests/verify_distribution_refactor.py
"""
from __future__ import annotations

import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.aggregate_view import AggregateViewService
from app.services.entity_extract import EntityExtractService
from app.services.sentiment_tag import SentimentTagService
from app.store import store


# ---- 重构前的旧实现，作为口径对照基准（通过原始记录复算旧口径） ----

def legacy_entity_distribution(rows: list[dict]) -> dict[str, int]:
    dist: dict[str, int] = {}
    for row in rows:
        etype = row.get("实体类型", "未知")
        dist[etype] = dist.get(etype, 0) + 1
    return dist


def legacy_sentiment_summary(rows: list[dict]) -> dict:
    dist: dict[str, int] = {}
    intensity_dist: dict[str, int] = {}
    for row in rows:
        sent = row.get("情感倾向", "未知")
        dist[sent] = dist.get(sent, 0) + 1
        intensity_dist[row.get("强烈程度", "未知")] = \
            intensity_dist.get(row.get("强烈程度", "未知"), 0) + 1
    return {
        "total_records": len(rows),
        "sentiment_distribution": dist,
        "intensity_distribution": intensity_dist,
    }


PASSES: list[str] = []
FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if ok:
        PASSES.append(name)
        print(f"  PASS {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL {name} {detail}")


def append_row(module: str, fields: dict) -> dict:
    """绕过必填校验直接送入一条记录（模拟缺类别 / 空类别数据）。"""
    rows = store.rows(module)
    entry = {"id": max((int(r.get("id", 0)) for r in rows), default=0) + 1}
    entry.update(fields)
    rows.append(entry)
    return entry


def check_old_interfaces(tag: str) -> None:
    """两个旧分布接口的口径与重构前实现一致（可由原始记录复算）。"""
    entity_rows = store.rows("entity_extract")
    sentiment_rows = store.rows("sentiment_tag")
    check(
        f"{tag}｜实体旧分布接口口径不变",
        EntityExtractService().compute_entity_distribution()
        == legacy_entity_distribution(entity_rows),
    )
    check(
        f"{tag}｜情感旧摘要接口口径不变",
        SentimentTagService().compute_sentiment_summary()
        == legacy_sentiment_summary(sentiment_rows),
    )
    check(
        f"{tag}｜实体快照沿用旧接口口径",
        EntityExtractService().domain_snapshot()["entity_distribution"]
        == legacy_entity_distribution(entity_rows),
    )
    check(
        f"{tag}｜情感快照沿用旧接口口径",
        SentimentTagService().domain_snapshot()["sentiment_summary"]
        == legacy_sentiment_summary(sentiment_rows),
    )


def check_dataset(tag: str, dataset: dict, rows: list[dict]) -> None:
    """分布计数解释数据集：计数、成员、贡献三者一致，记录不重复计数。"""
    counts, members, contribs = dataset["counts"], dataset["members"], dataset["contributions"]
    check(
        f"{tag}｜总数与贡献记录数对应（不重复计数）",
        dataset["total"] == len(rows) == len(contribs) == sum(counts.values()),
        f"total={dataset['total']} rows={len(rows)} contribs={len(contribs)}",
    )
    check(
        f"{tag}｜各类别计数与成员数互相复算",
        all(counts[c] == len(members.get(c, [])) for c in counts),
    )
    check(
        f"{tag}｜成员清单与贡献记录保存一致",
        sorted(cid for c in counts for cid in members[c])
        == sorted(c["id"] for c in contribs),
    )
    check(
        f"{tag}｜每条原始记录只贡献一次",
        sorted(c["id"] for c in contribs) == sorted(r["id"] for r in rows),
    )


def check_datasets(tag: str) -> None:
    check_dataset(
        f"{tag}｜实体数据集",
        EntityExtractService().entity_distribution_dataset(),
        store.rows("entity_extract"),
    )
    summary_ds = SentimentTagService().sentiment_summary_dataset()
    check(
        f"{tag}｜情感数据集总数与记录数对应",
        summary_ds["total_records"] == len(store.rows("sentiment_tag"))
        == summary_ds["sentiment"]["total"] == summary_ds["intensity"]["total"],
    )
    check_dataset(f"{tag}｜情感倾向数据集", summary_ds["sentiment"], store.rows("sentiment_tag"))
    check_dataset(f"{tag}｜强烈程度数据集", summary_ds["intensity"], store.rows("sentiment_tag"))


def check_panels(tag: str) -> None:
    """聚合视图消费两种计数结果：总数与成员数对应，类别明细可互相复算。"""
    avs = AggregateViewService()
    entity_panel = avs.aggregate_entity_distribution()
    sentiment_panel = avs.aggregate_sentiment_trend()
    dist = EntityExtractService().compute_entity_distribution()
    summary = SentimentTagService().compute_sentiment_summary()

    check(
        f"{tag}｜聚合视图实体维度与计数对应旧接口",
        entity_panel["dimensions"] == list(dist.keys())
        and entity_panel["values"] == list(dist.values()),
    )
    check(
        f"{tag}｜聚合视图实体总数与成员数对应",
        entity_panel["total_entities"]
        == sum(d["count"] for d in entity_panel["details"])
        == sum(len(d["members"]) for d in entity_panel["details"]),
    )
    check(
        f"{tag}｜聚合视图情感分布与总数对应旧接口",
        sentiment_panel["sentiment_distribution"] == summary["sentiment_distribution"]
        and sentiment_panel["total_records"] == summary["total_records"],
    )
    check(
        f"{tag}｜聚合视图情感总数与成员数对应",
        sentiment_panel["total_records"]
        == sum(d["count"] for d in sentiment_panel["details"])
        == sum(len(d["members"]) for d in sentiment_panel["details"]),
    )
    for source, panel in (("entity_extract", entity_panel), ("sentiment_tag", sentiment_panel)):
        for detail in panel["details"]:
            got = avs.category_detail(source, detail["category"])
            check(
                f"{tag}｜{source} 类别「{detail['category']}」明细复算",
                got is not None
                and got["count"] == len(got["members"]) == detail["count"],
            )


def scenario_normal() -> None:
    print("场景一：正常数据")
    check_old_interfaces("正常")
    check_datasets("正常")
    check_panels("正常")


def scenario_missing_category() -> None:
    print("场景二：缺类别数据（字段缺失归入「未知」）")
    append_row("entity_extract", {"实体ID": "miss-1", "实体名称": "缺类别实体"})
    append_row("sentiment_tag", {"记录ID": "miss-1", "文本片段": "缺类别记录"})
    check_old_interfaces("缺类别")
    check(
        "缺类别｜实体缺失类别归入「未知」",
        EntityExtractService().compute_entity_distribution().get("未知") == 1,
    )
    summary = SentimentTagService().compute_sentiment_summary()
    check(
        "缺类别｜情感缺失类别归入「未知」",
        summary["sentiment_distribution"].get("未知") == 1
        and summary["intensity_distribution"].get("未知") == 1,
    )
    check_datasets("缺类别")
    check_panels("缺类别")


def scenario_empty_category() -> None:
    print("场景三：空类别数据（空字符串保持 \"\" 类别键）")
    append_row("entity_extract", {"实体ID": "empty-1", "实体类型": ""})
    append_row("sentiment_tag", {"记录ID": "empty-1", "情感倾向": "", "强烈程度": ""})
    check_old_interfaces("空类别")
    check(
        "空类别｜实体空类别保持 \"\" 键",
        EntityExtractService().compute_entity_distribution().get("") == 1,
    )
    summary = SentimentTagService().compute_sentiment_summary()
    check(
        "空类别｜情感空类别保持 \"\" 键",
        summary["sentiment_distribution"].get("") == 1
        and summary["intensity_distribution"].get("") == 1,
    )
    check_datasets("空类别")
    check_panels("空类别")


def scenario_backfill() -> None:
    print("场景四：实体补录类别（同一来源两版数据）")
    avs = AggregateViewService()
    row = append_row("entity_extract", {"实体ID": "backfill-1", "实体名称": "补录实体"})

    # 第一版：聚合视图先读到旧计数（缺失类别归入「未知」）。
    before_panel = avs.aggregate_entity_distribution()
    before_dist = EntityExtractService().compute_entity_distribution()
    before_summary = SentimentTagService().compute_sentiment_summary()
    before_sentiment_panel = avs.aggregate_sentiment_trend()
    check("补录前｜聚合视图读到旧计数「未知」", before_dist.get("未知") == 1)

    # 同一来源补录类别，出现第二版数据。
    row["实体类型"] = "命名实体"

    after_panel = avs.aggregate_entity_distribution()
    after_dist = EntityExtractService().compute_entity_distribution()
    after_summary = SentimentTagService().compute_sentiment_summary()
    after_sentiment_panel = avs.aggregate_sentiment_trend()

    check(
        "补录后｜情感摘要批次保持不动",
        after_summary == before_summary
        and after_sentiment_panel["sentiment_distribution"]
        == before_sentiment_panel["sentiment_distribution"],
    )
    check(
        "补录后｜「未知」计数减一、新类别计数加一",
        after_dist.get("未知", 0) == before_dist.get("未知", 0) - 1
        and after_dist.get("命名实体", 0) == before_dist.get("命名实体", 0) + 1,
    )
    check(
        "补录前后｜聚合总数不变（记录不重复计数）",
        after_panel["total_entities"] == before_panel["total_entities"],
    )

    # 当轮分布计数解释数据集：补录记录只贡献一次，且归入新类别。
    dataset = EntityExtractService().entity_distribution_dataset()
    contribs = [c for c in dataset["contributions"] if c["id"] == row["id"]]
    check(
        "补录后｜当轮数据集中补录记录只贡献一次且归入新类别",
        len(contribs) == 1 and contribs[0]["category"] == "命名实体",
    )
    detail = avs.category_detail("entity_extract", "命名实体")
    check(
        "补录后｜点进新类别明细可定位到补录记录",
        detail is not None
        and detail["members"].count(row["id"]) == 1
        and detail["count"] == len(detail["members"]),
    )
    check_old_interfaces("补录后")
    check_datasets("补录后")
    check_panels("补录后")


def main() -> int:
    snapshots = {
        module: copy.deepcopy(store.rows(module))
        for module in ("entity_extract", "sentiment_tag")
    }
    for scenario in (
        scenario_normal,
        scenario_missing_category,
        scenario_empty_category,
        scenario_backfill,
    ):
        for module, rows in snapshots.items():
            store.rows(module)[:] = copy.deepcopy(rows)
        scenario()

    print(f"\n通过 {len(PASSES)} 项，失败 {len(FAILURES)} 项")
    if FAILURES:
        for name in FAILURES:
            print(f"  未通过：{name}")
        return 1
    print("全部验证通过：旧接口口径不变，分布计数解释数据集与聚合明细一致。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
