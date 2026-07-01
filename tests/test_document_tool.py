import json
import os
import tempfile
import unittest
import zipfile

from aiagent.context_references import preprocess_context_references
from aiagent.tools.document_tool import read_document
from aiagent.tools.path_context import set_tool_workspace


class DocumentToolTests(unittest.TestCase):
    def setUp(self):
        self.previous_cwd = os.getcwd()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = os.path.join(self.temp_dir.name, "workspace")
        os.makedirs(self.workspace)
        set_tool_workspace(self.workspace)

    def tearDown(self):
        os.chdir(self.previous_cwd)
        set_tool_workspace(self.previous_cwd)
        self.temp_dir.cleanup()

    def test_read_document_extracts_docx_text_and_tables(self):
        self._write_docx(
            "brief.docx",
            """
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
              <w:body>
                <w:p><w:r><w:t>Sierra project brief</w:t></w:r></w:p>
                <w:tbl>
                  <w:tr>
                    <w:tc><w:p><w:r><w:t>Name</w:t></w:r></w:p></w:tc>
                    <w:tc><w:p><w:r><w:t>Sierra</w:t></w:r></w:p></w:tc>
                  </w:tr>
                </w:tbl>
              </w:body>
            </w:document>
            """,
        )

        result = json.loads(read_document("brief.docx"))

        self.assertEqual(result["kind"], "docx")
        self.assertIn("Sierra project brief", result["text"])
        self.assertIn("Name | Sierra", result["text"])
        self.assertFalse(result["truncated"])

    def test_context_reference_expands_docx_file(self):
        self._write_docx(
            "notes.docx",
            """
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
              <w:body>
                <w:p><w:r><w:t>Forest companion notes</w:t></w:r></w:p>
              </w:body>
            </w:document>
            """,
        )

        result = preprocess_context_references(
            "总结 @file:`notes.docx`",
            workspace=self.workspace,
            context_window=120000,
        )

        self.assertTrue(result.expanded)
        self.assertIn("Forest companion notes", result.context)
        self.assertIn("Kind: docx", result.context)

    def test_legacy_doc_reports_clear_error(self):
        path = os.path.join(self.workspace, "old.doc")
        with open(path, "wb") as handle:
            handle.write(b"legacy")

        result = json.loads(read_document("old.doc"))

        self.assertIn("legacy binary Office format", result["error"])

    def _write_docx(self, name: str, document_xml: str) -> str:
        path = os.path.join(self.workspace, name)
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", "<Types></Types>")
            archive.writestr("word/document.xml", document_xml)
        return path


if __name__ == "__main__":
    unittest.main()
