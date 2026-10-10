import tempfile
import unittest
from pathlib import Path
from server import App
from unittest.mock import Mock
from codex_bridge import ModelError
from request_lifecycle import RequestCancelled


class Model:
    def available(self): return False


class ReportDocumentTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.app=App(Path(self.temp.name),model=Model());self.sid=self.app.store.create_session()['id']

    def test_empty_document_and_unicode_roundtrip(self):
        self.assertEqual(self.app.report_documents.get(self.sid)['body'],'')
        content='첫 문단\n\n환자가 직접 작성한 내용 <script>literal</script>'
        saved=self.app.report_documents.save(self.sid,{'title':'방문 메모','body':content,'revision':0})
        self.assertEqual(saved['revision'],1)
        self.assertEqual(self.app.report_documents.get(self.sid)['body'],content)

    def test_separate_conversations_and_cascade_delete(self):
        self.app.report_documents.save(self.sid,{'title':'첫 문서','body':'내 기록','revision':0})
        other=self.app.store.create_session()['id']
        self.assertEqual(self.app.report_documents.get(other)['body'],'')
        self.app.store.delete_session(self.sid)
        with self.app.store.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM report_documents').fetchone()[0],0)

    def test_stale_revision_cannot_overwrite_and_empty_edit_is_allowed(self):
        self.app.report_documents.save(self.sid,{'title':'처음','body':'보존','revision':0})
        with self.assertRaises(ValueError):self.app.report_documents.save(self.sid,{'title':'오래된 창','body':'덮어쓰기','revision':0})
        self.assertEqual(self.app.report_documents.get(self.sid)['body'],'보존')
        self.app.report_documents.save(self.sid,{'title':'','body':'','revision':1})
        self.assertEqual(self.app.report_documents.get(self.sid)['body'],'')

    def test_invalid_payload_does_not_change_document(self):
        for body in [{'title':'x','body':None,'revision':0},{'title':'x','body':'x'*20001,'revision':0},
                     {'title':'x'*161,'body':'x','revision':0},{'title':'x','body':'x','revision':True}]:
            with self.assertRaises(ValueError):self.app.report_documents.save(self.sid,body)
        self.assertEqual(self.app.report_documents.get(self.sid)['revision'],0)

    def draft_model(self, quote='어제는 충분히 잤고 오늘은 가볍게 산책했다.'):
        return Mock(available=Mock(return_value=True),draft_report=Mock(return_value={
            'title':'생활 리포트','sections':[{'heading':'생활 기록','statements':[{
                'text':'수면과 산책을 기록했습니다.','evidence':[{'source_id':'current-draft','quote':quote}]}]}]}))

    def test_draft_is_separate_and_has_exact_original_references(self):
        original='어제는 충분히 잤고 오늘은 가볍게 산책했다.'
        self.app.report_documents.save(self.sid,{'title':'내 리포트','body':original,'revision':0})
        result=self.app.report_documents.draft(self.sid,{'current':{'body':original}},self.draft_model())
        self.assertEqual(self.app.report_documents.get(self.sid)['body'],original)
        self.assertIn('[1]',result['body'])
        self.assertEqual(result['references'][0]['quote'],original)
        self.assertEqual(result['references'][0]['kind'],'user_written_draft')

    def test_invalid_quote_or_cross_session_reference_is_rejected(self):
        model=self.draft_model('없는 원문을 만들어낸 경우')
        with self.assertRaises(ModelError):self.app.report_documents.draft(self.sid,{'current':{'body':'실제 작성 내용'}},model)
        model=self.draft_model('실제 작성 내용')
        model.draft_report.return_value['sections'][0]['statements'][0]['evidence'][0]['source_id']='another-session-message'
        with self.assertRaises(ModelError):self.app.report_documents.draft(self.sid,{'current':{'body':'실제 작성 내용'}},model)

    def test_no_records_never_invents_a_report(self):
        model=self.draft_model()
        with self.assertRaises(ValueError):self.app.report_documents.draft(self.sid,{},model)
        model.draft_report.assert_not_called()

    def test_cancelled_draft_cannot_replace_saved_document(self):
        self.app.report_documents.save(self.sid,{'title':'보존','body':'내가 작성한 리포트','revision':0})
        model=self.draft_model();model.draft_report.side_effect=RequestCancelled()
        with self.assertRaises(RequestCancelled):self.app.report_documents.draft(self.sid,{'current':{'body':'내가 작성한 리포트'}},model)
        self.assertEqual(self.app.report_documents.get(self.sid)['body'],'내가 작성한 리포트')
