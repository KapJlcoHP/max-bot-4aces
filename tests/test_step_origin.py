"""Происхождение шага сохраняется во всех ответах API с StepDto."""

import unittest
from datetime import date, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from core.db.models import Base, Route, RouteStep, User
from core.schemas import CustomStepIn, RouteStartIn, StepAddIn, StepUpdateIn
from server.api.v1 import api


class StepOriginTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.user = User(max_user_id=760001, consent_at=datetime(2026, 1, 1))
        self.db.add(self.user)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_template_explanation_uses_selected_catalog_title(self):
        route = api.start_route(RouteStartIn(situation_key="chronic"), user=self.user, db=self.db)
        for step in route.steps:
            self.assertEqual(step.source, "template")
            self.assertIn("«Наблюдаться по хроническому»", step.reason)
            self.assertIn("вы выбрали", step.reason)
        loaded = api.get_route(user=self.user, db=self.db)
        self.assertEqual(loaded.model_dump()["steps"][0]["reason"], route.steps[0].reason)

    def test_doctor_and_user_steps_explain_manual_input_even_inside_template(self):
        route = api.start_route(
            RouteStartIn(situation_key="chronic", custom_steps=[CustomStepIn(title="Мой пункт")]),
            user=self.user, db=self.db,
        )
        own = next(step for step in route.steps if step.source == "user")
        self.assertEqual(own.reason, "Ваш шаг — добавлен вами в маршрут.")
        route = api.add_step(
            StepAddIn(title="Назначение", source="doctor"), after_step_id=route.steps[0].id,
            user=self.user, db=self.db,
        )
        doctor = next(step for step in route.steps if step.source == "doctor")
        self.assertEqual(doctor.reason, "Назначение врача — внесено вами.")
        self.assertNotIn("шаблон", doctor.reason)

    def test_completion_next_step_and_deadline_update_include_reason(self):
        route = api.start_route(RouteStartIn(situation_key="chronic"), user=self.user, db=self.db)
        current = route.steps[0]
        updated = api.update_step(
            current.id, StepUpdateIn(deadline=date(2026, 10, 20)), user=self.user, db=self.db,
        )
        self.assertEqual(updated.reason, current.reason)
        result = api.complete_step(current.id, body=None, user=self.user, db=self.db)
        self.assertEqual(result.step.reason, current.reason)
        self.assertEqual(result.route.steps[0].reason, current.reason)
        self.assertIsNotNone(result.next_step)
        self.assertEqual(result.next_step.reason, route.steps[1].reason)
        undone = api.uncomplete_step(current.id, user=self.user, db=self.db)
        self.assertEqual(undone.steps[0].reason, current.reason)

    def test_legacy_template_uses_stored_route_title_and_unknown_source_is_not_guessed(self):
        route = Route(user_id=self.user.id, situation_key="retired", title="Старый маршрут")
        self.db.add(route)
        self.db.flush()
        self.db.add_all([
            RouteStep(route_id=route.id, position=1, title="Первый", source="template", status="current"),
            RouteStep(route_id=route.id, position=2, title="Второй", source="legacy"),
        ])
        self.db.commit()
        dto = api.get_route(user=self.user, db=self.db)
        self.assertIn("«Старый маршрут»", dto.steps[0].reason)
        self.assertEqual(dto.steps[1].reason, "Происхождение этого шага не указано.")


if __name__ == "__main__":
    unittest.main()
