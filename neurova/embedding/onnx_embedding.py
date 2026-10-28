"""
ONNX Embedding Engine - ONNX Runtime 向量嵌入引擎

基于 ONNX Runtime 的本地向量嵌入引擎：
- 支持 BAAI/bge-small-zh-v1.5 等嵌入模型
- 首次使用自动从 HuggingFace 下载模型
- CPU 推理，无需 GPU
- 支持批量编码和单条编码
"""

from __future__ import annotations

from neurova.core.logger import get_logger
import json
import re
import threading
import time
import unicodedata
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

logger = get_logger(__name__)

#: numpy 在 `requirements-ci.txt` 里是**登记过的可选依赖**（该清单头部的契约：被排除的重依赖
#: 「在代码中均为惰性/try 降级导入，缺席时模块仍可加载」）。此处此前是模块级 `import numpy as np`，
#: 于是「薄环境里导入本模块」直接抛 ModuleNotFoundError——`neurova/embedding/__init__.py` 是唯一
#: 顶层导入点，连带 `get_embedding_engine` 都拿不到，受保护子集里 18 格整片红（`cnb-ggt-1k5ne7emk`）。
#: 改成懒取：类型注解走 `from __future__ import annotations` 天然是字符串，运行期用到时
#: `_numpy()` 现取；缺席时它是 `None`，即「这一档不可用」的**唯一判据**——不新造第二个开关，
#: 也不在调用点抛异常（异常会把「引擎缺席即降级关键词档」的调用方从降级路径推到异常路径）。
#: **不缓存到模块全局**：`import` 自身就带 `sys.modules` 缓存，再存一份 `np = ...` 是
#: 第二个写法不同、判空不带锁的"懒建单例"（`test_lazySingletonDcl` 按形态抓的正是它）。


if TYPE_CHECKING:  # 只为类型注解：运行期一律经 `_numpy()` 取，模块导入期不碰 numpy
    from numpy.typing import NDArray


def _numpy():
    """取 numpy；缺席时返回 None（可选依赖缺席＝这一档不可用，不是异常）。"""
    try:
        import numpy as _np
    except ImportError:
        return None
    return _np


def _normalize(vec: Any) -> Any:
    """L2 归一化（numpy 档与纯 Python 档逐值同语义）。"""
    numpy = _numpy()
    if numpy is not None:
        norm = numpy.linalg.norm(vec)
        if norm > 0:
            return vec / norm
        return vec
    norm = sum(float(x) * float(x) for x in vec) ** 0.5
    if norm > 0:
        return [float(x) / norm for x in vec]
    return list(vec)


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


class _WordPieceTokenizer:
    """纯 Python 的 BERT WordPiece 分词器（零第三方依赖）。

    `tokenizers` / `transformers` 都是**可选**依赖，薄环境（CI 的 `requirements-ci.lock`）
    里两者都不在。此前 tokenizer 只走这两条 import，缺席即 `initialize_sync()` 返回
    False，`encode_batch()` 从此对每次调用返回 512 维零向量——而所有消费方都判的是
    「引擎不为 None」，于是"零向量"被当成"语义相似度 0"继续往下算：联想召回掉档、
    线索通道不点火、肌肉记忆近似问法恒不命中。报错被吞进了兜底（教义第 1、2 条）。

    词表就在模型目录里（`vocab.txt`），WordPiece 的切分规则也只有几十行，
    没必要为它拉一个重型依赖：缺 `tokenizers` 时按同一份词表自解，
    token 序列与 `tokenizers.Tokenizer` 读取同一份 `tokenizer.json` 的结果一致
    （空格切词 → 小写/去重音 → CJK 逐字 → 贪心最长匹配 → [UNK]）。
    """

    #: BERT 基础常量（bge 系列的 tokenizer_config 同此）：[CLS]/[SEP]/[UNK] 与 100 字符上限
    _MAX_CHARS_PER_WORD = 100

    def __init__(self, vocab: Dict[str, int], *, do_lower_case: bool = False,
                 strip_accents: bool = False) -> None:
        self._vocab = vocab
        self._do_lower_case = do_lower_case
        self._strip_accents = strip_accents
        self._cls_id = vocab.get("[CLS]", 101)
        self._sep_id = vocab.get("[SEP]", 102)
        self._unk_id = vocab.get("[UNK]", 100)

    @classmethod
    def fromModelDir(cls, model_dir: Path) -> "_WordPieceTokenizer":
        model_dir = Path(model_dir)
        if not (model_dir / "vocab.txt").exists():
            raise FileNotFoundError(f"词表不存在: {model_dir / 'vocab.txt'}")
        lower = False
        strip = False
        config_path = model_dir / "tokenizer_config.json"
        if config_path.exists():
            try:
                config = json.loads(config_path.read_text(encoding="utf-8"))
                lower = bool(config.get("do_lower_case", False))
                strip = bool(config.get("strip_accents", False))
            except Exception as e:      # noqa: BLE001 - 配置坏掉不该让分词器整体缺席
                logger.debug("tokenizer_config.json 读取失败，按默认大小写口径: %s", e)
        vocab = cls._vocabFromTokenizerJson(model_dir)
        if vocab is None:
            vocab = cls._vocabFromVocabTxt(model_dir / "vocab.txt")
        return cls(vocab, do_lower_case=lower, strip_accents=strip)

    @staticmethod
    def _vocabFromTokenizerJson(model_dir: Path) -> Dict[str, int] | None:
        """优先读 `tokenizer.json` 的 model.vocab。

        `vocab.txt` 的**行号**与模型实际 id 只在小词表上逐位相等：这份 bge 词表里有两行
        空 token，其后 2 万余个 token 的 id 整体偏移 2。行号当 id 会让同一个词落到别的
        embedding 行上——不报错，但语义相似度全是错的。故以模型契约（tokenizer.json）为准，
        `vocab.txt` 只在没有 tokenizer.json 时兜底。
        """
        path = model_dir / "tokenizer.json"
        if not path.exists():
            return None
        try:
            model = json.loads(path.read_text(encoding="utf-8")).get("model") or {}
            vocab = model.get("vocab")
            if isinstance(vocab, dict) and vocab:
                return {str(token): int(index) for token, index in vocab.items()}
        except Exception as e:      # noqa: BLE001 - 读不动就退到 vocab.txt
            logger.debug("tokenizer.json 词表读取失败，退到 vocab.txt: %s", e)
        return None

    @staticmethod
    def _vocabFromVocabTxt(vocab_path: Path) -> Dict[str, int]:
        vocab: Dict[str, int] = {}
        for index, line in enumerate(vocab_path.read_text(encoding="utf-8").splitlines()):
            token = line.rstrip("\n")
            if token:
                vocab[token] = index
        if not vocab:
            raise ValueError(f"词表为空: {vocab_path}")
        return vocab

    def encode(self, text: str) -> "_WordPieceEncoding":
        ids: List[int] = [self._cls_id]
        for word in self._basicTokenize(text or ""):
            ids.extend(self._wordPiece(word))
        ids.append(self._sep_id)
        return _WordPieceEncoding(ids)

    def _basicTokenize(self, text: str) -> List[str]:
        if self._strip_accents:
            text = unicodedata.normalize("NFD", text)
            text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
        if self._do_lower_case:
            text = text.lower()
        words: List[str] = []
        for chunk in re.split(r"\s+", text.strip()):
            if not chunk:
                continue
            piece = ""
            for char in chunk:
                if _isCjk(char):
                    if piece:
                        words.append(piece)
                        piece = ""
                    words.append(char)
                else:
                    piece += char
            if piece:
                words.append(piece)
        return words

    def _wordPiece(self, word: str) -> List[int]:
        if len(word) > self._MAX_CHARS_PER_WORD:
            return [self._unk_id]
        ids: List[int] = []
        start = 0
        while start < len(word):
            end = len(word)
            matched: int | None = None
            while start < end:
                piece = word[start:end]
                if start > 0:
                    piece = "##" + piece
                if piece in self._vocab:
                    matched = self._vocab[piece]
                    break
                end -= 1
            if matched is None:
                return [self._unk_id]
            ids.append(matched)
            start = end
        return ids


class _WordPieceEncoding:
    """`tokenizers.Encoding` 的最小同形：`encode()` 的调用方只读 `.ids`。"""

    __slots__ = ("ids",)

    def __init__(self, ids: List[int]) -> None:
        self.ids = ids


def _isCjk(char: str) -> bool:
    """CJK 逐字切分的判定面（与 BERT 的 `_is_chinese_char` 同一批码位块）。"""
    code = ord(char)
    return (
        0x4E00 <= code <= 0x9FFF
        or 0x3400 <= code <= 0x4DBF
        or 0x20000 <= code <= 0x2A6DF
        or 0x2A700 <= code <= 0x2B73F
        or 0x2B740 <= code <= 0x2B81F
        or 0x2B820 <= code <= 0x2CEAF
        or 0xF900 <= code <= 0xFAFF
        or 0x2F800 <= code <= 0x2FA1F
    )


class ONNXEmbeddingEngine:
    """
    ONNX Runtime 向量嵌入引擎

    基于 ONNX Runtime，无需 GPU，CPU 即可运行。
    首次使用自动从 HuggingFace 下载模型（~130MB）。
    """

    def __init__(
        self,
        model_dir: str = "",
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
        # 模型目录锚在仓库根（随代码走的资产），不随 CWD 漂移。
        from neurova.core.data_root import repoAsset

        self._model_dir = (Path(model_dir) if model_dir
                           else repoAsset("models", "embedding", "bge-small-zh-v1.5"))
        self._model_name = model_name
        self._max_length = max_length
        self._auto_download = auto_download

        self._ort_session = None
        self._st_model = None
        self._tokenizer = None
        self._dimension = 0
        self._initialized = False
        self._backend_type = None
        #: 由工厂交出过的实例（见 `markHandedOutByFactory` / `isHandedOutByFactory`）。
        self._handedOut = False
        self._lock = threading.RLock()

        # 推理统计
        self._total_requests = 0
        self._total_inference_ms = 0.0

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    def markHandedOutByFactory(self) -> None:
        """点名「本实例是 `get_embedding_engine()` 交出的那一份」。

        工厂交出的是**尚未装载任何模型**的裸实例。这类实例一旦进入 `encode_batch`，
        那一段的懒初始化自救就会去走
        `initialize_sync() → ModelDownloader.ensure_model(..., auto_download=True)`——
        在一条判据的路径上出网拉权重。判别「这个实例有没有被交出去过」若靠
        「有没有模型」，就把"没装"与"装过"混成一件事；故由工厂在交出时点名，
        消费方据此决定要不要读它（`isHandedOutByFactory`）。
        """
        self._handedOut = True

    @property
    def isHandedOutByFactory(self) -> bool:
        """这个实例是不是由 `get_embedding_engine()` 交出、且尚未装载模型的那一份。

        True 的含义不是"不能用"，而是"**读它就等于现场建模型**"：编码会走到
        `initialize_sync()`/`ensure_model`。要求"不许为算一次分把模型拉起来"的
        消费方据此回退，而不是各自去判一遍就绪位。
        """
        return bool(self._handedOut) and not self._initialized

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def backend_type(self) -> Optional[str]:
        """本次实例实际走的是哪一档（`onnx` / `sentence_transformers` / `None`）。

        只读公开面：`_backend_type` 此前只在**模块内部**被读写，调用方要判档只能摸私有
        属性。而"哪一档在服务"是可观测契约——同一份语料在两档下的检索读数本征不同
        （实测词法兜底 MRR 0.303、稠密档 0.35），判据与日志都必须能指名档位，
        否则「换了档」会读成「检索退化了」。
        """
        return self._backend_type

    @property
    def stats(self) -> Dict[str, Any]:
        with self._lock:
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
        """异步初始化（契约保持：内部全为同步 I/O，直接走同步路径）"""
        return self.initialize_sync()

    def initialize_sync(self) -> bool:
        """
        同步初始化嵌入引擎

        流程：
        1. 自动下载模型（如果不存在）
        2. 加载 Tokenizer
        3. 加载推理引擎（ONNX 或 sentence-transformers）
        4. 推断向量维度

        事故约束（2026-09-10 CPU 打满）：初始化必须是可在事件循环内直接
        调用的同步方法——此前的"假异步"导致懒初始化在请求路径上永远无法
        完成，编码器整体降级 TF-IDF 全量重算。
        """
        with self._lock:
            if self._initialized:
                return True
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

                # 优先尝试 ONNX Runtime；失败再尝试 sentence-transformers
                if self._try_load_onnx():
                    return True
                return self._try_load_sentence_transformers()

            except Exception as e:
                logger.error(f"ONNXEmbeddingEngine 初始化失败: {e}", exc_info=True)
                return False

    def _try_load_onnx(self) -> bool:
        """尝试加载 ONNX Runtime 后端"""
        if _numpy() is None:
            # 前处理与后处理全是 ndarray 运算：缺 numpy 时这一档整体不可用。
            # 让位给 sentence-transformers 档（它不需要 numpy），而不是先加载
            # session 再在 encode 时崩。
            logger.debug("numpy 未安装，跳过 ONNX Runtime 后端")
            return False
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

    def _try_load_sentence_transformers(self) -> bool:
        """尝试加载 sentence-transformers 后端"""
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            logger.debug("sentence_transformers 未安装")
            return False

        try:
            # 限核保护: torch CPU 默认线程 = 全部核心, 后台索引会烧满整机。
            # 与 onnxruntime 后端 intra_op_num_threads=4 对齐。
            try:
                import os as _os
                import torch as _torch

                _torch.set_num_threads(int(_os.environ.get("NEUROVA_TORCH_THREADS", "4")))
            except Exception:
                pass

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
            logger.debug("HuggingFace tokenizer 加载失败，改用内置 WordPiece 分词: %s", e)

        # 最后一道：按模型目录自带的 `vocab.txt` 走纯 Python WordPiece。
        # 前两条都是**可选**依赖，两条都缺席是薄环境的常态，不该等于"引擎初始化失败"。
        try:
            tokenizer = _WordPieceTokenizer.fromModelDir(self._model_dir)
            logger.info("内置 WordPiece 分词器加载完成: %s", self._model_dir / "vocab.txt")
            return tokenizer
        except Exception as e:      # noqa: BLE001 - 词表真的不在，才是初始化失败
            logger.error("分词器全部不可用（tokenizers / transformers / vocab.txt）: %s", e)
            return None

    def encodeOrNone(self, text: str) -> Optional[List[float]]:
        """能真算才返回向量。

        为什么必须有这个口：`encode` 的契约是"总是给一列浮点"，算不出时给**零向量**。
        零向量传得下去，但传下去之后就再没人和"真算出一个全零向量"区分得开——下游把
        恒定 0 的余弦当"不相似"读，缺陷于是在读数里彻底不可见（`requirements-ci.txt`
        刻意不含 onnxruntime/tokenizers 时，四个消费方全都读成了"有向量、只是不相似"）。

        判据只有这一处：引擎自己交出的向量、维数对得上、且有一个分量不是 0。
        想写"算不出就别写"的消费方一律走这个口，不各自再判一遍零向量。
        """
        vector = [float(x) for x in self.encode(text)]
        if len(vector) != self._dimension or not any(vector):
            logger.debug("嵌入引擎未就绪（%s），本轮不给向量", self._unreadyReason())
            return None
        return vector

    def _unreadyReason(self) -> str:
        """引擎未就绪的原因（点名到缺哪一件，好让调用方把它写进日志而不是留白）。"""
        if self._initialized:
            return "已初始化"
        try:
            import onnxruntime  # noqa: F401
        except ImportError:
            return "onnxruntime 未安装"
        try:
            import sentence_transformers  # noqa: F401
        except ImportError:
            return "onnxruntime/sentence_transformers 均缺或模型未加载"
        return "后端未加载"

    def encode(self, text: str) -> List[float]:
        """
        将单条文本编码为向量

        Args:
            text: 输入文本

        Returns:
            向量；引擎未就绪时为全零（"算不出"要用 `encodeOrNone`，别从零向量反推）
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
            # 懒初始化自救：get_embedding_engine()/UnifiedVectorStore 拿到的
            # 都是未加载模型的裸实例，此处不初始化则所有消费方拿到静默零向量
            if not self.initialize_sync():
                logger.error("ONNXEmbeddingEngine 初始化失败，返回零向量兜底")
                return EmbeddingResult(
                    vectors=[[0.0] * 512] * len(texts),
                    model_name=self._model_name,
                    dimension=512,
                    inference_ms=0,
                )

        start_time = time.time()

        # 缺 numpy 时 ONNX 这一档整段不可用（前处理/后处理都是 ndarray 运算）：
        # 在此点名并返回零向量兜底（与下方既有的「初始化失败」兜底同一形态），
        # 而不是让 `np.array` 抛 AttributeError——后者会把「可选依赖缺席」
        # 伪装成「代码缺陷」。运行时按 backend_type 判定，不按代码位置假设。
        if _numpy() is None and self._backend_type != "sentence_transformers":
            logger.error("numpy 缺席，ONNX 推理档不可用，返回零向量兜底")
            return EmbeddingResult(
                vectors=[[0.0] * 512] * len(texts),
                model_name=self._model_name,
                dimension=512,
                inference_ms=0,
            )

        try:
            # sentence-transformers 后端
            if self._backend_type == "sentence_transformers" and self._st_model:
                embeddings = self._st_model.encode(
                    texts,
                    normalize_embeddings=True,
                    show_progress_bar=False,
                )
                inference_ms = (time.time() - start_time) * 1000
                with self._lock:
                    self._total_requests += len(texts)
                    self._total_inference_ms += inference_ms

                return EmbeddingResult(
                    vectors=embeddings.tolist(),
                    model_name=self._model_name,
                    dimension=self._dimension,
                    inference_ms=round(inference_ms, 2),
                )

            # 固定序列轴必须遵守模型契约；动态轴仅补齐批内最长文本，
            # 避免短查询也计算 512 token（并发召回曾在真实 ONNX 推理中超时）。
            model_inputs = self._ort_session.get_inputs()
            sequence_size = next((inp.shape[1] for inp in model_inputs
                                  if inp.name == "input_ids"), None)
            fixed_size = sequence_size if isinstance(sequence_size, int) and sequence_size > 0 else None
            token_limit = min(self._max_length, fixed_size or self._max_length)
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
                if len(token_ids) > token_limit:
                    token_ids = token_ids[:token_limit]

                # 创建 attention mask
                # 复制后再改写：tokenizers 返回的列表不得被原地补齐污染
                token_ids = list(token_ids)
                attention_mask = [1] * len(token_ids)

                input_ids_list.append(token_ids)
                attention_mask_list.append(attention_mask)

            # Padding：动态轴仅补齐批内最长序列；固定轴已并入 token_limit。
            # 全空序列时保留 1 位占位（序列轴不得为 0）。
            batch_longest = max((len(t) for t in input_ids_list), default=0) or 1
            for token_ids in input_ids_list:
                token_ids.extend([0] * (batch_longest - len(token_ids)))
            for attention_mask in attention_mask_list:
                attention_mask.extend([0] * (batch_longest - len(attention_mask)))

            # 转为 numpy（惰性取：薄环境里这一支根本走不到，本模块仍可导入）
            numpy = _numpy()
            input_ids = numpy.array(input_ids_list, dtype=numpy.int64)
            attention_mask = numpy.array(attention_mask_list, dtype=numpy.int64)

            # ONNX 推理
            ort_inputs = {
                "input_ids": input_ids,
                "attention_mask": attention_mask,
            }

            # 尝试添加 token_type_ids
            token_type_ids = numpy.zeros_like(input_ids, dtype=numpy.int64)
            input_names = [inp.name for inp in model_inputs]
            if "token_type_ids" in input_names:
                ort_inputs["token_type_ids"] = token_type_ids

            outputs = self._ort_session.run(None, ort_inputs)

            # 提取嵌入向量（取 [CLS] token 的输出）
            embeddings = outputs[0]
            if embeddings.ndim == 3:
                # (batch, seq_len, dim) -> 取 [CLS] token
                embeddings = embeddings[:, 0, :]

            # L2 归一化
            embeddings = numpy.array([_normalize(vec) for vec in embeddings])

            # 转为 Python list
            vectors = embeddings.tolist()

            inference_ms = (time.time() - start_time) * 1000
            with self._lock:
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

    def releaseBackend(self) -> None:
        """丢弃后端引用**并**把原生内存还回去（同步，不依赖事件循环）。

        `InferenceSession` 持有的是原生内存，只把引用置 None 是交给 GC——
        长进程（受保护子集单进程跑近八千档）里等于不释放，一路顶到 runner 的
        内存上限被 SIGKILL（pipeline-3 的 137 就是这么来的）。故显式 close()。

        为什么是同步方法而不是只有 async 的 `shutdown()`：重置入口
        （`reset_embedding_engine`）可能在**已有事件循环**里被调用，
        那里再 `asyncio.run()` 会抛 `RuntimeError`，协程从不执行、
        session 也就不释放——泄漏在异步上下文里原样复发。
        """
        session = self._ort_session
        self._ort_session = None
        if session is not None:
            # 关闭动作本身不得把停机流程变成崩溃：缺 close() 的后端原样跳过。
            closeSession = getattr(session, "close", None)
            if callable(closeSession):
                try:
                    closeSession()
                except Exception as e:
                    logger.warning("关闭 ONNX 会话失败: %s", e)
        self._st_model = None
        self._tokenizer = None

    async def shutdown(self) -> None:
        """关闭引擎，**并把原生内存还回去**。"""
        self.releaseBackend()
        self._initialized = False
        self._backend_type = None
        logger.info("ONNXEmbeddingEngine 已关闭 | 统计: %s", self.stats)
