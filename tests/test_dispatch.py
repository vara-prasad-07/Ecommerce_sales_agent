import unittest

from agent.dispatch import DispatchError, normalize_phone_number


class NormalizePhoneNumberTests(unittest.TestCase):
    def test_already_e164(self):
        self.assertEqual(normalize_phone_number("+919876543210"), "+919876543210")

    def test_adds_missing_plus(self):
        self.assertEqual(normalize_phone_number("919876543210"), "+919876543210")

    def test_strips_spaces_and_dashes(self):
        self.assertEqual(normalize_phone_number("+91 98765-43210"), "+919876543210")

    def test_strips_parentheses(self):
        self.assertEqual(normalize_phone_number("+1 (415) 555-2671"), "+14155552671")

    def test_rejects_too_short(self):
        with self.assertRaises(DispatchError):
            normalize_phone_number("+911234")

    def test_rejects_empty(self):
        with self.assertRaises(DispatchError):
            normalize_phone_number("")

    def test_rejects_leading_zero_country_code(self):
        with self.assertRaises(DispatchError):
            normalize_phone_number("+0123456789")

    def test_rejects_letters(self):
        with self.assertRaises(DispatchError):
            normalize_phone_number("+91abcdefghij")


if __name__ == "__main__":
    unittest.main()
