from datetime import date, datetime, timezone as datetime_timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from insights.ai.context import ToolContext
from insights.ai.registry import _run_spend_by
from insights.ai.schemas import SpendByArguments
from insights.services.spend import SpendReportError


class OrganisationLocalDateTests(SimpleTestCase):
    def make_context(self, *, timezone_name="Africa/Lagos"):
        user = SimpleNamespace(pk=7, is_authenticated=True)
        organization = SimpleNamespace(is_active=True, timezone=timezone_name)
        membership = SimpleNamespace(
            user_id=user.pk,
            is_active=True,
            organization=organization,
            role="read_only",
        )
        return ToolContext(user=user, membership=membership)

    @patch("insights.ai.context.django_timezone.now")
    def test_current_date_uses_organisation_timezone(self, mocked_now):
        mocked_now.return_value = datetime(
            2026, 11, 16, 23, 30, tzinfo=datetime_timezone.utc
        )
        context = self.make_context(timezone_name="Africa/Lagos")

        self.assertEqual(context.local_today, date(2026, 11, 17))

    @patch("insights.ai.context.django_timezone.now")
    def test_current_date_is_not_taken_from_server_utc_date(self, mocked_now):
        mocked_now.return_value = datetime(
            2026, 11, 16, 0, 30, tzinfo=datetime_timezone.utc
        )
        context = self.make_context(timezone_name="America/Los_Angeles")

        self.assertEqual(context.local_today, date(2026, 11, 15))


class SpendToolDatePolicyTests(SimpleTestCase):
    def setUp(self):
        self.context = SimpleNamespace(
            local_today=date(2026, 11, 16),
            organization=SimpleNamespace(timezone="Africa/Lagos"),
        )

    def arguments(self, *, start_date=date(2026, 1, 1), end_date=date(2026, 11, 16)):
        return SpendByArguments(
            dimension="vendor",
            start_date=start_date,
            end_date=end_date,
            currency="NGN",
        )

    @patch("insights.ai.registry.spend_by")
    def test_future_end_date_is_rejected_before_reporting_service(self, spend_by):
        arguments = self.arguments(end_date=date(2026, 11, 30))

        with self.assertRaisesRegex(
            SpendReportError, "after the organisation's current date"
        ):
            _run_spend_by(self.context, arguments)

        spend_by.assert_not_called()

    @patch("insights.ai.registry.spend_by")
    def test_future_start_date_is_rejected_before_reporting_service(self, spend_by):
        arguments = self.arguments(
            start_date=date(2026, 11, 17),
            end_date=date(2026, 11, 30),
        )

        with self.assertRaisesRegex(SpendReportError, "start_date .* is after"):
            _run_spend_by(self.context, arguments)

        spend_by.assert_not_called()

    @patch("insights.ai.registry.spend_by", return_value={"total": "1.00"})
    def test_current_local_date_is_an_allowed_end_date(self, spend_by):
        arguments = self.arguments(end_date=date(2026, 11, 16))

        result = _run_spend_by(self.context, arguments)

        self.assertEqual(result, {"total": "1.00"})
        self.assertEqual(
            spend_by.call_args.kwargs["end_date"], date(2026, 11, 16)
        )

    @patch("insights.ai.registry.spend_by", return_value={"total": "1.00"})
    def test_explicit_historical_period_is_preserved(self, spend_by):
        arguments = self.arguments(
            start_date=date(2024, 4, 1),
            end_date=date(2024, 9, 30),
        )

        _run_spend_by(self.context, arguments)

        self.assertEqual(
            spend_by.call_args.kwargs["start_date"], date(2024, 4, 1)
        )
        self.assertEqual(
            spend_by.call_args.kwargs["end_date"], date(2024, 9, 30)
        )


class AssistantReportingDateContextTests(SimpleTestCase):
    def test_system_prompt_contains_organisation_date_and_shorthand_rule(self):
        completion = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="The report is ready.", tool_calls=[]
                    )
                )
            ]
        )
        create = Mock(return_value=completion)
        client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        )

        class EmptyRegistry:
            def available_tools(self, context):
                return []

        context = SimpleNamespace(
            organization=SimpleNamespace(timezone="Africa/Lagos"),
            local_today=date(2026, 11, 16),
        )
        from insights.ai.groq_client import FinancialAssistantService

        service = FinancialAssistantService(
            client=client,
            registry=EmptyRegistry(),
            model="openai/gpt-oss-20b",
        )
        service.answer(
            "Show expenditure from January to November 2026.", context=context
        )

        system_message = create.call_args.kwargs["messages"][0]["content"]
        self.assertIn("Current date in that timezone: 2026-11-16", system_message)
        self.assertIn(
            "January to the current month ends on the supplied current date",
            system_message,
        )
        self.assertIn("do not silently shorten it", system_message)
