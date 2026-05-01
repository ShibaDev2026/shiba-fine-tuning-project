"""C4 多維採納啟發式單元測試（infer_acceptance_from_text）。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from layer_0_router.telemetry import infer_acceptance_from_text


class TestInferAcceptance:
    def test_rejection_keyword_marks_not_accepted(self):
        """否定關鍵字 → accepted=False, rewrote=False"""
        sig = infer_acceptance_from_text("這個不對，重做")
        assert sig.accepted is False
        assert sig.rewrote is False
        assert sig.matched_keyword is not None

    def test_rewrite_keyword_marks_soft_reject(self):
        """改寫關鍵字 → accepted=False, rewrote=True（軟拒絕 + 修正訊號）"""
        sig = infer_acceptance_from_text("應該是 git push -u origin")
        assert sig.accepted is False
        assert sig.rewrote is True

    def test_confirmation_keyword_marks_accepted(self):
        """確認關鍵字 → accepted=True, rewrote=False"""
        sig = infer_acceptance_from_text("好謝謝")
        assert sig.accepted is True
        assert sig.rewrote is False

    def test_ambiguous_returns_none(self):
        """模糊訊號（無關鍵字）→ accepted=None（不寫入 user_accepted）"""
        sig = infer_acceptance_from_text("接下來幫我看一下另一個檔案")
        assert sig.accepted is None
        assert sig.rewrote is False
        assert sig.matched_keyword is None

    def test_priority_rejection_over_rewrite(self):
        """同時命中拒絕 + 改寫：拒絕優先（明確拒絕信號權重高）"""
        sig = infer_acceptance_from_text("不對，應該是另一個寫法")
        assert sig.accepted is False
        assert sig.rewrote is False  # 純拒絕路徑，不誤判為 rewrote
