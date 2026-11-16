from types import SimpleNamespace
from unittest.mock import Mock

from django.test import SimpleTestCase

from insights.ai.groq_client import (
    FinancialAssistantInputError,
    FinancialAssistantProviderError,
    FinancialAssistantService,
    FinancialAssistantToolLimitError,
    ToolInvocation,
)
from insights.ai.registry import ToolRegistryError


def make_tool_call(call_id="call_1", name="spend_by", arguments='{"dimension":"vendor"}'):
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def make_response(*, content=None, tool_calls=None):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content, tool_calls=tool_calls or [])
            )
        ]
    )


class FakeCompletions:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        if not self.responses:
            raise AssertionError("No fake Groq response remains.")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class FakeClient:
    def __init__(self, responses):
        self.chat = SimpleNamespace(
            completions=FakeCompletions(responses),
        )


class FakeRegistry:
    def __init__(self, result=None, error=None):
        self.result = result if result is not None else {"total_expenditure": "1250.00"}
        self.error = error
        self.available_contexts = []
        self.executions = []

    def available_tools(self, context):
        self.available_contexts.append(context)
        return [
            {
                "type": "function",
                "function": {
                    "name": "spend_by",
                    "description": "Read expenditure report",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]

    def execute(self, *, name, arguments, context):
        self.executions.append((name, arguments, context))
        if self.error:
            raise self.error
        return self.result


class FinancialAssistantServiceTests(SimpleTestCase):
    def setUp(self):
        self.context = object()

    def make_service(self, responses, *, registry=None, max_tool_calls=4):
        client = FakeClient(responses)
        registry = registry or FakeRegistry()
        service = FinancialAssistantService(
            client=client,
            registry=registry,
            model="openai/gpt-oss-20b",
            max_tool_calls=max_tool_calls,
        )
        return service, client, registry

    def test_returns_direct_answer_without_calling_a_tool(self):
        service, client, registry = self.make_service(
            [make_response(content="Hello. No report lookup is needed.")]
        )

        result = service.answer("Hello", context=self.context)

        self.assertEqual(result.answer, "Hello. No report lookup is needed.")
        self.assertEqual(result.tool_call_count, 0)
        self.assertEqual(result.model, "openai/gpt-oss-20b")
        self.assertEqual(registry.executions, [])
        self.assertEqual(len(client.chat.completions.requests), 1)

    def test_executes_tool_and_sends_result_back_to_groq(self):
        service, client, registry = self.make_service(
            [
                make_response(tool_calls=[make_tool_call()]),
                make_response(content="The reported expenditure is NGN 1,250.00."),
            ]
        )

        result = service.answer("Show expenditure by vendor", context=self.context)

        self.assertEqual(result.answer, "The reported expenditure is NGN 1,250.00.")
        self.assertEqual(result.tool_call_count, 1)
        self.assertEqual(
            result.tool_invocations,
            (ToolInvocation("call_1", "spend_by", True),),
        )
        self.assertEqual(registry.available_contexts, [self.context])
        self.assertEqual(registry.executions, [("spend_by", '{"dimension":"vendor"}', self.context)])

        second_request = client.chat.completions.requests[1]
        tool_messages = [message for message in second_request["messages"] if isinstance(message, dict) and message.get("role") == "tool"]
        self.assertEqual(len(tool_messages), 1)
        self.assertEqual(tool_messages[0]["tool_call_id"], "call_1")
        self.assertIn('"ok":true', tool_messages[0]["content"])
        self.assertIn('"total_expenditure":"1250.00"', tool_messages[0]["content"])

    def test_tool_calls_are_executed_sequentially_and_parallel_calls_are_disabled(self):
        registry = FakeRegistry()
        service, client, _ = self.make_service(
            [
                make_response(
                    tool_calls=[
                        make_tool_call("call_1", arguments='{"dimension":"vendor"}'),
                        make_tool_call("call_2", arguments='{"dimension":"month"}'),
                    ]
                ),
                make_response(content="I have both report results."),
            ],
            registry=registry,
        )

        result = service.answer("Compare vendor and monthly spend", context=self.context)

        self.assertEqual(result.tool_call_count, 2)
        self.assertEqual(
            [call[1] for call in registry.executions],
            ['{"dimension":"vendor"}', '{"dimension":"month"}'],
        )
        self.assertFalse(client.chat.completions.requests[0]["parallel_tool_calls"])

    def test_registry_rejection_is_returned_as_a_safe_tool_error(self):
        registry = FakeRegistry(error=ToolRegistryError("Invalid reporting dimension."))
        service, client, _ = self.make_service(
            [
                make_response(tool_calls=[make_tool_call()]),
                make_response(content="I could not retrieve that report filter."),
            ],
            registry=registry,
        )

        result = service.answer("Show expenditure", context=self.context)

        self.assertEqual(result.tool_call_count, 1)
        self.assertFalse(result.tool_invocations[0].succeeded)
        tool_messages = [message for message in client.chat.completions.requests[1]["messages"] if isinstance(message, dict) and message.get("role") == "tool"]
        self.assertIn('"ok":false', tool_messages[0]["content"])
        self.assertIn("Invalid reporting dimension.", tool_messages[0]["content"])

    def test_tool_call_budget_is_checked_before_any_call_in_the_batch_executes(self):
        registry = FakeRegistry()
        service, _, _ = self.make_service(
            [
                make_response(
                    tool_calls=[
                        make_tool_call("call_1"),
                        make_tool_call("call_2"),
                    ]
                )
            ],
            registry=registry,
            max_tool_calls=1,
        )

        with self.assertRaises(FinancialAssistantToolLimitError):
            service.answer("Show expenditure", context=self.context)

        self.assertEqual(registry.executions, [])

    def test_empty_question_is_rejected_before_provider_call(self):
        service, client, _ = self.make_service([])

        with self.assertRaises(FinancialAssistantInputError):
            service.answer("   ", context=self.context)

        self.assertEqual(client.chat.completions.requests, [])

    def test_question_longer_than_limit_is_rejected(self):
        service, client, _ = self.make_service([])

        with self.assertRaises(FinancialAssistantInputError):
            service.answer("x" * 8_001, context=self.context)

        self.assertEqual(client.chat.completions.requests, [])

    def test_empty_provider_response_is_rejected(self):
        service, _, _ = self.make_service([SimpleNamespace(choices=[])])

        with self.assertRaises(FinancialAssistantProviderError):
            service.answer("Show expenditure", context=self.context)

    def test_invalid_tool_call_shape_is_rejected(self):
        invalid_call = SimpleNamespace(
            id="",
            function=SimpleNamespace(name="spend_by", arguments="{}"),
        )
        service, _, registry = self.make_service(
            [make_response(tool_calls=[invalid_call])]
        )

        with self.assertRaises(FinancialAssistantProviderError):
            service.answer("Show expenditure", context=self.context)

        self.assertEqual(registry.executions, [])

    def test_decimal_and_date_tool_values_are_json_serialized(self):
        from datetime import date
        from decimal import Decimal
        import json

        payload = {
            "amount": Decimal("12.30"),
            "period_start": date(2026, 1, 1),
        }
        encoded = json.dumps(payload, default=FinancialAssistantService._json_default)

        self.assertEqual(
            json.loads(encoded),
            {"amount": "12.30", "period_start": "2026-01-01"},
        )
