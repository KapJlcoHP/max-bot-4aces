"""Stage A initialization regressions, using isolated in-memory databases only."""

import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from core.db import demo, seed
from core.db.models import (
    Base, HealthRecord, HealthSetting, MedCourse, MedIntake, Organization,
    Reminder, Route, RouteStep, User,
)
from core.time import user_local


class SeedStageATests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")

        @event.listens_for(self.engine, "connect")
        def enable_foreign_keys(connection, _record):
            connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def user(self, **values):
        user = User(max_user_id=900000 + self.db.query(User).count(), **values)
        self.db.add(user)
        self.db.commit()
        return user

    def organizations(self):
        return {(org.region, org.title): org for org in self.db.query(Organization).all()}

    def snapshot(self):
        return {
            table.name: self.db.execute(select(table).order_by(table.c.id)).all()
            for table in Base.metadata.sorted_tables
        }

    def test_actual_catalog_has_21_rows_both_centers_and_stable_ids(self):
        expected = {
            (region["title"], item["title"]): item
            for region in seed.load_regions()
            for item in region["organizations"]
        }
        self.assertEqual(len(expected), 21)
        seed.seed_organizations(self.db)
        organizations = self.organizations()
        self.assertEqual(set(organizations), set(expected))
        center = "Областной перинатальный центр"
        for region in ("Владимирская область", "Ярославская область"):
            self.assertEqual(organizations[region, center].address, expected[region, center]["address"])
        clinic = next(org for org in organizations.values() if org.org_type == "Поликлиники")
        user = self.user(region=clinic.region, attached_clinic_id=clinic.id)
        ids = {key: org.id for key, org in organizations.items()}
        clinic.phone = "outdated"
        self.db.commit()

        seed.seed_organizations(self.db)
        seed.seed_organizations(self.db)

        self.assertEqual({key: org.id for key, org in self.organizations().items()}, ids)
        self.db.refresh(user)
        self.assertEqual(user.attached_clinic_id, clinic.id)
        self.assertEqual(clinic.phone, expected[clinic.region, clinic.title]["phone"])

    def test_catalog_does_not_keep_old_model_cards(self):
        titles = {item["title"] for region in seed.load_regions() for item in region["organizations"]}
        self.assertIn("Ивановская городская поликлиника №2", titles)
        self.assertIn("Городская клиническая больница №5 (ПО «Автоприбор» и «Точмаш»)", titles)
        self.assertIn("Республиканский клинический онкологический диспансер имени профессора М.З. Сигала", titles)
        self.assertNotIn("Городская поликлиника №12", titles)
        self.assertNotIn("ГКБ им. С.П. Боткина №3", titles)

    def test_old_title_collapsed_catalog_recovers_without_relocating_existing_ids(self):
        # This is exactly the former title-only seed's initial state (20 rows).
        collapsed = {
            item["title"]: {**item, "region": region["title"]}
            for region in seed.load_regions()
            for item in region["organizations"]
        }
        self.db.add_all(Organization(**item) for item in collapsed.values())
        self.db.commit()
        original = {key: org.id for key, org in self.organizations().items()}
        clinic = self.db.query(Organization).filter_by(org_type="Поликлиники").first()
        user = self.user(region=clinic.region, attached_clinic_id=clinic.id)

        seed.seed_organizations(self.db)

        current = self.organizations()
        self.assertEqual(len(current), 21)
        self.assertEqual({key: current[key].id for key in original}, original)
        self.assertIn(("Владимирская область", "Областной перинатальный центр"), current)
        self.db.refresh(user)
        self.assertEqual(user.attached_clinic_id, clinic.id)

    def test_duplicates_relink_only_valid_same_region_attachments_and_remove_obsolete(self):
        region = seed.load_regions()[0]
        item = {**region["organizations"][0], "region": region["title"]}
        canonical, duplicate = Organization(**item), Organization(**item)
        obsolete = Organization(**{**item, "title": "Удалённая поликлиника"})
        self.db.add_all([canonical, duplicate, obsolete])
        self.db.commit()
        canonical_id, duplicate_id, obsolete_id = canonical.id, duplicate.id, obsolete.id
        attached = self.user(region=canonical.region, attached_clinic_id=canonical_id)
        duplicate_user = self.user(region=canonical.region, attached_clinic_id=duplicate_id)
        foreign_user = self.user(region="Владимирская область", attached_clinic_id=duplicate_id)
        obsolete_user = self.user(region=canonical.region, attached_clinic_id=obsolete_id)

        seed.seed_organizations(self.db)

        self.assertEqual(self.db.query(Organization).count(), 21)
        self.assertIsNone(self.db.get(Organization, duplicate_id))
        self.assertIsNone(self.db.get(Organization, obsolete_id))
        for user in (attached, duplicate_user, foreign_user, obsolete_user):
            self.db.refresh(user)
        self.assertEqual(attached.attached_clinic_id, canonical_id)
        self.assertEqual(duplicate_user.attached_clinic_id, canonical_id)
        self.assertIsNone(foreign_user.attached_clinic_id)
        self.assertIsNone(obsolete_user.attached_clinic_id)

    def test_every_ordinary_template_is_unscheduled_and_action_content_is_retained(self):
        user = self.user()
        for key, scenario in seed.load_scenarios().items():
            with self.subTest(situation=key):
                route = seed.build_route_for(self.db, user, key)
                self.assertEqual(len(route.steps), len(scenario["steps"]))
                for step, spec in zip(route.steps, scenario["steps"]):
                    self.assertIsNone(step.deadline)
                    self.assertIsNone(step.deadline_time)
                    self.assertEqual(step.title, spec["title"])
                    unselected = "Поликлиника не выбрана — выберите в профиле"
                    self.assertEqual(step.description, spec.get("description", "").replace("{clinic}", unselected))
                    self.assertEqual(step.place, spec.get("place", "").replace("{clinic}", unselected))
                    self.assertEqual(step.source_id, spec.get("source_id"))

    def test_custom_dates_and_existing_route_dates_survive_new_route_and_seed(self):
        user = self.user()
        deadline = date(2031, 4, 5)
        first = seed.build_route_for(self.db, user, "chronic", custom_steps=[
            {"title": "My visit", "deadline": deadline, "deadline_time": "13:25"},
            {"title": "Legacy clock", "deadline": deadline, "time": "14:15"},
        ])
        user_steps = [step for step in first.steps if step.source == "user"]
        self.assertEqual([(step.deadline, step.deadline_time) for step in user_steps],
                         [(deadline, "13:25"), (deadline, "14:15")])
        template = first.steps[0]
        template.deadline, template.deadline_time = deadline, "17:20"
        self.db.commit()

        custom = seed.build_route_for(self.db, user, "custom", custom_steps=[
            {"title": "Own route", "deadline": deadline, "deadline_time": "16:30"},
        ])
        seed.seed_organizations(self.db)
        seed.refresh_route_clinic(self.db, user, first)
        self.db.commit()
        self.db.refresh(template)
        self.assertEqual((template.deadline, template.deadline_time), (deadline, "17:20"))
        self.assertEqual((custom.steps[0].deadline, custom.steps[0].deadline_time), (deadline, "16:30"))

    def assert_demo_day(self, user, today):
        route = self.db.query(Route).filter_by(user_id=user.id).one()
        days_ago = [33, 33, 32, 31, 7, 6, 5, -7]
        self.assertEqual(len(route.steps), len(days_ago))
        for index, (step, days) in enumerate(zip(route.steps, days_ago)):
            self.assertEqual(step.deadline, today - timedelta(days=days))
            self.assertEqual(step.deadline_time, "10:00" if index in (3, 7) else None)
        for step, days in zip(route.steps[:-1], days_ago):
            self.assertEqual(user_local(step.completed_at, user.tz).date(),
                             today - timedelta(days=days))
        self.assertEqual(route.steps[-1].status, "current")
        self.assertIsNone(route.steps[-1].completed_at)
        records = self.db.query(HealthRecord).filter_by(user_id=user.id).all()
        self.assertEqual(max(user_local(row.at, user.tz).date() for row in records), today - timedelta(days=1))
        courses = self.db.query(MedCourse).filter_by(user_id=user.id).all()
        self.assertEqual({row.until for row in courses}, {today + timedelta(days=27)})
        self.assertEqual({user_local(row.created_at, user.tz).date() for row in courses},
                          {today - timedelta(days=30)})
        intakes = self.db.query(MedIntake).filter_by(user_id=user.id).all()
        self.assertEqual(max(row.day for row in intakes), today - timedelta(days=1))
        for row in intakes:
            local = user_local(row.taken_at, user.tz)
            self.assertEqual((local.date(), local.strftime("%H:%M")), (row.day, row.at_time))
        reminders = self.db.query(Reminder).filter_by(user_id=user.id).order_by(Reminder.id).all()
        self.assertEqual([(user_local(row.at, user.tz).date(), user_local(row.at, user.tz).strftime("%H:%M"))
                          for row in reminders],
                         [(today + timedelta(days=6), "10:00"), (today + timedelta(days=12), "09:00")])

    def test_demo_uses_invocation_local_date_across_midnight_and_timezones(self):
        # UTC stays on the same day while Tokyo crosses midnight between calls.
        cases = [
            (datetime(2031, 5, 2, 14, 59, tzinfo=timezone.utc), "Asia/Tokyo", date(2031, 5, 2)),
            (datetime(2031, 5, 2, 15, 1, tzinfo=timezone.utc), "Asia/Tokyo", date(2031, 5, 3)),
            (datetime(2031, 5, 2, 15, 1, tzinfo=timezone.utc), "America/Los_Angeles", date(2031, 5, 2)),
        ]
        for instant, tz, expected in cases:
            with self.subTest(instant=instant, tz=tz):
                user = self.user(tz=tz)
                with patch.object(demo, "datetime", wraps=datetime) as clock:
                    clock.now.side_effect = lambda zone: instant.astimezone(zone)
                    demo.fill_demo(self.db, user)
                self.assert_demo_day(user, expected)

    def test_repeated_demo_keeps_ids_dates_settings_and_user_additions(self):
        user = self.user(tz="Asia/Tokyo")
        setting = HealthSetting(user_id=user.id, diary="bp", enabled=False, push_time="11:45")
        self.db.add(setting)
        self.db.commit()
        with patch.object(demo, "datetime", wraps=datetime) as clock:
            clock.now.side_effect = lambda zone: datetime(2031, 5, 2, 14, 59, tzinfo=timezone.utc).astimezone(zone)
            demo.fill_demo(self.db, user)
        initial = self.snapshot()
        with patch.object(demo, "datetime", wraps=datetime) as clock:
            clock.now.side_effect = lambda zone: datetime(2031, 5, 4, 18, tzinfo=timezone.utc).astimezone(zone)
            demo.fill_demo(self.db, user)
        self.assertEqual(self.snapshot(), initial)
        self.db.refresh(setting)
        self.assertEqual((setting.enabled, setting.push_time), (False, "11:45"))

        self.db.add(HealthRecord(user_id=user.id, type="weight", at=datetime(2031, 5, 4), weight_kg=73))
        self.db.commit()
        with_addition = self.snapshot()
        with self.assertRaises(ValueError):
            demo.fill_demo(self.db, user)
        self.assertEqual(self.snapshot(), with_addition)

    def test_demo_refuses_existing_ordinary_route_without_modification(self):
        user = self.user()
        seed.build_route_for(self.db, user, "doctor")
        initial = self.snapshot()
        with self.assertRaises(ValueError):
            demo.fill_demo(self.db, user)
        self.assertEqual(self.snapshot(), initial)


if __name__ == "__main__":
    unittest.main()
