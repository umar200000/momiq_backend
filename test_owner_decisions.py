import secrets
import sqlite3
import unittest
from datetime import datetime, timezone
import booking_reviews
import catalog
import legal_documents
import server
import test_api
import test_catalog
from booking_engine import BookingError


class LegalDraftHttpTests(unittest.TestCase):
    setUpClass=classmethod(test_api.ApiTests.setUpClass.__func__)
    tearDownClass=classmethod(test_api.ApiTests.tearDownClass.__func__)
    setUp=test_api.ApiTests.setUp
    req=test_api.ApiTests.req

    def payload(self):
        row=self.req('/api/admin/legal-documents',admin=True)
        return {key:row[key] for key in ('version','organization','documents')}|{'reason':'TEST legal correction'}

    def test_private_drafts_defaults_and_roles(self):
        self.req('/api/admin/legal-documents',expected=401)
        self.req('/api/legal-documents',expected=401)
        data=self.req('/api/admin/legal-documents',admin=True)
        self.assertEqual(data['status'],'draft');self.assertEqual(set(data['documents']),set(legal_documents.DOCUMENTS))
        self.assertEqual(data['supportSchedule'],{'timezone':'Asia/Tashkent','weekdays':[1,2,3,4,5,6],'opens':'09:00','closes':'18:00','reviewBusinessDays':3})
        for role in ('support','moderation','finance'):
            with server.db() as con:con.execute("UPDATE admin_permissions SET role=? WHERE username='admin'",(role,))
            try:
                self.req('/api/admin/login','POST',{'username':'admin','password':'test-admin-password'},admin=True)
                self.req('/api/admin/legal-documents',admin=True,expected=403)
                self.req('/api/admin/legal-documents/history',admin=True,expected=403)
                self.req('/api/admin/legal-documents','PUT',{},admin=True,expected=403)
            finally:
                with server.db() as con:con.execute("UPDATE admin_permissions SET role='administrator' WHERE username='admin'")

    def test_save_roundtrip_conflict_history_and_immutable_versions(self):
        data=self.payload();data['organization']['legalName']='TEST Momiq';data['documents']['terms']='TEST {{legalName}} <script>plain text</script>'
        saved=self.req('/api/admin/legal-documents','PUT',data,admin=True)
        self.assertEqual(saved['version'],data['version']+1);self.assertEqual(saved['documents'],data['documents'])
        self.req('/api/admin/legal-documents','PUT',data,admin=True,expected=409)
        self.assertEqual(self.req('/api/admin/legal-documents',admin=True),saved)
        history=self.req('/api/admin/legal-documents/history',admin=True)['items']
        self.assertEqual(history[0]['version'],saved['version']);self.assertEqual(history[0]['reason'],data['reason'])
        for sql in ['UPDATE legal_document_versions SET actor=actor','DELETE FROM legal_document_versions',
                    'INSERT OR REPLACE INTO legal_document_versions SELECT * FROM legal_document_versions']:
            with server.db() as con:
                with self.assertRaises(sqlite3.IntegrityError):con.execute(sql)

    def test_bad_fields_queries_and_failed_audit_never_commit(self):
        original=self.payload()
        for patch in ({'version':True},{'reason':''},{'documents':{}},{'organization':[]},{'published':True}):
            self.req('/api/admin/legal-documents','PUT',original|patch,admin=True,expected=400)
        self.req('/api/admin/legal-documents?publish=true','PUT',original,admin=True,expected=400)
        self.req('/api/admin/legal-documents/history?before=0',admin=True,expected=400)
        with server.db() as con:con.execute("CREATE TRIGGER fail_legal_audit BEFORE INSERT ON audit WHEN NEW.action='legal-draft-save' BEGIN SELECT RAISE(ABORT,'TEST audit unavailable'); END")
        try:self.req('/api/admin/legal-documents','PUT',original,admin=True,expected=500)
        finally:
            with server.db() as con:con.execute('DROP TRIGGER fail_legal_audit')
        self.assertEqual(self.payload(),original)

    def test_review_restore_rejected_before_database_for_nonadministrator(self):
        for role in ('support','moderation','finance'):
            with server.db() as con,self.assertRaises(BookingError) as raised:
                booking_reviews.moderate(con,'TEST operator',1,{'hidden':False,'revision':1,'requestId':secrets.token_hex(16),'reason':'TEST restore'},datetime.now(timezone.utc),role)
            self.assertEqual(raised.exception.status,403)


class ListingRestoreRoleTests(unittest.TestCase):
    setUp=test_catalog.CatalogTests.setUp
    save=test_catalog.CatalogTests.save
    review=test_catalog.CatalogTests.review

    def test_moderator_cannot_restore_suspended_listing_administrator_can(self):
        self.save();self.review();self.review(revision=2,decision='suspend')
        data={'decision':'approve','reason':'TEST appeal upheld','testOnly':True,'_revision':3}
        with server.db() as con,self.assertRaises(catalog.CatalogError) as raised:
            catalog.review(con,'abc','boarding',data,'TEST moderator','local','moderation')
        self.assertEqual(raised.exception.status,403)
        with server.db() as con:
            self.assertEqual(catalog.document(con,'abc')['_revision'],3)
        with server.db() as con:
            restored=catalog.review(con,'abc','boarding',data,'admin','local','administrator')
        self.assertEqual(restored['moderation']['boarding']['status'],'approved')


if __name__=='__main__':unittest.main()
