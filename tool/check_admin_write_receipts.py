"""Check admin acknowledgements against isolated backend HTTP test responses.

Runs a fixed allowlist of temporary-database tests; no live integration tests,
provider calls or production credentials. Captures only the twelve write routes.
"""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ROUTES = [
    ('K01', 'PUT', r'users/[^/]+'),
    ('K02', 'DELETE', r'messages/[^/]+'),
    ('K03', 'POST', r'listings/[^/]+/[^/]+/review'),
    ('K04', 'PUT', r'platform-settings'),
    ('K05', 'POST', r'topups/[^/]+/review'),
    ('K06', 'POST', r'topups/[^/]+/corrections'),
    ('K07', 'POST', r'reviews/[^/]+/moderate'),
    ('K08', 'POST', r'chat-reports/[^/]+/review'),
    ('K09', 'POST', r'disputes/[^/]+/resolve'),
    ('K10', 'POST', r'incidents/[^/]+/[^/]+/excuse'),
    ('K11', 'POST', r'work-queue/(support|listing|chat_report)/[^/]+'),
    ('K12', 'POST', r'work-queue/support/[^/]+/escalate'),
]
TESTS = [
    'test_api.ApiTests.test_roles_and_server_listings',
    'test_api.ApiTests.test_admin_block_and_unblock',
    'test_api.ApiTests.test_legacy_message_removal_is_reasoned_atomic_and_retry_does_not_duplicate_audit',
    'test_api.ApiTests.test_settings_audit_and_response_match_the_committed_version_during_a_second_write',
    'test_api.ApiTests.test_manual_topup_verification_idempotency_and_access',
    'test_api.ApiTests.test_wallet_clarification_preserves_evidence_and_blocks_stale_credit',
    'test_api.ApiTests.test_topup_corrections_admin_only_owner_history_and_pagination',
    'test_booking_http.BookingHttpTests.test_review_http_completed_ownership_public_projection_and_admin_gate',
    'test_chat_moderation.ChatModerationTests.test_dismiss_does_not_hide_message_and_review_requires_revision_reason',
    'test_chat_moderation.ChatModerationTests.test_parallel_moderation_redacts_old_pages_without_destroying_evidence',
    'test_booking_disputes.DisputeHttpTests.test_authenticated_routes_private_images_admin_decision_and_incident_history',
    'test_work_queue.WorkQueueTests.test_claim_reassign_retry_closed_history_and_client_privacy',
    'test_work_queue.WorkQueueTests.test_listing_work_uses_current_moderation_and_operator_role',
    'test_work_escalation.WorkEscalationTests.test_escalation_assigns_administrator_with_immutable_history_without_source_or_money_changes',
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--admin', type=Path, required=True)
    args = parser.parse_args()
    admin = args.admin.resolve()
    if not (admin / 'test_write_receipts.cjs').is_file():
        parser.error('Admin checkout must contain test_write_receipts.cjs')
    # Only allowlisted unittest fixtures are invoked, regardless of external flags.
    os.environ.pop('MOMIQ_INTEGRATION', None)
    import server
    captured = []
    original_body, original_reply = server.Handler.body, server.Handler.reply

    def body(handler):
        value = original_body(handler)
        handler._write_contract_body = json.loads(json.dumps(value))
        return value

    def reply(handler, status, value, cookie=None):
        path = handler.path.removeprefix('/api/admin/')
        if handler.path.startswith('/api/admin/') and 200 <= status < 300:
            for identity, method, pattern in ROUTES:
                if handler.command == method and re.fullmatch(pattern, path):
                    captured.append(json.loads(json.dumps({
                        'id': identity, 'path': path, 'method': method,
                        'body': handler._write_contract_body, 'data': value,
                    })))
                    break
        return original_reply(handler, status, value, cookie)

    suite = unittest.defaultTestLoader.loadTestsFromNames(TESTS)
    with patch.object(server.Handler, 'body', body), patch.object(server.Handler, 'reply', reply):
        result = unittest.TextTestRunner(verbosity=1).run(suite)
    if not result.wasSuccessful():
        return 1
    counts = Counter(row['id'] for row in captured)
    if set(counts) != {row[0] for row in ROUTES}:
        print('Missing route coverage:', sorted({row[0] for row in ROUTES} - set(counts)))
        return 1
    print('Synthetic HTTP receipts:', json.dumps(dict(sorted(counts.items()))), flush=True)
    with tempfile.TemporaryDirectory(prefix='momiq-write-contract-') as directory:
        fixture = Path(directory) / 'receipts.json'
        fixture.write_text(json.dumps(captured), encoding='utf-8')
        env = dict(os.environ, MOMIQ_WRITE_RECEIPTS=str(fixture))
        return subprocess.run(['node', '--test', 'test_write_receipts.cjs'], cwd=admin, env=env, timeout=60).returncode


if __name__ == '__main__':
    raise SystemExit(main())
