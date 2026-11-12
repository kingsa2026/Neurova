# -*- coding: utf-8 -*-
"""C1 RDF/XML 导入面（specs/2026-11-12 §18）：
inert 姿态＋字节级往返＋DOCTYPE 拒＋资源上限＋原始字节保留。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.ontology.rdf_import import (
    MAX_IMPORT_BYTES,
    RdfImportLimitError,
    RdfImportNotSupported,
    RdfImportSecurityError,
    importRdfXml,
)


RDF_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:kbg="https://neurova.local/knowledge/">
  <rdf:Description rdf:about="https://neurova.local/knowledge/subject1">
    <kbg:linked>object1</kbg:linked>
  </rdf:Description>
</rdf:RDF>"""


class TestImport:
    def test_basicImport(self):
        """合法 RDF/XML：解析三元组＋原始字节保留＋inert=True。"""
        result = importRdfXml(RDF_XML)
        assert result.triple_count >= 1
        assert result.inert is True, "导入缺省 inert（SHACL/OWL 不执行）"
        assert result.original_bytes == RDF_XML, "原始字节保留"

    def test_doctypeRejected(self):
        """DOCTYPE 声明显式拒（XXE 面收窄——在解析器之前拦截）。"""
        with pytest.raises(RdfImportSecurityError, match="DOCTYPE"):
            importRdfXml(b'<?xml version="1.0"?><!DOCTYPE rdf:RDF [<!ENTITY x "y">]>'
                         b'<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
                         b'</rdf:RDF>')

    def test_entityRejected(self):
        with pytest.raises(RdfImportSecurityError, match="ENTITY"):
            importRdfXml(b'<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
                         b'<!ENTITY evil "gotcha">></rdf:RDF>')

    def test_byteLimitExceeded(self):
        """字节数超上限显式拒。"""
        big = b"<rdf:RDF xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#'>"
        big += b"<rdf:Description/>" * (MAX_IMPORT_BYTES // 10)
        big += b"</rdf:RDF>"
        with pytest.raises(RdfImportLimitError, match="上限"):
            importRdfXml(big)

    def test_rdflibUnavailableExplicit(self, monkeypatch):
        """rdflib 未装：显式 not_supported（不静默降级）。"""
        from neurova.knowledge.ontology import rdf_import

        monkeypatch.setattr(rdf_import, "_rdflibAvailable", lambda: False)
        with pytest.raises(RdfImportNotSupported):
            importRdfXml(RDF_XML)

    def test_originalBytesPreservedAfterParse(self):
        """解析后原始字节不变（无损往返的基础）。"""
        result = importRdfXml(RDF_XML)
        assert result.original_bytes == RDF_XML
        assert result.triple_count > 0
        assert result.original_bytes == RDF_XML, "二次确认不丢字节"
