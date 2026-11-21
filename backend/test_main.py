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


if __name__ == "__main__":
    unittest.main()
