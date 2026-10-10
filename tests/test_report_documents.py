import tempfile
import unittest
from pathlib import Path
from server import App


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
