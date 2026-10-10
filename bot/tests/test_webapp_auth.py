import time
import urllib.parse
import unittest

from webapp_auth import validate_init_data


class WebAppAuthTests(unittest.TestCase):
    def _vector(self, age=0):
        bot_token = "123456:TEST"
        user = '{"id":123,"first_name":"Test"}'
        pairs = {
            "query_id": "AAETEST",
            "user": user,
            "auth_date": str(int(time.time()) - age),
        }
        check = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
        import hashlib
        import hmac
        secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        digest = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
        pairs["hash"] = digest
        return bot_token, urllib.parse.urlencode(pairs)

    def test_accepts_valid_recent_init_data(self):
        token, value = self._vector()
        # P0: Was only assertIsNotNone — never verified the returned identity.
        # A truthy non-dict (True, tuple) would pass and break downstream.
        result = validate_init_data(value, token, max_age_seconds=60)
        self.assertIsNotNone(result)
        self.assertIsInstance(result, dict)
        self.assertIn("user", result)
        self.assertIsInstance(result["user"], dict)
        self.assertIn("id", result["user"])

    def test_rejects_bad_hash(self):
        token, value = self._vector()
        value = value.replace("AAETEST", "AAEBAD")
        self.assertIsNone(validate_init_data(value, token, max_age_seconds=60))

    def test_rejects_stale_data(self):
        token, value = self._vector(age=120)
        self.assertIsNone(validate_init_data(value, token, max_age_seconds=60))

    def test_rejects_missing_hash(self):
        token, value = self._vector()
        value = urllib.parse.urlencode(
            [(k, v) for k, v in urllib.parse.parse_qsl(value) if k != "hash"]
        )
        self.assertIsNone(validate_init_data(value, token, max_age_seconds=60))
