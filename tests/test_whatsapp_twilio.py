import asyncio
import json
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch


class TwilioWhatsAppTemplateTests(unittest.TestCase):
    @patch.dict(
        os.environ,
        {
            "TWILIO_ACCOUNT_SID": "AC123",
            "TWILIO_AUTH_TOKEN": "token123",
            "TWILIO_WHATSAPP_FROM": "whatsapp:+14155238886",
            "WHATSAPP_RECIPIENT_NUMBER": "+917658975169",
            "YOUR_PHONE_NUMBER": "7658975169",
            "YOUR_NAME": "Vara Prasad",
            "RESUME_PUBLIC_URL": "https://example.com/resume.pdf",
            "ARCHITECTURE_DIAGRAM_URL": "https://example.com/diagram.png",
        },
        clear=True,
    )
    def test_mid_call_template_uses_twilio_content_variables(self):
        from agent.whatsapp import send_mid_call_message

        with patch("agent.whatsapp.Client") as mock_client:
            mock_client.return_value.messages.create.return_value = MagicMock()

            success = asyncio.run(send_mid_call_message("Hot lead interested in website redesign", "hot"))

            self.assertTrue(success)
            mock_client.assert_called_once_with("AC123", "token123")
            create_kwargs = mock_client.return_value.messages.create.call_args.kwargs
            self.assertEqual(create_kwargs["content_sid"], "HX0b5ef55c49ac598c27c41aaea7393634")
            self.assertEqual(create_kwargs["from_"], "whatsapp:+14155238886")
            self.assertEqual(create_kwargs["to"], "whatsapp:+917658975169")
            self.assertEqual(
                json.loads(create_kwargs["content_variables"]),
                {
                    "1": "Vara Prasad",
                    "2": "High buying intent right now. Hot lead interested in website redesign",
                    "3": "+91 7658975169",
                },
            )

    @patch.dict(
        os.environ,
        {
            "TWILIO_ACCOUNT_SID": "AC123",
            "TWILIO_AUTH_TOKEN": "token123",
            "TWILIO_WHATSAPP_FROM": "whatsapp:+14155238886",
            "WHATSAPP_RECIPIENT_NUMBER": "+917658975169",
            "YOUR_PHONE_NUMBER": "7658975169",
            "YOUR_NAME": "Vara Prasad",
        },
        clear=True,
    )
    def test_mid_call_context_is_normalized_for_template_variable(self):
        from agent.whatsapp import send_mid_call_message

        with patch("agent.whatsapp.Client") as mock_client:
            mock_client.return_value.messages.create.return_value = MagicMock()

            success = asyncio.run(
                send_mid_call_message("Budget: 30,000 INR.\n\nTimeline: one month.", "hot")
            )

            self.assertTrue(success)
            variables = json.loads(
                mock_client.return_value.messages.create.call_args.kwargs["content_variables"]
            )
            self.assertIn("Budget: 30,000 INR. Timeline: one month.", variables["2"])

    @patch.dict(
        os.environ,
        {
            "TWILIO_ACCOUNT_SID": "AC123",
            "TWILIO_AUTH_TOKEN": "token123",
            "TWILIO_WHATSAPP_FROM": "whatsapp:+14155238886",
            "WHATSAPP_RECIPIENT_NUMBER": "+917658975169",
            "YOUR_PHONE_NUMBER": "7658975169",
            "YOUR_NAME": "Vara Prasad",
        },
        clear=True,
    )
    def test_mid_call_message_reflects_tone(self):
        from agent.whatsapp import send_mid_call_message

        with patch("agent.whatsapp.Client") as mock_client:
            mock_client.return_value.messages.create.return_value = MagicMock()

            asyncio.run(send_mid_call_message("wants a jewelry store, budget 30k", "hot"))
            hot_variables = json.loads(
                mock_client.return_value.messages.create.call_args.kwargs["content_variables"]
            )

            asyncio.run(send_mid_call_message("just browsing, no clear budget", "cold"))
            cold_variables = json.loads(
                mock_client.return_value.messages.create.call_args.kwargs["content_variables"]
            )

            self.assertNotEqual(hot_variables["2"], cold_variables["2"])
            self.assertIn("High buying intent", hot_variables["2"])
            self.assertIn("Low intent", cold_variables["2"])

    @patch.dict(
        os.environ,
        {
            "TWILIO_ACCOUNT_SID": "AC123",
            "TWILIO_AUTH_TOKEN": "token123",
            "TWILIO_WHATSAPP_FROM": "whatsapp:+14155238886",
            "WHATSAPP_RECIPIENT_NUMBER": "+917658975169",
            "YOUR_PHONE_NUMBER": "7658975169",
            "RESUME_PUBLIC_URL": "https://example.com/resume.pdf",
            "ARCHITECTURE_DIAGRAM_URL": "https://example.com/diagram.png",
        },
        clear=True,
    )
    def test_post_call_template_uses_required_values(self):
        from agent.whatsapp import send_post_call_summary

        with patch("agent.whatsapp.Client") as mock_client:
            mock_client.return_value.messages.create.return_value = MagicMock()

            call_context = "We discussed a website project and his team wants a quick proposal."
            success = asyncio.run(send_post_call_summary(call_context, "hot"))

            self.assertTrue(success)
            create_kwargs = mock_client.return_value.messages.create.call_args.kwargs
            self.assertEqual(create_kwargs["content_sid"], "HX2f327669489ed03af33a064ca3485999")
            variables = json.loads(create_kwargs["content_variables"])
            self.assertEqual(variables["1"], "Vara Prasad")
            # Variable 2 is the short classification tag.
            self.assertIn("Hot lead", variables["2"])
            # Variable 3 is the framed body and MUST carry the real call
            # context — this was previously a hardcoded string that ignored
            # the conversation entirely (assignment section 06, item 1).
            self.assertIn(call_context, variables["3"])
            self.assertEqual(variables["4"], "+91 7658975169")
            self.assertEqual(variables["5"], "https://example.com/resume.pdf")
            self.assertEqual(variables["6"], "https://example.com/diagram.png")

    @patch.dict(
        os.environ,
        {
            "TWILIO_ACCOUNT_SID": "AC123",
            "TWILIO_AUTH_TOKEN": "token123",
            "TWILIO_WHATSAPP_FROM": "whatsapp:+14155238886",
            "WHATSAPP_RECIPIENT_NUMBER": "+917658975169",
            "YOUR_PHONE_NUMBER": "7658975169",
        },
        clear=True,
    )
    def test_post_call_template_classification_changes_variable_2(self):
        from agent.whatsapp import send_post_call_summary

        with patch("agent.whatsapp.Client") as mock_client:
            mock_client.return_value.messages.create.return_value = MagicMock()

            asyncio.run(send_post_call_summary("some context", "cold"))
            cold_variables = json.loads(
                mock_client.return_value.messages.create.call_args.kwargs["content_variables"]
            )

            asyncio.run(send_post_call_summary("some context", "hot"))
            hot_variables = json.loads(
                mock_client.return_value.messages.create.call_args.kwargs["content_variables"]
            )

            self.assertNotEqual(cold_variables["2"], hot_variables["2"])

    @patch.dict(
        os.environ,
        {
            "TWILIO_ACCOUNT_SID": "AC123",
            "TWILIO_AUTH_TOKEN": "token123",
            "TWILIO_WHATSAPP_FROM": "whatsapp:+14155238886",
            "WHATSAPP_RECIPIENT_NUMBER": "+917658975169",
            "YOUR_PHONE_NUMBER": "7658975169",
            "YOUR_NAME": "Vara Prasad",
            "RESUME_PUBLIC_URL": "https://example.com/resume.pdf",
            "ARCHITECTURE_DIAGRAM_URL": "https://example.com/diagram.png",
        },
        clear=True,
    )
    def test_post_call_summary_greets_caller_by_name_when_known(self):
        """Section 06 item 2: the follow-up should read like a person wrote
        it after a real call, not a template with the name missing — when
        record_caller_name captured a name during the call, it must open
        the message."""
        from agent.whatsapp import send_post_call_summary

        with patch("agent.whatsapp.Client") as mock_client:
            mock_client.return_value.messages.create.return_value = MagicMock()

            asyncio.run(send_post_call_summary("wants a jewelry store, budget 30k", "hot", "Ramesh"))
            variables = json.loads(
                mock_client.return_value.messages.create.call_args.kwargs["content_variables"]
            )
            self.assertTrue(variables["3"].startswith("Hi Ramesh!"))
            self.assertIn("jewelry store", variables["3"])

            # No name captured (e.g. call hung up early) -> no fabricated greeting.
            asyncio.run(send_post_call_summary("wants a jewelry store, budget 30k", "hot", ""))
            variables_no_name = json.loads(
                mock_client.return_value.messages.create.call_args.kwargs["content_variables"]
            )
            self.assertFalse(variables_no_name["3"].startswith("Hi"))

    @patch("agent.main.whatsapp.send_post_call_summary", new_callable=AsyncMock)
    @patch("agent.main.storage.record_whatsapp_send", new_callable=AsyncMock)
    @patch("agent.main.storage.get_latest_callback", new_callable=AsyncMock)
    @patch("agent.main.storage.get_call", new_callable=AsyncMock)
    @patch("agent.main.storage.set_discovery", new_callable=AsyncMock)
    def test_send_summary_passes_caller_name_through(
        self,
        mock_set_discovery,
        mock_get_call,
        mock_get_latest_callback,
        mock_record_whatsapp_send,
        mock_send_post_call_summary,
    ):
        from agent.main import ElevateBoxSalesAgent

        agent = ElevateBoxSalesAgent("call-name-2", None)
        mock_get_call.return_value = {"current_classification": "hot"}
        mock_get_latest_callback.return_value = None
        mock_send_post_call_summary.return_value = True

        asyncio.run(agent.record_caller_name(None, "Priya"))
        asyncio.run(agent._send_summary())

        self.assertEqual(mock_send_post_call_summary.call_args.args[2], "Priya")

    @patch.dict(
        os.environ,
        {
            "TARGET_PHONE_NUMBER": "+917386696790",
            "WHATSAPP_RECIPIENT_NUMBER": "",
        },
        clear=True,
    )
    def test_whatsapp_recipient_defaults_to_target_phone_number(self):
        from agent.whatsapp import _recipient_whatsapp_number

        self.assertEqual(_recipient_whatsapp_number(), "whatsapp:+917386696790")

    def test_detect_tts_language_from_text_handles_romanized_telugu(self):
        from agent.main import detect_tts_language_from_text

        self.assertEqual(detect_tts_language_from_text("naku website kavali, bagundi"), "te-IN")
        self.assertEqual(detect_tts_language_from_text("bro, budget ledu and timeline cheppandi"), "te-IN")

    def test_tts_language_prefers_spoken_text_over_english_metadata(self):
        from agent.main import resolve_tts_language

        self.assertEqual(resolve_tts_language("naku website kavali, bagundi", "en-IN"), "te-IN")
        self.assertEqual(resolve_tts_language("budget ledu, timeline cheppandi", "en-IN"), "te-IN")
        self.assertEqual(resolve_tts_language("main website banana chahta hoon", "en-IN"), "hi-IN")

    def test_classify_caller_turn_pure_english(self):
        from agent.main import classify_caller_turn

        verdict, locale = classify_caller_turn("What's the price and timeline for this?")
        self.assertEqual(verdict, "pure_english")
        self.assertEqual(locale, "en-IN")

    def test_classify_caller_turn_code_mixed_telugu_not_pure_english(self):
        """Regression test: this is the exact 'Teluguish' shape the caller
        reported — before the fix, the agent replied in pure English to
        input like this because nothing told the LLM what language the
        caller had actually just used."""
        from agent.main import classify_caller_turn

        verdict, locale = classify_caller_turn(
            "naku website kavali but budget thoda tight undi"
        )
        self.assertEqual(verdict, "code_mixed_telugu")
        self.assertEqual(locale, "te-IN")

    def test_classify_caller_turn_pure_telugu_script(self):
        from agent.main import classify_caller_turn

        verdict, locale = classify_caller_turn("నాకు వెబ్‌సైట్ కావాలి")
        self.assertEqual(verdict, "pure_telugu")
        self.assertEqual(locale, "te-IN")

    def test_classify_caller_turn_telugu_script_with_english_word_is_code_mixed(self):
        from agent.main import classify_caller_turn

        verdict, _locale = classify_caller_turn("నాకు website కావాలి")
        self.assertEqual(verdict, "code_mixed_telugu")

    def test_classify_caller_turn_hindi_romanized(self):
        from agent.main import classify_caller_turn

        verdict, locale = classify_caller_turn("mera budget kam hai, kya kar sakte ho")
        self.assertEqual(verdict, "hindi_romanized")
        self.assertEqual(locale, "hi-IN")

    def test_on_user_turn_completed_injects_language_cue_for_code_mixed_telugu(self):
        from agent.main import ElevateBoxSalesAgent

        agent = ElevateBoxSalesAgent("call-lang-1", None)
        turn_ctx = MagicMock()
        new_message = MagicMock(text_content="naku website kavali but budget thoda tight undi")

        asyncio.run(agent.on_user_turn_completed(turn_ctx, new_message))

        turn_ctx.add_message.assert_called_once()
        kwargs = turn_ctx.add_message.call_args.kwargs
        self.assertEqual(kwargs["role"], "system")
        self.assertIn("Do NOT reply in pure English", kwargs["content"])

    def test_on_user_turn_completed_no_cue_for_pure_english(self):
        from agent.main import ElevateBoxSalesAgent

        agent = ElevateBoxSalesAgent("call-lang-2", None)
        turn_ctx = MagicMock()
        new_message = MagicMock(text_content="What's your budget for this?")

        asyncio.run(agent.on_user_turn_completed(turn_ctx, new_message))

        turn_ctx.add_message.assert_not_called()

    def test_record_caller_name_sets_instance_state(self):
        from agent.main import ElevateBoxSalesAgent

        agent = ElevateBoxSalesAgent("call-name-1", None)
        result = asyncio.run(agent.record_caller_name(None, "  Ramesh  "))

        self.assertEqual(agent._caller_name, "Ramesh")
        self.assertIn("Ramesh", result)

    def test_mid_call_whatsapp_is_blocked_until_required_discovery_is_complete(self):
        from agent.main import ElevateBoxSalesAgent

        agent = ElevateBoxSalesAgent("call-123", None)

        result = asyncio.run(agent.send_whatsapp_now(None, "clothes", "cold"))

        self.assertIn("Not enough discovery yet", result)
        self.assertFalse(agent._mid_call_whatsapp_sent)

    def test_mid_call_whatsapp_is_blocked_when_only_the_first_question_is_answered(self):
        from agent.main import _has_required_discovery

        context = (
            "agent: what do you sell? caller: clothes. no other details discussed yet."
        )

        self.assertFalse(_has_required_discovery(context))

    def test_mid_call_whatsapp_only_sends_after_required_questions_are_asked(self):
        from agent.main import _has_required_discovery

        context = (
            "agent: what do you sell? how many products do you have? what timeline are you thinking? "
            "what features do you need? what budget range are you looking at? "
            "caller: sells clothes, 50 products."
        )

        self.assertTrue(_has_required_discovery(context))

    @patch("agent.main.whatsapp.send_mid_call_message", new_callable=AsyncMock)
    @patch("agent.main.storage.record_whatsapp_send", new_callable=AsyncMock)
    @patch("agent.main.storage.set_classification", new_callable=AsyncMock)
    def test_mid_call_whatsapp_only_sent_once_per_call(
        self,
        mock_set_classification,
        mock_record_whatsapp_send,
        mock_send_mid_call_message,
    ):
        from agent.main import ElevateBoxSalesAgent

        agent = ElevateBoxSalesAgent("call-123", None)
        mock_send_mid_call_message.return_value = True

        full_context = (
            "clothes, 50 products, timeline 2 months, all features including payments and inventory, "
            "budget 30000 INR"
        )

        asyncio.run(agent.classify_lead(None, "hot", full_context))
        asyncio.run(agent.classify_lead(None, "hot", full_context))
        asyncio.run(agent.classify_lead(None, "cold", full_context))

        self.assertEqual(mock_send_mid_call_message.await_count, 1)
        self.assertTrue(agent._mid_call_whatsapp_sent)
        self.assertEqual(agent._mid_call_tones_sent, {"hot"})

    @patch("agent.main.storage.set_discovery", new_callable=AsyncMock)
    def test_update_discovery_rejects_literal_null_and_similar_non_answers(self, mock_set_discovery):
        """Regression test: a real call had the LLM pass the literal string
        "null" for fields it didn't have an answer for, which then leaked
        verbatim into a real WhatsApp message ("sells: null; catalog size:
        null..."). update_discovery must treat these as no answer, same as
        an empty string."""
        from agent.main import ElevateBoxSalesAgent

        agent = ElevateBoxSalesAgent("call-null-1", None)

        asyncio.run(
            agent.update_discovery(
                None,
                category="null",
                catalog_size="None",
                timeline="n/a",
                features="not discussed",
                budget="1 lakh INR",
            )
        )

        self.assertEqual(agent._discovery_context(), "budget: 1 lakh INR")
        self.assertNotIn("null", agent._discovery_context().lower())

    @patch("agent.main.storage.set_discovery", new_callable=AsyncMock)
    def test_update_discovery_tracks_structured_fields(self, mock_set_discovery):
        from agent.main import ElevateBoxSalesAgent

        agent = ElevateBoxSalesAgent("call-456", None)

        asyncio.run(agent.update_discovery(None, category="handmade jewelry"))
        asyncio.run(agent.update_discovery(None, catalog_size="about 50 products"))
        asyncio.run(agent.update_discovery(None, timeline="in 3 weeks"))
        self.assertFalse(agent._discovery_complete())

        asyncio.run(agent.update_discovery(None, features="payments, inventory tracking"))
        self.assertTrue(agent._discovery_complete())
        self.assertIn("handmade jewelry", agent._discovery_context())
        self.assertIn("in 3 weeks", agent._discovery_context())

    @patch("agent.main.whatsapp.send_mid_call_message", new_callable=AsyncMock)
    @patch("agent.main.storage.record_whatsapp_send", new_callable=AsyncMock)
    @patch("agent.main.storage.set_classification", new_callable=AsyncMock)
    @patch("agent.main.storage.set_discovery", new_callable=AsyncMock)
    def test_mid_call_whatsapp_fires_from_structured_discovery_on_non_english_call(
        self,
        mock_set_discovery,
        mock_set_classification,
        mock_record_whatsapp_send,
        mock_send_mid_call_message,
    ):
        """Regression test: before this fix, a call conducted entirely in
        Telugu/Hindi could never trigger the mid-call WhatsApp, because the
        gate only recognized English keywords in the raw transcript.
        update_discovery records fields in English regardless of the
        caller's language, so the gate must key off that structured state
        instead of scanning transcript text for English phrases."""
        from agent.main import ElevateBoxSalesAgent

        agent = ElevateBoxSalesAgent("call-789", None)
        mock_send_mid_call_message.return_value = True

        asyncio.run(agent.update_discovery(None, category="clothes"))
        asyncio.run(agent.update_discovery(None, catalog_size="50 products"))
        asyncio.run(agent.update_discovery(None, timeline="next month"))
        asyncio.run(agent.update_discovery(None, budget="30000 INR"))

        # No English discovery keywords anywhere in this reasoning string —
        # only the structured discovery dict can satisfy the gate.
        non_english_reasoning = "మంచి ఆసక్తి చూపించారు, వెంటనే మొదలుపెట్టాలి అన్నారు"
        asyncio.run(agent.classify_lead(None, "hot", non_english_reasoning))

        self.assertEqual(mock_send_mid_call_message.await_count, 1)
        self.assertTrue(agent._mid_call_whatsapp_sent)

    @patch("agent.main.whatsapp.send_post_call_summary", new_callable=AsyncMock)
    @patch("agent.main.storage.record_whatsapp_send", new_callable=AsyncMock)
    @patch("agent.main.storage.get_latest_callback", new_callable=AsyncMock)
    @patch("agent.main.storage.get_call", new_callable=AsyncMock)
    @patch("agent.main.storage.set_discovery", new_callable=AsyncMock)
    def test_post_call_summary_uses_structured_discovery_not_raw_transcript(
        self,
        mock_set_discovery,
        mock_get_call,
        mock_get_latest_callback,
        mock_record_whatsapp_send,
        mock_send_post_call_summary,
    ):
        from agent.main import ElevateBoxSalesAgent

        agent = ElevateBoxSalesAgent("call-999", None)
        mock_get_call.return_value = {"current_classification": "hot"}
        mock_get_latest_callback.return_value = None
        mock_send_post_call_summary.return_value = True

        asyncio.run(agent.update_discovery(None, category="clothes", budget="30000 INR"))
        asyncio.run(agent._send_summary())

        context_arg = mock_send_post_call_summary.call_args.args[0]
        self.assertIn("clothes", context_arg)
        self.assertIn("30000 INR", context_arg)


if __name__ == "__main__":
    unittest.main()
