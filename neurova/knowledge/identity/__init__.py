"""实体身份消解层：分块 → 多因子相似度 → 并查集聚类，全段确定性、零模型调用。"""

from .entity_blocking import EntityBlockingResolver, normalizeLabel
from .identity_merger import IdentityMerger
from .similarity_fusion import JaroWinkler, Levenshtein, SimilarityFusion, cosine
from .subject_resolver import SubjectResolution, SubjectResolver

__all__ = [
    "EntityBlockingResolver",
    "IdentityMerger",
    "JaroWinkler",
    "Levenshtein",
    "SimilarityFusion",
    "SubjectResolution",
    "SubjectResolver",
    "cosine",
    "normalizeLabel",
]
