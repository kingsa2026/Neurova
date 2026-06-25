"""
梦境报告 Mixin - 从 MemoryStorage 中提取的梦境报告存储相关方法

提供梦境（记忆融合）报告的 CRUD 和统计查询。
"""

import datetime
from neurova.core.logger import get_logger
import uuid
from typing import Any, Dict, List, Optional

logger = get_logger(__name__)


class DreamMixin:
    """
    梦境报告 Mixin

    提供梦境（记忆融合）报告的 CRUD 和统计查询。
    """

    def __init__(self):
        """初始化梦境报告存储"""
        self._dream_reports: Dict[str, Dict[str, Any]] = {}
        logger.info("DreamMixin 初始化完成")

    def create_dream_report(
        self,
        title: str,
        content: str,
        memory_ids: List[str],
        fusion_type: str = "random",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        创建梦境报告

        Args:
            title: 报告标题
            content: 报告内容
            memory_ids: 参与融合的记忆ID列表
            fusion_type: 融合类型
            metadata: 可选的元数据

        Returns:
            创建的梦境报告
        """
        report_id = str(uuid.uuid4())
        now = datetime.datetime.now(datetime.timezone.utc)

        report = {
            "id": report_id,
            "title": title,
            "content": content,
            "memory_ids": memory_ids,
            "fusion_type": fusion_type,
            "metadata": metadata or {},
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "access_count": 0,
            "last_accessed_at": None,
        }

        self._dream_reports[report_id] = report
        logger.debug("创建梦境报告: %s", report_id)

        return report

    def get_dream_report(self, report_id: str) -> Optional[Dict[str, Any]]:
        """
        获取梦境报告

        Args:
            report_id: 报告ID

        Returns:
            梦境报告，如果不存在返回None
        """
        report = self._dream_reports.get(report_id)
        if report:
            report["access_count"] += 1
            report["last_accessed_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        return report

    def update_dream_report(
        self,
        report_id: str,
        title: Optional[str] = None,
        content: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        更新梦境报告

        Args:
            report_id: 报告ID
            title: 新标题
            content: 新内容
            metadata: 新元数据

        Returns:
            更新后的梦境报告
        """
        report = self._dream_reports.get(report_id)
        if not report:
            return None

        if title is not None:
            report["title"] = title
        if content is not None:
            report["content"] = content
        if metadata is not None:
            report["metadata"] = metadata

        report["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()

        return report

    def delete_dream_report(self, report_id: str) -> bool:
        """
        删除梦境报告

        Args:
            report_id: 报告ID

        Returns:
            是否删除成功
        """
        if report_id in self._dream_reports:
            del self._dream_reports[report_id]
            logger.debug("删除梦境报告: %s", report_id)
            return True
        return False

    def list_dream_reports(
        self,
        fusion_type: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """
        列出梦境报告

        Args:
            fusion_type: 按融合类型过滤
            limit: 返回数量限制
            offset: 偏移量

        Returns:
            梦境报告列表
        """
        reports = list(self._dream_reports.values())

        # 按融合类型过滤
        if fusion_type:
            reports = [r for r in reports if r["fusion_type"] == fusion_type]

        # 按创建时间排序（最新的在前）
        reports.sort(key=lambda x: x["created_at"], reverse=True)

        # 应用分页
        return reports[offset : offset + limit]

    def search_dream_reports(self, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        """
        搜索梦境报告

        Args:
            query: 搜索查询
            limit: 返回数量限制

        Returns:
            匹配的梦境报告
        """
        query_lower = query.lower()
        results = []

        for report in self._dream_reports.values():
            # 在标题和内容中搜索
            if query_lower in report["title"].lower() or query_lower in report["content"].lower():
                results.append(report)

        # 按相关性排序（简化版：按访问次数排序）
        results.sort(key=lambda x: x["access_count"], reverse=True)

        return results[:limit]

    def get_dream_statistics(self) -> Dict[str, Any]:
        """
        获取梦境报告统计信息

        Returns:
            统计信息字典
        """
        reports = list(self._dream_reports.values())

        if not reports:
            return {
                "total_reports": 0,
                "fusion_type_distribution": {},
                "average_memory_count": 0,
                "most_accessed": None,
                "recent_reports": [],
            }

        # 融合类型分布
        fusion_type_dist: Dict[str, int] = {}
        for report in reports:
            ft = report["fusion_type"]
            fusion_type_dist[ft] = fusion_type_dist.get(ft, 0) + 1

        # 平均记忆数量
        total_memories = sum(len(r["memory_ids"]) for r in reports)
        avg_memory_count = total_memories / len(reports)

        # 最常访问的报告
        most_accessed = max(reports, key=lambda x: x["access_count"])

        # 最近的报告
        recent_reports = sorted(reports, key=lambda x: x["created_at"], reverse=True)[:5]

        return {
            "total_reports": len(reports),
            "fusion_type_distribution": fusion_type_dist,
            "average_memory_count": avg_memory_count,
            "most_accessed": most_accessed,
            "recent_reports": recent_reports,
        }

    def get_dreams_by_memory(self, memory_id: str) -> List[Dict[str, Any]]:
        """
        获取包含特定记忆的所有梦境报告

        Args:
            memory_id: 记忆ID

        Returns:
            梦境报告列表
        """
        results = []
        for report in self._dream_reports.values():
            if memory_id in report["memory_ids"]:
                results.append(report)

        return results

    def clear_dream_reports(self) -> int:
        """
        清空所有梦境报告

        Returns:
            删除的报告数量
        """
        count = len(self._dream_reports)
        self._dream_reports.clear()
        logger.debug("清空梦境报告: %s 个", count)
        return count
