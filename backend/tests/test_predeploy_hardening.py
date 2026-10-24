from __future__ import annotations

import io
import json
import unittest
import zipfile
from types import SimpleNamespace
from unittest.mock import patch

from app.file_validation import FileValidationError, validate_file_bytes


class PredeployHardeningTest(unittest.TestCase):
    def test_valid_xlsx_and_video_return_semantic_categories(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("[Content_Types].xml", "<Types/>")
            archive.writestr("xl/workbook.xml", "<workbook/>")
        office = validate_file_bytes("terms.xlsx", buffer.getvalue())
        self.assertEqual(office["category"], "office")
        self.assertTrue(office["valid"])

        ffprobe = SimpleNamespace(returncode=0, stdout=json.dumps({"streams": [{"codec_type": "video", "codec_name": "h264"}], "format": {"duration": "1"}}))
        with patch("app.file_validation._magic_mime", return_value="video/mp4"), patch("app.file_validation.shutil.which", return_value="/usr/bin/ffprobe"), patch("app.file_validation.subprocess.run", return_value=ffprobe):
            video = validate_file_bytes("example.mp4", b"not-a-real-video")
        self.assertEqual(video["category"], "video")
        self.assertTrue(video["valid"])

    def test_rejected_file_keeps_semantic_category(self):
        with self.assertRaises(FileValidationError) as caught:
            validate_file_bytes("broken-paper.pdf", b"not a pdf")
        self.assertEqual(caught.exception.details["category"], "document")


if __name__ == "__main__":
    unittest.main()
