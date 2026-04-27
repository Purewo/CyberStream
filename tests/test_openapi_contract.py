from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

from tests.path_cleaner_test_utils import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app import create_app


OPENAPI_PATH = PROJECT_ROOT / "backend/openapi/openapi-1.17.0-beta/openapi-1.17.0-beta.json"
HTTP_METHODS = {"GET", "POST", "PATCH", "PUT", "DELETE"}


def _flask_rule_to_openapi_path(rule):
    return re.sub(r"<(?:[^:<>]+:)?([^<>]+)>", r"{\1}", rule)


class OpenApiContractTests(unittest.TestCase):
    def test_openapi_paths_match_registered_runtime_routes(self):
        app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        })
        runtime_operations = set()
        for rule in app.url_map.iter_rules():
            if rule.endpoint == "static":
                continue
            path = _flask_rule_to_openapi_path(rule.rule)
            for method in rule.methods:
                if method in HTTP_METHODS:
                    runtime_operations.add((path, method))

        openapi = json.loads(OPENAPI_PATH.read_text())
        documented_operations = {
            (path, method.upper())
            for path, path_item in openapi["paths"].items()
            for method in path_item.keys()
            if method.upper() in HTTP_METHODS
        }

        self.assertEqual(set(), runtime_operations - documented_operations)
        self.assertEqual(set(), documented_operations - runtime_operations)


if __name__ == "__main__":
    unittest.main()
