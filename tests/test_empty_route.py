"""Первый шаг пустого маршрута должен быть доступен для выполнения."""

import importlib
import sys
import types
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from core.db.models import Base, Route, RouteStep, User
from core.schemas import StepAddIn


class EmptyRouteTests(unittest.TestCase):
    def test_first_step_in_empty_route_becomes_current(self):
        # В локальной тестовой среде reportlab может отсутствовать; этот endpoint PDF не использует.
        pdf_module = types.ModuleType("server.health_pdf")
        pdf_module.build_health_pdf = lambda *args, **kwargs: b""
        with patch.dict(sys.modules, {"server.health_pdf": pdf_module}):
            add_step = importlib.import_module("server.api.v1.api").add_step

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            user = User(max_user_id=301)
            db.add(user)
            db.flush()
            route = Route(user_id=user.id, situation_key="custom", title="My route")
            db.add(route)
            db.commit()

            first = add_step(StepAddIn(title="First"), after_step_id=None, user=user, db=db)
            self.assertEqual([(step.position, step.status) for step in first.steps], [(1, "current")])

            db.query(RouteStep).filter(RouteStep.route_id == route.id).update({"status": "done"})
            db.commit()
            second = add_step(StepAddIn(title="Second"), after_step_id=None, user=user, db=db)
            self.assertEqual(second.steps[-1].status, "current")
        engine.dispose()


if __name__ == "__main__":
    unittest.main()
