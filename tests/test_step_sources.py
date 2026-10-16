"""Источники шаблонов, редакционные метаданные и обновление старых маршрутов."""

import json
import unittest
from datetime import date, datetime
from unittest.mock import patch

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from core.db.models import Base, Route, RouteStep, User
from core.db.seed import CONTENT_DIR, load_catalog, load_scenarios, load_sources
from core.db.session import _migrate_sqlite
from core.schemas import ContentSourceDto, CustomStepIn, RouteStartIn, StepAddIn, StepUpdateIn
from server.api.v1 import api


class StepSourceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.user = User(max_user_id=770001, consent_at=datetime(2026, 1, 1))
        self.db.add(self.user)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_every_template_step_references_a_valid_source_without_invented_review(self):
        sources = load_sources()
        raw = json.loads((CONTENT_DIR / "sources.json").read_text(encoding="utf-8"))["sources"]
        self.assertEqual(len(sources), len(raw))
        for source in sources.values():
            dto = ContentSourceDto.model_validate(source)
            self.assertEqual(dto.url.scheme, "https")
            self.assertTrue(dto.title)
            self.assertTrue(dto.scope)
            self.assertEqual(dto.checked_at.isoformat() if dto.checked_at else None, source["checked_at"])
            self.assertEqual(dto.checked_by, source["checked_by"])
            self.assertEqual(dto.checked_where, source["checked_where"])
        for scenario in load_scenarios().values():
            for step in scenario["steps"]:
                self.assertIn(step["source_id"], sources)

    def test_all_available_routes_return_sources_for_every_template_step(self):
        sources = load_sources()
        for situation in load_catalog():
            with self.subTest(situation=situation["key"]):
                route = api.start_route(
                    RouteStartIn(situation_key=situation["key"]), user=self.user, db=self.db,
                )
                for step in route.steps:
                    self.assertIsNotNone(step.source_info)
                    self.assertEqual(step.source_info.id, step.source_id)
                    self.assertEqual(str(step.source_info.url), sources[step.source_id]["url"])
                    stored = self.db.get(RouteStep, step.id)
                    self.assertEqual(stored.source_id, step.source_id)

    def test_reordering_and_status_changes_preserve_source(self):
        route = api.start_route(
            RouteStartIn(situation_key="chronic", exclude_positions=[1]), user=self.user, db=self.db,
        )
        current = route.steps[0]
        spec = load_scenarios()["chronic"]["steps"][1]
        self.assertEqual(current.source_id, spec["source_id"])
        api.add_step(
            StepAddIn(title="Назначение", source="doctor"), after_step_id=current.id,
            user=self.user, db=self.db,
        )
        changed = api.update_step(
            current.id, StepUpdateIn(deadline=date(2026, 10, 20)), user=self.user, db=self.db,
        )
        self.assertEqual(changed.source_info, current.source_info)
        completed = api.complete_step(current.id, body=None, user=self.user, db=self.db)
        self.assertEqual(completed.step.source_info, current.source_info)
        undone = api.uncomplete_step(current.id, user=self.user, db=self.db)
        self.assertEqual(undone.steps[0].source_info, current.source_info)

    def test_manual_steps_do_not_inherit_an_official_source(self):
        route = api.start_route(
            RouteStartIn(situation_key="chronic", custom_steps=[CustomStepIn(title="Свой шаг")]),
            user=self.user, db=self.db,
        )
        route = api.add_step(
            StepAddIn(title="Назначение", source="doctor"), after_step_id=route.steps[0].id,
            user=self.user, db=self.db,
        )
        for step in route.steps:
            if step.source != "template":
                self.assertIsNone(step.source_id)
                self.assertIsNone(step.source_info)

    def test_editorial_review_metadata_is_read_from_registry(self):
        route = api.start_route(RouteStartIn(situation_key="chronic"), user=self.user, db=self.db)
        source_id = route.steps[0].source_id
        sources = load_sources()
        sources[source_id].update(
            checked_at="2026-09-20", checked_by="Тестовый редактор", checked_where="Тестовая сверка",
        )
        with patch("server.api.v1.common.load_sources", return_value=sources):
            refreshed = api.get_route(user=self.user, db=self.db)
        info = refreshed.steps[0].source_info.model_dump(mode="json")
        self.assertEqual(info["checked_at"], "2026-09-20")
        self.assertEqual(info["checked_by"], "Тестовый редактор")
        self.assertEqual(info["checked_where"], "Тестовая сверка")

    def test_migration_adds_column_and_matches_legacy_steps_by_title_not_position(self):
        spec = load_scenarios()["chronic"]["steps"][2]
        route = Route(user_id=self.user.id, situation_key="chronic", title="Старый маршрут")
        self.db.add(route)
        self.db.flush()
        matched = RouteStep(
            route_id=route.id, position=1, title=spec["title"], source="template", status="done",
        )
        manual = RouteStep(route_id=route.id, position=2, title=spec["title"], source="doctor")
        unknown = RouteStep(route_id=route.id, position=3, title="Неизвестный старый шаг", source="template")
        self.db.add_all([matched, manual, unknown])
        self.db.commit()
        matched_id, manual_id, unknown_id = matched.id, manual.id, unknown.id
        with self.engine.begin() as conn:
            conn.exec_driver_sql("ALTER TABLE route_steps DROP COLUMN source_id")
        with patch("core.db.session.engine", self.engine):
            _migrate_sqlite()
            _migrate_sqlite()
        self.assertIn("source_id", {column["name"] for column in inspect(self.engine).get_columns("route_steps")})
        self.db.expire_all()
        self.assertEqual(self.db.get(RouteStep, matched_id).source_id, spec["source_id"])
        self.assertEqual(self.db.get(RouteStep, matched_id).status, "done")
        self.assertIsNone(self.db.get(RouteStep, manual_id).source_id)
        self.assertIsNone(self.db.get(RouteStep, unknown_id).source_id)


if __name__ == "__main__":
    unittest.main()
