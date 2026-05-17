import unittest

from feishu_doc_exporter.client import parse_document_ref
from feishu_doc_exporter.public_web import extract_catalog_record_info, extract_public_title, render_records_to_lines


class ParseDocumentRefTest(unittest.TestCase):
    def test_docx_url(self):
        ref = parse_document_ref("https://my.feishu.cn/docx/CnPQdk671oL5wSxDV7YchA2dnpf")
        self.assertEqual(ref.token, "CnPQdk671oL5wSxDV7YchA2dnpf")
        self.assertEqual(ref.url_type, "docx")
        self.assertEqual(ref.export_type, "docx")


class PublicWebParsingTest(unittest.TestCase):
    def test_extract_catalog_record_info(self):
        html = '<script>window.catalogRecordInfo={"headingRecords":{"doc":{"data":{"type":"page","children":["a"],"text":{"initialAttributedTexts":{"text":{"0":"Title"}}}}},"a":{"data":{"type":"heading2","children":[],"text":{"initialAttributedTexts":{"text":{"0":"Section"}}}}}}};</script>'
        payload = extract_catalog_record_info(html)
        lines = render_records_to_lines(payload, "doc")
        self.assertEqual(lines, ["# Title", "", "## Section"])
        self.assertEqual(extract_public_title(payload, "doc"), "Title")

    def test_plain_token(self):
        ref = parse_document_ref("CnPQdk671oL5wSxDV7YchA2dnpf")
        self.assertEqual(ref.token, "CnPQdk671oL5wSxDV7YchA2dnpf")
        self.assertEqual(ref.export_type, "docx")


if __name__ == "__main__":
    unittest.main()
