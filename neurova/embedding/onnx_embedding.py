"""
ONNX Embedding Engine - ONNX Runtime 向量嵌入引擎

基于 ONNX Runtime 的本地向量嵌入引擎：
- 支持 BAAI/bge-small-zh-v1.5 等嵌入模型
- 首次使用自动从 HuggingFace 下载模型
- CPU 推理，无需 GPU
- 支持批量编码和单条编码
"""

from neurova.core.logger import get_logger
import threading
import time
from pathlib import Path
from typing import Any, Dict, List

import numpy as np

logger = get_logger(__name__)


def _normalize(vec: np.ndarray) -> np.ndarray:
    """L2 归一化"""
    norm = np.linalg.norm(vec)
    if norm > 0:
        return vec / norm
    return vec


class EmbeddingResult:
    """嵌入结果"""

    def __init__(
        self,
        vectors: List[List[float]],
        model_name: str,
        dimension: int,
        inference_ms: float,
    ):
        self.vectors = vectors
        self.model_name = model_name
        self.dimension = dimension
        self.inference_ms = inference_ms

    @property
    def embedding(self) -> List[float]:
        """单条结果的便捷访问"""
        return self.vectors[0] if self.vectors else []


class ONNXEmbeddingEngine:
    """
    ONNX Runtime 向量嵌入引擎

    基于 ONNX Runtime，无需 GPU，CPU 即可运行。
    首次使用自动从 HuggingFace 下载模型（~130MB）。
    """

    def __init__(
        self,
        model_dir: str = "models/embedding/bge-small-zh-v1.5",
        model_name: str = "BAAI/bge-small-zh-v1.5",
        max_length: int = 512,
        auto_download: bool = True,
    ):
        """
        初始化 ONNX 嵌入引擎

        Args:
            model_dir: 模型本地目录
            model_name: HuggingFace 模型名称
            max_length: 最大序列长度
            auto_download: 是否自动下载模型
        """
        self._model_dir = Path(model_dir)
        self._model_name = model_name
        self._max_length = max_length
        self._auto_download = auto_download

        self._ort_session = None
        self._st_model = None
        self._tokenizer = None
        self._dimension = 0
        self._initialized = False
        self._backend_type = None
        self._lock = threading.Lock()

        # 推理统计
        self._total_requests = 0
        self._total_inference_ms = 0.0

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def stats(self) -> Dict[str, Any]:
        avg_ms = self._total_inference_ms / self._total_requests if self._total_requests > 0 else 0
        return {
            "model_name": self._model_name,
            "dimension": self._dimension,
            "initialized": self._initialized,
            "total_requests": self._total_requests,
            "total_inference_ms": round(self._total_inference_ms, 2),
            "avg_inference_ms": round(avg_ms, 2),
        }

    async def initialize(self) -> bool:
        """
        初始化嵌入引擎

        流程：
        1. 自动下载模型（如果不存在）
        2. 加载 Tokenizer
        3. 加载推理引擎（ONNX 或 sentence-transformers）
        4. 推断向量维度
        """
        try:
            from neurova.tts.model_downloader import get_model_downloader

            downloader = get_model_downloader()

            # 自动下载模型
            if self._auto_download:
                self._model_dir = downloader.ensure_model("bge-small-zh-v1.5")
            else:
                if not downloader.is_model_available("bge-small-zh-v1.5"):
                    logger.error("嵌入模型不存在: %s", self._model_dir)
                    return False

            # 加载 Tokenizer
            try:
                from sentencepiece import SentencePieceProcessor

                tokenizer_path = self._model_dir / "tokenizer.model"
                if tokenizer_path.exists():
                    self._tokenizer = SentencePieceProcessor()
                    self._tokenizer.Load(str(tokenizer_path))
                    logger.info("Tokenizer 加载完成: %s", tokenizer_path)
                else:
                    # 回退到 HuggingFace tokenizer
                    self._tokenizer = self._load_hf_tokenizer()
            except ImportError:
                logger.warning("sentencepiece 未安装，尝试 HuggingFace tokenizer")
                self._tokenizer = self._load_hf_tokenizer()

            if self._tokenizer is None:
                logger.error("Tokenizer 加载失败")
                return False

            # 优先尝试 ONNX Runtime
            onnx_loaded = await self._try_load_onnx()

            # 如果 ONNX 失败，尝试 sentence-transformers
            if not onnx_loaded:
                st_loaded = await self._try_load_sentence_transformers()
                if st_loaded:
                    return True

            if not onnx_loaded:
                logger.error("所有嵌入后端加载失败")
                return False

            return True

        except Exception as e:
            logger.error(f"ONNXEmbeddingEngine 初始化失败: {e}", exc_info=True)
            return False

    async def _try_load_onnx(self) -> bool:
        """尝试加载 ONNX Runtime 后端"""
        try:
            import onnxruntime as ort
        except ImportError:
            logger.debug("onnxruntime 未安装")
            return False

        # 查找 ONNX 模型文件
        onnx_path = self._model_dir / "model.onnx"
        if not onnx_path.exists():
            onnx_files = list(self._model_dir.glob("*.onnx"))
            if onnx_files:
                onnx_path = onnx_files[0]
            else:
                logger.debug("ONNX 模型文件不存在")
                return False

        try:
            # 创建推理 Session
            session_opts = ort.SessionOptions()
            session_opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            session_opts.inter_op_num_threads = 4
            session_opts.intra_op_num_threads = 4

            self._ort_session = ort.InferenceSession(str(onnx_path), sess_options=session_opts)

            # 推断向量维度
            output_meta = self._ort_session.get_outputs()[0]
            self._dimension = output_meta.shape[-1] if output_meta.shape else 512

            self._backend_type = "onnx"
            self._initialized = True
            logger.info(
                f"ONNXEmbeddingEngine 初始化完成 (ONNX Runtime) | "
                f"模型={self._model_name} | "
                f"维度={self._dimension}"
            )
            return True

        except Exception as e:
            logger.warning("ONNX Runtime 加载失败: %s", e)
            return False

    async def _try_load_sentence_transformers(self) -> bool:
        """尝试加载 sentence-transformers 后端"""
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            logger.debug("sentence_transformers 未安装")
            return False

        try:
            self._st_model = SentenceTransformer(str(self._model_dir))
            if hasattr(self._st_model, "get_embedding_dimension"):
                self._dimension = self._st_model.get_embedding_dimension()
            else:
                self._dimension = self._st_model.get_sentence_embedding_dimension()
            self._backend_type = "sentence_transformers"
            self._initialized = True
            logger.info(
                f"ONNXEmbeddingEngine 初始化完成 (sentence-transformers) | "
                f"模型={self._model_name} | "
                f"维度={self._dimension}"
            )
            return True

        except Exception as e:
            logger.warning("sentence-transformers 加载失败: %s", e)
            return False

    def _load_hf_tokenizer(self):
        """加载 HuggingFace tokenizer"""
        # 尝试直接用 tokenizers 库加载
        try:
            from tokenizers import Tokenizer

            tokenizer_path = self._model_dir / "tokenizer.json"
            if tokenizer_path.exists():
                tokenizer = Tokenizer.from_file(str(tokenizer_path))
                logger.info("tokenizers.Tokenizer 加载完成: %s", tokenizer_path)
                return tokenizer
        except Exception as e:
            logger.debug("tokenizers.Tokenizer 加载失败: %s", e)

        # 回退到 transformers
        try:
            from transformers import AutoTokenizer

            tokenizer = AutoTokenizer.from_pretrained(str(self._model_dir))
            logger.info("HuggingFace tokenizer 加载完成: %s", self._model_dir)
            return tokenizer
        except Exception as e:
            logger.warning("HuggingFace tokenizer 加载失败: %s", e)
            return None

    def encode(self, text: str) -> List[float]:
        """
        将单条文本编码为向量

        Args:
            text: 输入文本

        Returns:
            归一化向量
        """
        result = self.encode_batch([text])
        return result.vectors[0] if result.vectors else [0.0] * self._dimension

    def encode_batch(self, texts: List[str]) -> EmbeddingResult:
        """
        批量文本编码

        Args:
            texts: 文本列表

        Returns:
            EmbeddingResult
        """
        if not self._initialized:
            logger.error("ONNXEmbeddingEngine 未初始化")
            return EmbeddingResult(
                vectors=[[0.0] * 512] * len(texts),
                model_name=self._model_name,
                dimension=512,
                inference_ms=0,
            )

        start_time = time.time()

        try:
            # sentence-transformers 后端
            if self._backend_type == "sentence_transformers" and self._st_model:
                embeddings = self._st_model.encode(
                    texts,
                    normalize_embeddings=True,
                    show_progress_bar=False,
                )
                inference_ms = (time.time() - start_time) * 1000
                self._total_requests += len(texts)
                self._total_inference_ms += inference_ms

                return EmbeddingResult(
                    vectors=embeddings.tolist(),
                    model_name=self._model_name,
                    dimension=self._dimension,
                    inference_ms=round(inference_ms, 2),
                )

            # ONNX Runtime 后端
            input_ids_list = []
            attention_mask_list = []

            for text in texts:
                if hasattr(self._tokenizer, "encode"):
                    # SentencePiece or tokenizers.Tokenizer
                    encoded = self._tokenizer.encode(text)
                    if hasattr(encoded, "ids"):
                        token_ids = encoded.ids
                    elif isinstance(encoded, list) and len(encoded) > 0 and isinstance(encoded[0], int):
                        token_ids = encoded
                    else:
                        token_ids = list(encoded)
                else:
                    # Simple tokenizer
                    token_ids = self._tokenizer.encode(text, max_length=self._max_length)

                # 截断
                if len(token_ids) > self._max_length:
                    token_ids = token_ids[: self._max_length]

                # 创建 attention mask
                attention_mask = [1] * len(token_ids)

                # Padding
                pad_len = self._max_length - len(token_ids)
                token_ids += [0] * pad_len
                attention_mask += [0] * pad_len

                input_ids_list.append(token_ids)
                attention_mask_list.append(attention_mask)

            # 转为 numpy
            input_ids = np.array(input_ids_list, dtype=np.int64)
            attention_mask = np.array(attention_mask_list, dtype=np.int64)

            # ONNX 推理
            ort_inputs = {
                "input_ids": input_ids,
                "attention_mask": attention_mask,
            }

            # 尝试添加 token_type_ids
            token_type_ids = np.zeros_like(input_ids, dtype=np.int64)
            input_names = [inp.name for inp in self._ort_session.get_inputs()]
            if "token_type_ids" in input_names:
                ort_inputs["token_type_ids"] = token_type_ids

            outputs = self._ort_session.run(None, ort_inputs)

            # 提取嵌入向量（取 [CLS] token 的输出）
            embeddings = outputs[0]
            if embeddings.ndim == 3:
                # (batch, seq_len, dim) -> 取 [CLS] token
                embeddings = embeddings[:, 0, :]

            # L2 归一化
            embeddings = np.array([_normalize(vec) for vec in embeddings])

            # 转为 Python list
            vectors = embeddings.tolist()

            inference_ms = (time.time() - start_time) * 1000
            self._total_requests += len(texts)
            self._total_inference_ms += inference_ms

            return EmbeddingResult(
                vectors=vectors,
                model_name=self._model_name,
                dimension=self._dimension,
                inference_ms=round(inference_ms, 2),
            )

        except Exception as e:
            logger.error(f"嵌入编码失败: {e}", exc_info=True)
            inference_ms = (time.time() - start_time) * 1000
            return EmbeddingResult(
                vectors=[[0.0] * self._dimension] * len(texts),
                model_name=self._model_name,
                dimension=self._dimension,
                inference_ms=round(inference_ms, 2),
            )

    async def shutdown(self) -> None:
        """关闭引擎"""
        self._ort_session = None
        self._st_model = None
        self._tokenizer = None
        self._initialized = False
        self._backend_type = None
        logger.info("ONNXEmbeddingEngine 已关闭 | 统计: %s", self.stats)
