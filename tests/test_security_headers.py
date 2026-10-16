"""Заголовки FastAPI на API/SPA, документации, CORS и ответах с ошибками."""

import re
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from server.main import app
from server.api.v1.common import current_user
from server.security import content_security_policy


def directives(policy):
    return {parts[0]: parts[1:] for section in policy.split(";") if (parts := section.strip().split())}


class SecurityHeaderTests(unittest.TestCase):
    def setUp(self):
        # Без lifespan: проверки HTTP-заголовков не открывают рабочую БД.
        self.client = TestClient(app, raise_server_exceptions=False)
        self.addCleanup(self.client.close)

    def assert_security_headers(self, response):
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response.headers["X-Frame-Options"], "SAMEORIGIN")
        policy = directives(response.headers["Content-Security-Policy"])
        self.assertEqual(policy["default-src"], ["'self'"])
        self.assertEqual(policy["object-src"], ["'none'"])
        self.assertIn("https://st.max.ru", policy["script-src"])
        self.assertEqual(policy["frame-ancestors"], ["'self'", "https://max.ru", "https://web.max.ru"])
        self.assertNotIn("*", policy["script-src"])
        return policy

    def test_api_spa_and_schema_responses_are_protected(self):
        for path in ("/api/v1/health", "/", "/openapi.json"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                policy = self.assert_security_headers(response)
                self.assertNotIn("'unsafe-inline'", policy["script-src"])

        home = self.client.get("/")
        assets = re.findall(r'(?:src|href)="(/assets/[^"?#]+)', home.text)
        for asset in assets:
            with self.subTest(asset=asset):
                response = self.client.get(asset)
                self.assertEqual(response.status_code, 200)
                self.assert_security_headers(response)

    def test_documentation_has_its_own_cdn_and_initialization_exceptions(self):
        for path in ("/docs", "/redoc", "/docs/oauth2-redirect"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                policy = self.assert_security_headers(response)
                self.assertIn("https://cdn.jsdelivr.net", policy["script-src"])
                self.assertIn("'unsafe-inline'", policy["script-src"])
        policy = directives(self.client.get("/").headers["Content-Security-Policy"])
        self.assertNotIn("https://cdn.jsdelivr.net", policy["script-src"])

    def test_http_errors_and_unhandled_500_keep_headers_without_leaking_error(self):
        for status in (401, 403, 404, 422):
            def reject():
                raise HTTPException(status_code=status, detail="test error")

            with self.subTest(status=status), patch.dict(app.dependency_overrides, {current_user: reject}):
                response = self.client.get("/api/v1/me")
                self.assertEqual(response.status_code, status)
                self.assert_security_headers(response)

        def fail():
            raise RuntimeError("sensitive implementation details")

        with patch.dict(app.dependency_overrides, {current_user: fail}):
            response = self.client.get("/api/v1/me")
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json(), {"detail": "Internal Server Error"})
        self.assert_security_headers(response)

    def test_cors_preflight_also_has_security_headers(self):
        response = self.client.options("/api/v1/health", headers={
            "Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Access-Control-Allow-Origin"], "http://localhost:5173")
        self.assert_security_headers(response)

    def test_maps_exceptions_are_enabled_only_when_maps_are_configured(self):
        disabled = directives(content_security_policy(maps_enabled=False))
        enabled = directives(content_security_policy(maps_enabled=True))
        self.assertNotIn("'unsafe-eval'", disabled["script-src"])
        self.assertIn("'unsafe-eval'", enabled["script-src"])
        self.assertIn("https://api-maps.yandex.ru", enabled["script-src"])
        self.assertIn("https://yastatic.net", enabled["script-src"])
        self.assertIn("https://*.maps.yandex.net", enabled["connect-src"])
        self.assertIn("data:", enabled["worker-src"])
        self.assertIn("https://fonts.googleapis.com", enabled["style-src"])
        self.assertIn("https://fonts.gstatic.com", enabled["font-src"])


if __name__ == "__main__":
    unittest.main()
