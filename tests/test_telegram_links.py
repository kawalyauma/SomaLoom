import unittest
from services.ingestion.telegram_links import TelegramLinkError, normalize_link


class TelegramLinkBoundaryTests(unittest.TestCase):
    def test_group_and_post_links_resolve_to_the_group(self):
        for link in ['https://t.me/TeacherInUganda','https://t.me/TeacherInUganda/123','https://t.me/s/TeacherInUganda/123','https://telegram.me/TeacherInUganda?single=1']:
            self.assertEqual(normalize_link(link), 'https://t.me/TeacherInUganda')

    def test_private_invite_forms_are_normalized(self):
        self.assertEqual(normalize_link('https://t.me/joinchat/Abcd_12345678'), 'https://t.me/+Abcd_12345678')
        self.assertEqual(normalize_link('https://t.me/+Abcd_12345678'), 'https://t.me/+Abcd_12345678')

    def test_numeric_ids_and_arbitrary_network_targets_are_rejected(self):
        for link in ['-1001234567','http://t.me/TeacherInUganda','https://127.0.0.1/TeacherInUganda','https://t.me.evil.example/TeacherInUganda','https://t.me@evil.example/TeacherInUganda','https://evil.example@t.me/TeacherInUganda','https://t.me:8443/TeacherInUganda','https://t.me/c/123/456','https://t.me/proxy?server=127.0.0.1','https://t.me/TeacherInUganda/../../admin','https://t.me/']:
            with self.subTest(link=link), self.assertRaises(TelegramLinkError):
                normalize_link(link)
