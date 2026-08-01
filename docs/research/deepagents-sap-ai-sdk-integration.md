# DeepAgents + SAP Generative AI Hub SDK Integration Research

Date: 2026-07-31

## Core conclusion

SAP Generative AI Hub SDK models can be connected to LangChain DeepAgents by passing an initialized SAP LangChain chat-model object to `create_deep_agent(model=...)`, not by using a DeepAgents `provider:model` string. DeepAgents documents that it works with LangChain chat models that support tool calling and that `create_deep_agent` accepts either a `provider:model` string or an initialized model instance; package source inspection confirms the current constructor type is `str | BaseChatModel | None` and pre-initialized `BaseChatModel` objects are returned unchanged by its resolver. [LangChain DeepAgents quickstart](https://docs.langchain.com/oss/python/deepagents/quickstart.md), [LangChain DeepAgents models](https://docs.langchain.com/oss/python/deepagents/models.md), [deepagents 0.7.1 source distribution](https://files.pythonhosted.org/packages/88/e3/00c98c6b677ba89270b09dcb950848c794d507168b3dc53fa4d5cfb6a2e3/deepagents-0.7.1.tar.gz)

The main caveat is dependencies: the latest PyPI metadata observed during this research reports `deepagents==0.7.1` requiring `langchain-google-genai>=4.3.1,<5.0.0`, while `sap-ai-sdk-gen[all]==7.2.0` requires `langchain-google-genai~=4.2.5`, which means current latest `deepagents` + current `sap-ai-sdk-gen[all]` are not resolver-compatible. The clean current prototype should start with SAP's OpenAI-compatible wrapper (`sap-ai-sdk-gen`, no `[all]`) or the Amazon subset (`sap-ai-sdk-gen[amazon]`), and only use `[all]` with an older compatible DeepAgents pin such as `deepagents==0.6.12` until SAP updates the Google extra. [PyPI deepagents JSON](https://pypi.org/pypi/deepagents/json), [PyPI sap-ai-sdk-gen JSON](https://pypi.org/pypi/sap-ai-sdk-gen/json)

## Primary sources consulted

- LangChain DeepAgents quickstart and model configuration docs: `create_deep_agent`, required tool-calling model support, model strings vs initialized model instances. [Quickstart](https://docs.langchain.com/oss/python/deepagents/quickstart.md), [Models](https://docs.langchain.com/oss/python/deepagents/models.md)
- DeepAgents package/source metadata: current version, Python and LangChain dependencies, constructor/source behavior. [PyPI project](https://pypi.org/project/deepagents/), [PyPI JSON](https://pypi.org/pypi/deepagents/json), [0.7.1 sdist](https://files.pythonhosted.org/packages/88/e3/00c98c6b677ba89270b09dcb950848c794d507168b3dc53fa4d5cfb6a2e3/deepagents-0.7.1.tar.gz)
- SAP Help for SAP Cloud SDK for AI, formerly Generative AI Hub SDK: installation, authentication, LangChain integration, streaming, async examples. [SAP SDK README](https://help.sap.com/doc/generative-ai-hub-sdk/CLOUD/en-US/_reference/README_sphynx.html), [SAP LangChain examples](https://help.sap.com/doc/generative-ai-hub-sdk/CLOUD/en-US/_reference/gen_ai_hub.html), [SAP streaming examples](https://help.sap.com/doc/generative-ai-hub-sdk/CLOUD/en-US/_reference/streaming.html), [SAP async examples](https://help.sap.com/doc/generative-ai-hub-sdk/CLOUD/en-US/_reference/async-examples.html)
- SAP package metadata/source inspection: current version, extras, exported LangChain classes and routing logic in `gen_ai_hub.proxy.langchain`. [PyPI project](https://pypi.org/project/sap-ai-sdk-gen/), [PyPI JSON](https://pypi.org/pypi/sap-ai-sdk-gen/json), [7.2.0 wheel](https://files.pythonhosted.org/packages/aa/34/1a908ceabe7d04406fa5f57f2c857b2f4aca003ea65762b0b9d7a678f275/sap_ai_sdk_gen-7.2.0-py3-none-any.whl)

## What DeepAgents expects

DeepAgents requires a model that supports tool calling. The quickstart calls this out as a prerequisite, and the model docs say DeepAgents work with any LangChain chat model that supports tool calling. [Quickstart](https://docs.langchain.com/oss/python/deepagents/quickstart.md), [Models](https://docs.langchain.com/oss/python/deepagents/models.md)

DeepAgents model strings are LangChain `provider:model` strings resolved through LangChain `init_chat_model`. That mechanism has no documented SAP provider prefix, so SAP models should be passed as initialized LangChain chat model instances instead. [Models](https://docs.langchain.com/oss/python/deepagents/models.md)

Current DeepAgents source inspection confirms `create_deep_agent(model=...)` accepts `str | BaseChatModel | None`; its resolver returns an existing `BaseChatModel` unchanged and only calls LangChain `init_chat_model` for string models. [deepagents 0.7.1 source distribution](https://files.pythonhosted.org/packages/88/e3/00c98c6b677ba89270b09dcb950848c794d507168b3dc53fa4d5cfb6a2e3/deepagents-0.7.1.tar.gz)

Local package verification in a temporary Python 3.11 environment installed `deepagents` with `sap-ai-sdk-gen[all]`; the resolver selected `deepagents==0.6.12`, `sap-ai-sdk-gen==7.2.0`, `langchain==1.3.14`, `langchain-core==1.5.3`, and `langchain-google-genai==4.2.7`. In that environment, `deepagents._models.resolve_model()` returned an existing SAP `BaseChatModel` instance unchanged, and `create_deep_agent(model=<SAP chat model instance>)` successfully created a `CompiledStateGraph` without a live SAP model call.

## What SAP provides

SAP Help says the SDK formerly known as the Generative AI Hub SDK is now SAP Cloud SDK for AI, and provides LLM access by wrapping native provider SDKs for OpenAI, Amazon, and Google, through LangChain, or through the orchestration service. [SAP SDK README](https://help.sap.com/doc/generative-ai-hub-sdk/CLOUD/en-US/_reference/README_sphynx.html)

SAP documents installation with all OpenAI, Amazon, Google, and LangChain support as `pip install "sap-ai-sdk-gen[all]"`; it also documents the default install as `pip install sap-ai-sdk-gen` and provider subsets such as `sap-ai-sdk-gen[google, amazon]`. [SAP SDK README](https://help.sap.com/doc/generative-ai-hub-sdk/CLOUD/en-US/_reference/README_sphynx.html)

SAP authentication can be configured through environment variables or a config file, and the documented environment variables include `AICORE_CLIENT_ID`, `AICORE_CLIENT_SECRET`, `AICORE_AUTH_URL`, `AICORE_BASE_URL` with `/v2` suffix, and `AICORE_RESOURCE_GROUP`; X.509 certificate/key variables are also documented. [SAP SDK README](https://help.sap.com/doc/generative-ai-hub-sdk/CLOUD/en-US/_reference/README_sphynx.html)

SAP Help documents `gen_ai_hub.proxy.langchain.init_llm` and `init_embedding_model` as harmonized LangChain model initializers, and shows `init_llm('gpt-5-nano', max_tokens=300)` in a LangChain pipe. [SAP LangChain examples](https://help.sap.com/doc/generative-ai-hub-sdk/CLOUD/en-US/_reference/gen_ai_hub.html)

SAP Help also documents explicit LangChain wrapper usage, including `ChatOpenAI(proxy_model_name='gpt-4o-mini', proxy_client=get_proxy_client('gen-ai-hub'))` and `ChatBedrock(model_name="anthropic--claude-3-haiku", model_kwargs={"temperature": 0.0})`. [SAP LangChain examples](https://help.sap.com/doc/generative-ai-hub-sdk/CLOUD/en-US/_reference/gen_ai_hub.html), [SAP async examples](https://help.sap.com/doc/generative-ai-hub-sdk/CLOUD/en-US/_reference/async-examples.html)

SAP package source inspection of `sap_ai_sdk_gen-7.2.0` shows `gen_ai_hub.proxy.langchain` exports `init_llm`, `ChatOpenAI`, `ChatBedrock`, `ChatBedrockConverse`, and `ChatGoogleGenerativeAI`; source inspection also shows those classes subclass LangChain provider classes (`langchain_openai.ChatOpenAI`, `langchain_aws.ChatBedrock` / `ChatBedrockConverse`, and `langchain_google_genai.ChatGoogleGenerativeAI`). [sap-ai-sdk-gen 7.2.0 wheel](https://files.pythonhosted.org/packages/aa/34/1a908ceabe7d04406fa5f57f2c857b2f4aca003ea65762b0b9d7a678f275/sap_ai_sdk_gen-7.2.0-py3-none-any.whl)

Local inspection against the installed `sap-ai-sdk-gen==7.2.0` package found `ChatOpenAI`, `ChatBedrock`, `ChatBedrockConverse`, and `ChatGoogleGenerativeAI` are all `BaseChatModel` subclasses and expose `bind_tools()`. `OpenAI` is a `BaseLLM`, not a chat model, so it should not be passed directly to DeepAgents. Offline construction also showed SAP-proxy `ChatOpenAI(proxy_model_name=...)` needs a matching generative AI hub deployment from `get_proxy_client()`; without one it fails validation with "No deployment found". `ChatGoogleGenerativeAI(model=..., api_key=...)` can be constructed locally, but SAP proxy/deployment behavior should still be tested in the target environment.

## Integration options

### Option 1: Explicit SAP `ChatOpenAI` instance, recommended first

This is the lowest-friction path because SAP's default package includes OpenAI LangChain support, SAP documents `ChatOpenAI`, and DeepAgents accepts an initialized LangChain chat model. [SAP SDK README](https://help.sap.com/doc/generative-ai-hub-sdk/CLOUD/en-US/_reference/README_sphynx.html), [SAP LangChain examples](https://help.sap.com/doc/generative-ai-hub-sdk/CLOUD/en-US/_reference/gen_ai_hub.html), [LangChain DeepAgents models](https://docs.langchain.com/oss/python/deepagents/models.md)

```python
from deepagents import create_deep_agent
from gen_ai_hub.proxy import get_proxy_client
from gen_ai_hub.proxy.langchain import ChatOpenAI
from langchain_core.tools import tool


@tool
def echo(text: str) -> str:
    """Echo text for a tool-calling smoke test."""
    return text


proxy_client = get_proxy_client("gen-ai-hub")
model = ChatOpenAI(
    proxy_model_name="gpt-4o-mini",
    proxy_client=proxy_client,
    temperature=0,
    max_tokens=512,
)

# Smoke-test tool binding before involving DeepAgents.
tool_bound = model.bind_tools([echo])
print(tool_bound.invoke("Call the echo tool with text 'ok'."))

agent = create_deep_agent(
    model=model,
    tools=[echo],
    system_prompt="Use tools when useful. Be concise.",
)

result = agent.invoke(
    {"messages": [{"role": "user", "content": "Use echo with text 'ok', then summarize."}]}
)
print(result["messages"][-1].content)
```

### Option 2: SAP `init_llm`, useful but assert chat-model compatibility

SAP documents `init_llm` as a harmonized initializer and source inspection shows it routes OpenAI-like names to SAP's `openai.init_chat_model`, Amazon/Anthropic names to SAP's Bedrock initializer, and Google/Gemini names to SAP's Google initializer. However, its package return type is `BaseLanguageModel`, while DeepAgents wants a chat model with tool calling, so the prototype should assert `BaseChatModel` and test `bind_tools()` before creating the agent. [SAP LangChain examples](https://help.sap.com/doc/generative-ai-hub-sdk/CLOUD/en-US/_reference/gen_ai_hub.html), [sap-ai-sdk-gen 7.2.0 wheel](https://files.pythonhosted.org/packages/aa/34/1a908ceabe7d04406fa5f57f2c857b2f4aca003ea65762b0b9d7a678f275/sap_ai_sdk_gen-7.2.0-py3-none-any.whl), [LangChain DeepAgents models](https://docs.langchain.com/oss/python/deepagents/models.md)

```python
from deepagents import create_deep_agent
from gen_ai_hub.proxy.langchain import init_llm
from langchain_core.language_models import BaseChatModel


model = init_llm("gpt-4o-mini", temperature=0, max_tokens=512)
assert isinstance(model, BaseChatModel), type(model)

agent = create_deep_agent(model=model)
result = agent.invoke({"messages": [{"role": "user", "content": "Write a one-sentence status."}]})
print(result["messages"][-1].content)
```

### Option 3: Amazon Bedrock via SAP, prefer Converse for tool-calling experiments

SAP Help documents `ChatBedrock` usage for Claude via SAP AI Core, and source inspection shows SAP also ships `ChatBedrockConverse`, described as a drop-in replacement for LangChain `ChatBedrockConverse`. Because DeepAgents depends on tool calling, `ChatBedrockConverse` is the more promising Amazon path to prototype, but it needs a direct `bind_tools()` smoke test with the target SAP deployment. [SAP async examples](https://help.sap.com/doc/generative-ai-hub-sdk/CLOUD/en-US/_reference/async-examples.html), [sap-ai-sdk-gen 7.2.0 wheel](https://files.pythonhosted.org/packages/aa/34/1a908ceabe7d04406fa5f57f2c857b2f4aca003ea65762b0b9d7a678f275/sap_ai_sdk_gen-7.2.0-py3-none-any.whl), [LangChain DeepAgents models](https://docs.langchain.com/oss/python/deepagents/models.md)

```python
from deepagents import create_deep_agent
from gen_ai_hub.proxy.langchain import ChatBedrockConverse


model = ChatBedrockConverse(
    model="anthropic--claude-3-haiku",
    temperature=0,
    max_tokens=512,
)

agent = create_deep_agent(model=model)
result = agent.invoke({"messages": [{"role": "user", "content": "Say hello in one sentence."}]})
print(result["messages"][-1].content)
```

### Option 4: Google/Gemini via SAP, blocked with latest `[all]` unless versions change

SAP source inspection shows a `ChatGoogleGenerativeAI` wrapper, and SAP's `[all]` extra includes Google dependencies. The current resolver problem is that `sap-ai-sdk-gen[all]==7.2.0` pins `langchain-google-genai~=4.2.5`, while `deepagents==0.7.1` requires `langchain-google-genai>=4.3.1,<5.0.0`; that conflict must be resolved by a SAP package update, an older DeepAgents pin, or an explicitly unsupported manual dependency override. [PyPI deepagents JSON](https://pypi.org/pypi/deepagents/json), [PyPI sap-ai-sdk-gen JSON](https://pypi.org/pypi/sap-ai-sdk-gen/json), [sap-ai-sdk-gen 7.2.0 wheel](https://files.pythonhosted.org/packages/aa/34/1a908ceabe7d04406fa5f57f2c857b2f4aca003ea65762b0b9d7a678f275/sap_ai_sdk_gen-7.2.0-py3-none-any.whl)

## Dependency and version notes

Observed current PyPI metadata: `deepagents==0.7.1` requires Python `>=3.11,<4.0`, `langchain>=1.3.14,<2.0.0`, `langchain-core>=1.5.0,<2.0.0`, and `langchain-google-genai>=4.3.1,<5.0.0`. [PyPI deepagents JSON](https://pypi.org/pypi/deepagents/json)

Observed current PyPI metadata: `sap-ai-sdk-gen==7.2.0` requires Python `>=3.9`, `langchain~=1.3.11`, `langchain-openai~=1.3.3`, `openai>=1.66.0`, and for `[all]` adds `langchain-google-genai~=4.2.5`, `google-genai~=2.9.0`, `langchain-aws~=1.6.0`, `aiobotocore>=3.2.0`, and `boto3>=1.40.61`. [PyPI sap-ai-sdk-gen JSON](https://pypi.org/pypi/sap-ai-sdk-gen/json)

Local package metadata inspection found `deepagents==0.6.12` requires `langchain-google-genai>=4.2.5,<5.0.0` and `langchain>=1.3.11,<2.0.0`, making it dependency-compatible with `sap-ai-sdk-gen[all]==7.2.0` on the Google package range. This is a compatibility escape hatch, not the best long-term target. [PyPI deepagents JSON](https://pypi.org/pypi/deepagents/json), [PyPI sap-ai-sdk-gen JSON](https://pypi.org/pypi/sap-ai-sdk-gen/json)

Suggested install choices:

| Goal | Install | Notes |
| --- | --- | --- |
| Current DeepAgents + SAP OpenAI-compatible models | `pip install "deepagents==0.7.1" "sap-ai-sdk-gen==7.2.0"` | Recommended minimal prototype. Avoids the `[all]` Google conflict. |
| Current DeepAgents + SAP Amazon models | `pip install "deepagents==0.7.1" "sap-ai-sdk-gen[amazon]==7.2.0"` | Likely resolver-compatible; test `bind_tools()` on `ChatBedrockConverse`. |
| SAP `[all]` is mandatory today | `pip install "deepagents==0.6.12" "sap-ai-sdk-gen[all]==7.2.0"` | Uses an older DeepAgents version to avoid the Google dependency conflict. This exact combination resolved locally. Verify behavior against current docs. |
| Latest DeepAgents + latest SAP `[all]` | `pip install "deepagents==0.7.1" "sap-ai-sdk-gen[all]==7.2.0"` | Not recommended; package metadata has an unsatisfied `langchain-google-genai` intersection. |

## Recommended minimal prototype

Start with current DeepAgents and SAP's OpenAI-compatible LangChain wrapper. This validates the key integration contract without dragging in the current `[all]` dependency conflict. [LangChain DeepAgents models](https://docs.langchain.com/oss/python/deepagents/models.md), [SAP LangChain examples](https://help.sap.com/doc/generative-ai-hub-sdk/CLOUD/en-US/_reference/gen_ai_hub.html), [PyPI sap-ai-sdk-gen JSON](https://pypi.org/pypi/sap-ai-sdk-gen/json)

1. Use Python 3.11+ because current DeepAgents requires it. [PyPI deepagents JSON](https://pypi.org/pypi/deepagents/json)
2. Install `deepagents==0.7.1` and `sap-ai-sdk-gen==7.2.0`, not `[all]`, for the first pass. [PyPI deepagents JSON](https://pypi.org/pypi/deepagents/json), [PyPI sap-ai-sdk-gen JSON](https://pypi.org/pypi/sap-ai-sdk-gen/json)
3. Export SAP AI Core credentials via `AICORE_CLIENT_ID`, `AICORE_CLIENT_SECRET`, `AICORE_AUTH_URL`, `AICORE_BASE_URL`, and `AICORE_RESOURCE_GROUP`. [SAP SDK README](https://help.sap.com/doc/generative-ai-hub-sdk/CLOUD/en-US/_reference/README_sphynx.html)
4. Run the `ChatOpenAI` snippet above with a deployed model such as `gpt-4o-mini`; first test `model.invoke()`, then `model.bind_tools()`, then `create_deep_agent(model=model, ...)`. [SAP LangChain examples](https://help.sap.com/doc/generative-ai-hub-sdk/CLOUD/en-US/_reference/gen_ai_hub.html), [LangChain DeepAgents quickstart](https://docs.langchain.com/oss/python/deepagents/quickstart.md)
5. If that succeeds, repeat with `sap-ai-sdk-gen[amazon]` and `ChatBedrockConverse` for Amazon/Anthropic deployments. Only move to `[all]` after the dependency conflict is resolved or an older DeepAgents pin is accepted. [SAP async examples](https://help.sap.com/doc/generative-ai-hub-sdk/CLOUD/en-US/_reference/async-examples.html), [PyPI deepagents JSON](https://pypi.org/pypi/deepagents/json), [PyPI sap-ai-sdk-gen JSON](https://pypi.org/pypi/sap-ai-sdk-gen/json)

## Risks and open questions

- Tool calling is the central runtime risk. DeepAgents requires tool-calling chat models, and SAP's wrappers inherit from LangChain chat model classes, but each target SAP deployment should be tested with `bind_tools()` because proxy/deployment/model support can differ. [LangChain DeepAgents models](https://docs.langchain.com/oss/python/deepagents/models.md), [sap-ai-sdk-gen 7.2.0 wheel](https://files.pythonhosted.org/packages/aa/34/1a908ceabe7d04406fa5f57f2c857b2f4aca003ea65762b0b9d7a678f275/sap_ai_sdk_gen-7.2.0-py3-none-any.whl)
- Current SAP Help pages observed during this research display SDK documentation version `v7.2.1`, while current PyPI metadata reports `sap-ai-sdk-gen==7.2.0`. Treat dependency conclusions as PyPI-current and check again before implementation. [SAP SDK README](https://help.sap.com/doc/generative-ai-hub-sdk/CLOUD/en-US/_reference/README_sphynx.html), [PyPI sap-ai-sdk-gen JSON](https://pypi.org/pypi/sap-ai-sdk-gen/json)
- DeepAgents provider strings should not be used for SAP models unless SAP or LangChain later publishes a provider integration accepted by LangChain `init_chat_model`; today the documented path is initialized model instances. [LangChain DeepAgents models](https://docs.langchain.com/oss/python/deepagents/models.md)
- SAP's `init_llm` is convenient but too broad as a type contract for DeepAgents. Prefer explicit chat wrappers for the prototype, or assert that `init_llm()` returned a `BaseChatModel` and can bind tools. [SAP LangChain examples](https://help.sap.com/doc/generative-ai-hub-sdk/CLOUD/en-US/_reference/gen_ai_hub.html), [sap-ai-sdk-gen 7.2.0 wheel](https://files.pythonhosted.org/packages/aa/34/1a908ceabe7d04406fa5f57f2c857b2f4aca003ea65762b0b9d7a678f275/sap_ai_sdk_gen-7.2.0-py3-none-any.whl)
- DeepAgents' default built-in tools include file operations and subagent delegation, and the project warns that agents can do anything their tools allow; constrain tools/backends deliberately when moving beyond a smoke test. [DeepAgents README in 0.7.1 sdist](https://files.pythonhosted.org/packages/88/e3/00c98c6b677ba89270b09dcb950848c794d507168b3dc53fa4d5cfb6a2e3/deepagents-0.7.1.tar.gz)
