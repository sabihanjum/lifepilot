import asyncio
import os
import tempfile
import unittest
import gc

import main


class LifePilotAgentTests(unittest.TestCase):
    def setUp(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.db_path = path
        main.DB_PATH = path
        main.init_db()
        main.workflows.clear()
        main.calendar_events.clear()

    def tearDown(self):
        gc.collect()
        try:
            os.unlink(self.db_path)
        except PermissionError:
            pass

    def chat(self, message, conversation_id=None, user_id="test-user"):
        request = main.ChatRequest(
            message=message,
            conversation_id=conversation_id,
            user_id=user_id,
        )
        return asyncio.run(main.chat(request))

    def test_coorg_trip_does_not_route_to_mysuru_or_book(self):
        result = self.chat(
            "Plan a 2-day trip to Coorg for 2 people under ₹10,000. "
            "Find accommodation, suggest places to visit, calculate the budget, "
            "and save it in My Trips. Don't book anything."
        )
        reply = result["reply"]
        workflow = result["workflow"]
        itinerary = workflow["itinerary"]
        self.assertEqual(itinerary["destination"], "Coorg")
        self.assertEqual(itinerary["days"], 2)
        self.assertEqual(itinerary["people"], 2)
        self.assertNotIn("Mysuru", reply)
        self.assertFalse(itinerary["booking_allowed"])
        self.assertEqual(itinerary["status"], "saved")
        self.assertIn("trip_id", itinerary)
        self.assertFalse(workflow["approval_required"] if "approval_required" in workflow else False)

    def test_calendar_request_creates_two_separate_events_only(self):
        result = self.chat(
            "Schedule 2 hours of AI learning tomorrow morning and "
            "1 hour for job applications in the afternoon."
        )
        workflow = result["workflow"]
        self.assertEqual(len(workflow["calendar_events"]), 2)
        self.assertIsNone(workflow["itinerary"])
        self.assertTrue(workflow["calendar_events"][0]["title"] == "AI learning")
        self.assertTrue(workflow["calendar_events"][1]["title"] == "Job applications")

    def test_memory_persists_and_is_applied_to_trip(self):
        memory = self.chat(
            "Remember that I prefer budget travel, nature, quiet places, "
            "and vegetarian food."
        )
        self.assertEqual(memory["workflow"]["status"], "memory_updated")
        saved = main.get_preferences("test-user")
        self.assertTrue(saved["travel_preferences"]["budget_friendly"])
        self.assertTrue(saved["travel_preferences"]["nature"])
        self.assertTrue(saved["travel_preferences"]["quiet_places"])
        self.assertEqual(saved["travel_preferences"]["food_preference"], "vegetarian")

        trip = self.chat("Plan a 2-day trip to Coorg under ₹8000.")
        itinerary = trip["workflow"]["itinerary"]
        self.assertTrue(
            itinerary["preferences_applied"]["travel_preferences"]["budget_friendly"]
        )

    def test_confirmation_without_pending_action_is_safe(self):
        result = self.chat("Yes, proceed.", conversation_id="isolated-conversation")
        self.assertIn("no pending action", result["reply"].lower())
        self.assertFalse(result["approval_required"])

    def test_stale_pending_action_does_not_leak_between_sessions(self):
        first = self.chat(
            "Plan a 2-day trip to Coorg under ₹10000",
            conversation_id="conversation-a",
        )
        first_id = first["conversation_id"]
        result = self.chat("Yes, proceed.", conversation_id="conversation-b")
        self.assertNotIn("LP-", result["reply"])
        self.assertIn("no pending action", result["reply"].lower())
        self.assertNotEqual(first_id, "conversation-b")

    def test_different_consecutive_requests_return_different_responses(self):
        trip = self.chat("Plan a weekend trip to Coorg")
        calendar = self.chat(
            "Schedule 2 hours of AI learning tomorrow morning",
            conversation_id=trip["conversation_id"],
        )
        memory = self.chat(
            "Remember that I prefer vegetarian food",
            conversation_id=trip["conversation_id"],
        )
        self.assertIn("Coorg", trip["reply"])
        self.assertIn("calendar", calendar["reply"].lower())
        self.assertIn("Saved", memory["reply"])

    def test_hardcoded_mysuru_response_is_not_general_fallback(self):
        result = self.chat("Tell me a fun fact")
        self.assertNotIn("Mysuru", result["reply"])
        self.assertNotIn("Express train", result["reply"])
        self.assertNotIn("₹2,200", result["reply"])

    def test_rainy_coorg_revision_preserves_context_and_updates_without_duplicate(self):
        initial = self.chat(
            "Plan a 2-day trip to Coorg for 2 people under ₹10000. "
            "Save it to My Trips. Don't book anything.",
            conversation_id="coorg-context",
            user_id="rain-user",
        )
        trip_id = initial["workflow"]["itinerary"]["trip_id"]
        revised = self.chat(
            "It is raining in Coorg. Replace outdoor activities with indoor or covered "
            "alternatives and revise the itinerary while keeping the ₹10000 budget.",
            conversation_id="coorg-context",
            user_id="rain-user",
        )
        trip = revised["workflow"]["itinerary"]
        self.assertEqual(trip["trip_id"], trip_id)
        self.assertEqual(trip["destination"], "Coorg")
        self.assertEqual(trip["people"], 2)
        self.assertEqual(trip["days"], 2)
        self.assertEqual(trip["budget"], 10000)
        self.assertIn("indoor", " ".join(trip["day_1"]).lower())
        self.assertNotIn("Abbey Falls", " ".join(trip["day_1"] + trip["day_2"]))
        self.assertLessEqual(trip["estimate"]["total"], trip["budget"])
        self.assertEqual(trip["estimate"]["remaining"], trip["budget"] - trip["estimate"]["total"])
        rows = main.get_latest_trip("coorg-context", "Coorg")
        self.assertEqual(rows["trip_id"], trip_id)

    def test_packing_reminder_is_new_30_minute_event_and_preserves_existing_events(self):
        first = self.chat(
            "Schedule 2 hours of AI learning tomorrow morning and "
            "1 hour for job applications in the afternoon.",
            conversation_id="calendar-context",
        )
        existing = first["workflow"]["calendar_events"]
        second = self.chat(
            "Schedule a 30-minute packing reminder tomorrow evening.",
            conversation_id="calendar-context",
        )
        events = second["workflow"]["calendar_events"]
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event["title"], "Packing reminder")
        start = main.datetime.fromisoformat(event["start"])
        end = main.datetime.fromisoformat(event["end"])
        self.assertEqual((end - start).total_seconds(), 1800)
        self.assertEqual(start.hour, 18)
        listed = main.list_calendar_events()
        titles = {item["title"] for item in listed}
        self.assertIn("Packing reminder", titles)
        self.assertIn("AI learning", titles)
        self.assertIn("Job applications", titles)
        self.assertGreaterEqual(len(existing), 2)

    def test_multiple_calendar_requests_use_independent_results(self):
        one = self.chat("Schedule packing tomorrow evening", conversation_id="multi-calendar")
        two = self.chat("Schedule 30 minutes of resume review tomorrow morning", conversation_id="multi-calendar")
        self.assertEqual(one["workflow"]["calendar_events"][0]["title"], "Packing reminder")
        self.assertEqual(two["workflow"]["calendar_events"][0]["title"], "Calendar reminder")

    def test_calendar_creation_failure_is_not_reported_as_success(self):
        original = main.save_calendar_event
        main.save_calendar_event = lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("calendar unavailable"))
        try:
            result = self.chat("Schedule a 30-minute packing reminder tomorrow evening")
        finally:
            main.save_calendar_event = original
        self.assertIn("calendar event creation failed", result["reply"].lower())
        self.assertEqual(result["workflow"]["status"], "failed")
        self.assertNotIn("Created", result["reply"])

    def test_trip_budget_is_mathematically_correct_and_within_limit(self):
        result = self.chat("Plan a 2-day trip to Coorg for 2 people under ₹8000.")
        trip = result["workflow"]["itinerary"]
        estimate = trip["estimate"]
        category_keys = [
            "transportation_amount",
            "stay_amount",
            "food_amount",
            "activities_amount",
        ]
        calculated = sum(estimate[key] for key in category_keys)
        self.assertEqual(estimate["total"], calculated)
        self.assertLessEqual(estimate["total"], trip["budget"])
        self.assertEqual(estimate["remaining"], trip["budget"] - estimate["total"])

    def test_agora_generated_uids_are_unique_and_not_fixed_defaults(self):
        first_agent, first_remote = main.generate_agora_uids()
        second_agent, second_remote = main.generate_agora_uids()
        self.assertNotEqual(first_agent, second_agent)
        self.assertNotEqual(first_remote, second_remote)
        self.assertNotEqual(first_agent, first_remote)
        self.assertNotEqual(first_agent, 1001)
        self.assertNotEqual(first_remote, 1002)

    def test_agora_start_defaults_to_a_unique_channel(self):
        first = main.generate_agora_channel_name()
        second = main.generate_agora_channel_name()
        self.assertNotEqual(first, "lifepilot-demo")
        self.assertNotEqual(first, second)
        self.assertTrue(first.startswith("lifepilot-"))


if __name__ == "__main__":
    unittest.main()
