"""聚合视图领域服务：管理抽取结果的多维聚合视图。"""
from __future__ import annotations

from typing import Any

from app.services.base import BaseModuleService
from app.store import store


CHART_TYPES = ["bar", "line", "pie", "scatter", "heatmap", "table"]


class AggregateViewService(BaseModuleService):
    MODULE = "aggregate_view"
    ENTITY = "视图配置"
    OPERATION_TERM = "聚合"
    LIST_FIELDS = ["视图名称", "统计维度", "聚合字段", "时间范围", "刷新间隔", "图表类型", "数据来源"]
    REQUIRED_FIELDS = ["视图名称", "统计维度", "聚合字段"]
    STATUS_ORDER = ["草稿", "已启用", "已停用"]
    ACTION_RULES = {"启用视图": "草稿", "停用视图": "已启用"}
    NEGATIVE_ACTIONS = ["停用视图"]

    @staticmethod
    def _distribution_details(dataset: dict[str, Any]) -> list[dict[str, Any]]:
        """把数据集中的定位依据回写成本次聚合的明细清单。

        每个类别的计数与成员清单一同落进明细，点进类别即可按
        count == len(members) 互相复算。
        """
        return [
            {
                "category": category,
                "count": count,
                "members": list(dataset["members"].get(category, [])),
            }
            for category, count in dataset["counts"].items()
        ]

    def aggregate_entity_distribution(self) -> dict[str, Any]:
        """消费实体抽取的分布数据，生成聚合视图。"""
        from app.services.entity_extract import EntityExtractService
        ees = EntityExtractService()
        dataset = ees.entity_distribution_dataset()
        dist = dataset["counts"]
        return {
            "view_name": "实体类型分布",
            "chart_type": "pie",
            "data_source": "entity_extract",
            "dimensions": list(dist.keys()),
            "values": list(dist.values()),
            "total_entities": sum(dist.values()),
            "details": self._distribution_details(dataset),
        }

    def aggregate_sentiment_trend(self) -> dict[str, Any]:
        """消费情感标注的分布数据。"""
        from app.services.sentiment_tag import SentimentTagService
        sts = SentimentTagService()
        datasets = sts.sentiment_summary_dataset()
        sentiment = datasets["sentiment"]
        return {
            "view_name": "情感趋势",
            "chart_type": "bar",
            "data_source": "sentiment_tag",
            "sentiment_distribution": dict(sentiment["counts"]),
            "total_records": datasets["total_records"],
            "details": self._distribution_details(sentiment),
        }

    def category_detail(self, data_source: str, category: str) -> dict[str, Any] | None:
        """点进某一来源的类别明细：返回该类别当轮的计数与成员（定位依据）。"""
        if data_source == "entity_extract":
            panel = self.aggregate_entity_distribution()
        elif data_source == "sentiment_tag":
            panel = self.aggregate_sentiment_trend()
        else:
            return None
        for detail in panel["details"]:
            if detail["category"] == category:
                return detail
        return None

    def aggregate_quality_metrics(self) -> dict[str, Any]:
        """消费质量检查的运行结果。"""
        from app.services.quality_check import QualityCheckService
        qcs = QualityCheckService()
        pipeline = qcs.run_quality_pipeline()
        return {
            "view_name": "质量指标聚合",
            "chart_type": "bar",
            "data_source": "quality_check",
            "total_checks": pipeline.get("total_checks", 0),
            "passed_checks": pipeline.get("passed_checks", 0),
            "pass_ratio": pipeline.get("pass_ratio", 0.0),
        }

    def build_dashboard(self) -> dict[str, Any]:
        """构建完整仪表盘：聚合所有模块的快照数据。"""
        panels = [
            self.aggregate_entity_distribution(),
            self.aggregate_sentiment_trend(),
            self.aggregate_quality_metrics(),
        ]
        return {
            "ok": True,
            "dashboard_name": "语义抽取运营看板",
            "panel_count": len(panels),
            "panels": panels,
            "generated_at": "2026-11-19T10:00:00Z",
        }

    def domain_snapshot(self) -> dict[str, Any]:
        base = super().domain_snapshot()
        try:
            base["dashboard"] = self.build_dashboard()
        except Exception:
            base["dashboard"] = {"ok": False}
        return base