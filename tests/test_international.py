"""Raw hook retrieval over original and localized skill metadata."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest

from orchestrator.cli import _hook_run
from orchestrator.evaluate import evaluate, load_cases, load_target
from orchestrator.retrieval import retrieve
from orchestrator.search import fold, query_units, tokenize
from tests.helpers import skill, write


FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "eval")

# A billing task outside the six parallel audit families, and distractors that
# share one domain term. These are authored regression cases, not a blind test.
BILLING = {
    "en": ("Track invoice payments", "Paint an invoice on a teapot"),
    "es": ("Conciliar el pago de la factura", "Pintar una factura en la tetera"),
    "pt": ("Conciliar o pagamento da fatura", "Desenhar uma fatura no bule"),
    "fr": ("Rapprocher le paiement et la facture", "Peindre une facture sur la théière"),
    "de": ("Rechnung und Zahlung abgleichen", "Eine Rechnung auf die Teekanne malen"),
    "ru": ("Сверить счёт и оплату", "Нарисовать счёт на чайнике"),
    "ar": ("مطابقة الفاتورة مع الدفع", "ارسم الفاتورة على إبريق الشاي"),
    "hi": ("चालान का भुगतान मिलाएँ", "चायदानी पर चालान बनाएँ"),
    "zh": ("核对发票和付款记录", "在茶壶上画发票"),
    "ja": ("請求書と支払いを照合する", "ティーポットに請求書を描く"),
    "ko": ("청구서와 결제를 대조해 주세요", "찻주전자에 청구서를 그려 주세요"),
    "sw": ("Linganisha ankara na malipo", "Chora ankara kwenye birika"),
}


class InternationalTests(unittest.TestCase):
    def test_parallel_audit_hits_every_cohort(self):
        loaded = load_target(os.path.join(FIXTURE, "config.json"))
        cases = load_cases(os.path.join(FIXTURE, "audit_languages.json"))
        for row in evaluate(cases, loaded, _hook_run)["rows"]:
            with self.subTest(case=row["id"]):
                self.assertTrue(row["hit_at_3"], row)

    def test_billing_in_each_language_and_one_term_distractors(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill(tmp, "skills/ledger", "ledger", "Reconcile invoice payments and receipts.")
            for i in range(8):
                skill(tmp, "skills/plant-%d" % i, "plant-%d" % i, "Tropical foliage and garden soil.")
            path = write(tmp, "config.json", '{"extra_roots":["skills"],"use_platform_roots":false,'
                         '"use_cwd_project_roots":false}')
            loaded = load_target(path)
            for lang, (positive, negative) in BILLING.items():
                with self.subTest(language=lang):
                    ids, _ = _hook_run({"prompt": positive}, loaded)
                    self.assertTrue(ids and ids[0].endswith("/ledger"), ids)
                    self.assertEqual(_hook_run({"prompt": negative}, loaded)[0], [])

    def test_localized_metadata_matches_across_scripts_and_via_tags(self):
        pool = [{"id": "books", "name": "請求書照合", "description": "支払いを確認"},
                {"id": "wine", "name": "cellar", "tags": ["vignoble", "barrique"]},
                {"id": "tool", "name": "SQLite", "description": "数据库备份"}]
        for query, expected in (("invoice payment", "books"), ("paiement facture", "books"),
                                ("vignoble barrique", "wine"), ("SQLiteのバックアップ", "tool")):
            with self.subTest(query=query):
                self.assertEqual([r["entry"]["id"] for r in retrieve(pool, [query])], [expected])

    def test_english_query_over_native_descriptions_for_every_cohort(self):
        for language, (description, _negative) in BILLING.items():
            with self.subTest(language=language), tempfile.TemporaryDirectory() as tmp:
                skill(tmp, "lib/bookkeeper", "LedgerPro", description)
                skill(tmp, "lib/pottery", "pottery", "Hand-painted ceramics and collectible iron teapots.")
                cfg = write(tmp, "config.json", '{"extra_roots":["lib"],"use_platform_roots":false,'
                            '"use_cwd_project_roots":false}')
                loaded = load_target(cfg)
                ids, _ = _hook_run({"prompt": "Which invoice payments need reconciling?"}, loaded)
                self.assertTrue(ids and ids[0].endswith("/LedgerPro"), ids)
                native = next(e for e in loaded[1]["entries"] if e["name"] == "LedgerPro")
                self.assertEqual(native["description"], description)

    def test_domain_terms_compose_without_a_predefined_intent_or_skill_id(self):
        entries = [{"id": "atlas", "name": "atlas", "description": "Diagram the database."},
                   {"id": "vault", "name": "vault", "description": "Restore the database."},
                   {"id": "links", "name": "links", "description": "Diagram service connections."}]
        entries.extend({"id": "plant-%d" % i, "name": "plant-%d" % i, "description": "Water tropical foliage."}
                       for i in range(20))
        for query in ("database diagram", "un schéma de la base de données", "数据库的图表", "データベースの構成図",
                      "Datenbank als Diagramm", "mchoro wa hifadhidata"):
            with self.subTest(query=query):
                self.assertEqual([r["entry"]["id"] for r in retrieve(entries, [query])], ["atlas"])

    def test_particles_do_not_break_a_multiword_alias(self):
        self.assertIn("prospect", tokenize("잠재 고객에게"))
        self.assertEqual(len(query_units("請求書 facture Rechnung")), 1)

    def test_browser_diagnostics_and_regional_spanish_vocabulary(self):
        loaded = load_target(os.path.join(FIXTURE, "config.json"))
        for query, ident in (
                ("診断用にブラウザのコンソールを開く", "eng-skills/browser-devtools-testing"),
                ("kagua konsoli ya kivinjari", "eng-skills/browser-devtools-testing"),
                ("افتح وحدة التحكم في المتصفح", "eng-skills/browser-devtools-testing"),
                ("recuperar un respaldo del servidor", "ops-skills/backup-restore"),
                ("estimar margen y punto de equilibrio", "biz-skills/financial-model")):
            with self.subTest(query=query):
                ids, _ = _hook_run({"prompt": query}, loaded)
                self.assertTrue(ids and ids[0] == ident, ids)

    def test_cached_tokenizer_fingerprint_is_stable_across_interpreters(self):
        command = [sys.executable, "-B", "-c", "from orchestrator.search import tokenizer_id; print(tokenizer_id())"]
        ids = {subprocess.check_output(command, cwd=os.path.dirname(os.path.dirname(__file__)),
                                       env=dict(os.environ, PYTHONHASHSEED=str(seed)), text=True).strip()
               for seed in (7, 521)}
        self.assertEqual(len(ids), 1)

    def test_combining_marks_and_names_survive_script_changes(self):
        self.assertNotEqual(tokenize("दिन"), tokenize("दीन"))
        self.assertNotEqual(tokenize("がく"), tokenize("かく"))
        self.assertEqual(fold("가"), "가")
        self.assertIn("sqlite", tokenize("在SQLite中"))
        self.assertIn("postgresql", tokenize("PostgreSQLを確認"))
