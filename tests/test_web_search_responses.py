from types import SimpleNamespace

from langchain_core.messages import AIMessage

from agents.web_search_processor_agent.web_search_processor import WebSearchProcessor


class FakeResponse:
    output_text = "基于最新资料的医学信息。"
    model = "gpt-5.6-sol"

    def model_dump(self):
        return {
            "output": [
                {
                    "type": "web_search_call",
                    "action": {
                        "sources": [
                            {"title": "WHO", "url": "https://www.who.int/example"},
                            {"title": "WHO duplicate", "url": "https://www.who.int/example"},
                        ]
                    },
                }
            ]
        }


class FakeResponses:
    def __init__(self):
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return FakeResponse()


def test_gpt_56_sol_uses_responses_web_search_and_returns_sources():
    responses = FakeResponses()
    config = SimpleNamespace(
        web_search=SimpleNamespace(
            responses_client=SimpleNamespace(responses=responses),
            model_name="gpt-5.6-sol",
            max_output_tokens=2048,
        )
    )
    processor = WebSearchProcessor(config)

    result = processor.process_web_results("最新肿瘤治疗进展", "")

    assert isinstance(result["message"], AIMessage)
    assert "https://www.who.int/example" in result["message"].content
    assert result["source_count"] == 1
    assert responses.kwargs["model"] == "gpt-5.6-sol"
    assert responses.kwargs["tools"] == [{"type": "web_search"}]
    assert responses.kwargs["tool_choice"] == "required"
    assert responses.kwargs["store"] is False
    assert responses.kwargs["include"] == ["web_search_call.action.sources"]
