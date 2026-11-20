"""实体抽取领域服务：从DOM解析结果中识别命名实体。"""
from __future__ import annotations

import hashlib
import re
from typing import Any

from app.services.base import BaseModuleService
from app.services.distribution import build_distribution_dataset, dataset_counts
from app.store import store


ENTITY_TYPE_MAP = {
    "title": re.compile(r"<title[^>]*>(.*?)</title>", re.I),
    "heading": re.compile(r"<h[1-6][^>]*>(.*?)</h[1-6]>", re.I),
    "link": re.compile(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.I),
    "meta_value": re.compile(r'<meta[^>]+content=["\']([^"\']+)["\']', re.I),
}


class EntityExtractService(BaseModuleService):
    MODULE = "entity_extract"
    ENTITY = "实体条目"
    OPERATION_TERM = "校验"
    LIST_FIELDS = ["实体ID", "实体类型", "实体名称", "页面来源", "原文片段", "置信度", "抽取时间"]
    REQUIRED_FIELDS = ["实体ID", "实体类型", "实体名称"]
    STATUS_ORDER = ["已抽取", "已校验", "已入库", "已废弃"]
    ACTION_RULES = {"校验实体": "已抽取", "确认入库": "已校验", "标记废弃": "已抽取"}
    NEGATIVE_ACTIONS = []

    def extract_from_parse(self, dom_parser_config_id: int) -> dict[str, Any]:
        """从DOM解析配置的输出中抽取实体，整合 dom_parser -> entity_extract 消费链。"""
        from app.services.dom_parser import DomParserService
        dps = DomParserService()
        feed = dps.feed_entity_extract(dom_parser_config_id)
        if not feed["ok"]:
            return feed
        source_uri = feed["source_uri"]
        fields = feed["fields_for_extraction"]
        entities = []
        for idx, field in enumerate(fields):
            eid = hashlib.md5(f"{source_uri}|{field}".encode()).hexdigest()[:8]
            confidence = round(0.95 - (0.05 * (idx % 3)), 2)
            entities.append({
                "实体ID": eid,
                "实体类型": self._guess_type(field),
                "实体名称": field,
                "页面来源": source_uri,
                "原文片段": f"提取自 {source_uri} #{idx+1}",
                "置信度": str(confidence),
                "抽取时间": "2026-11-19",
            })
        return {"ok": True, "source_uri": source_uri, "entity_count": len(entities), "entities": entities}

    def entity_distribution_dataset(self) -> dict[str, Any]:
        """实体类型的分布计数解释数据集：计数与贡献明细一体，供聚合视图定位。"""
        return build_distribution_dataset(store.rows(self.MODULE), "实体类型")

    def compute_entity_distribution(self) -> dict[str, int]:
        """计算实体类型分布，供聚合视图消费。"""
        return dataset_counts(self.entity_distribution_dataset())

    def extract_for_relation_graph(self) -> list[dict[str, Any]]:
        """将已入库实体提供给关系图谱模块构建关系。"""
        rows = [r for r in store.rows(self.MODULE) if r.get("status") == "已入库"]
        return [
            {"entity_id": r.get("实体ID"), "entity_type": r.get("实体类型"),
             "entity_name": r.get("实体名称"), "source_page": r.get("页面来源")}
            for r in rows
        ]

    def _guess_type(self, field_name: str) -> str:
        field_lower = field_name.lower()
        if any(k in field_lower for k in ("name", "名称", "title", "标题")):
            return "命名实体"
        if any(k in field_lower for k in ("price", "价格", "amount", "金额")):
            return "数值实体"
        if any(k in field_lower for k in ("date", "日期", "time", "时间")):
            return "时间实体"
        if any(k in field_lower for k in ("url", "link", "链接")):
            return "链接实体"
        return "属性实体"

    def domain_snapshot(self) -> dict[str, Any]:
        base = super().domain_snapshot()
        base["entity_distribution"] = self.compute_entity_distribution()
        base["ready_for_relation"] = len(self.extract_for_relation_graph())
        return base