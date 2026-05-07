# LLM Task Extraction

TeamTask can use an OpenAI-compatible chat-completions endpoint for demo task extraction. The default remains `rule`, so local tests and mock demos do not require a model API.

## Modes

- `TASK_EXTRACTOR_BACKEND=rule`: use deterministic keyword, regex, participant, URL, and date extraction.
- `TASK_EXTRACTOR_BACKEND=llm`: call the configured LLM first.
- `TASK_EXTRACTOR_BACKEND=auto`: call the LLM only when model configuration is present; otherwise use the rule extractor.

`TASK_EXTRACTOR_LLM_FALLBACK=true` keeps the demo resilient. If the LLM is unavailable, TeamTask falls back to the rule extractor and still completes the flow.

## Configuration

```dotenv
TASK_EXTRACTOR_BACKEND=llm
TASK_EXTRACTOR_LLM_FALLBACK=true
LLM_TASK_API_BASE=https://api.openai.com/v1
LLM_TASK_API_KEY=your_key
LLM_TASK_MODEL=your_model
LLM_TASK_PROMPT_PATH=prompts/extract_tasks.md
LLM_TASK_RESPONSE_FORMAT=json_object
LLM_TASK_TIMEOUT_SECONDS=30
LLM_TASK_MAX_INPUT_CHARS=20000
LLM_TASK_TEMPERATURE=0
```

The implementation uses `POST {LLM_TASK_API_BASE}/chat/completions` with a JSON-object response. Any compatible provider can be used if it accepts the same request shape.

Some OpenAI-compatible providers do not support `response_format={"type":"json_object"}`. For Ark models that reject this parameter, set:

```dotenv
LLM_TASK_RESPONSE_FORMAT=none
```

TeamTask also retries once without `response_format` when the provider returns a 400 saying that `response_format` is not supported or not valid.

## Prompt Boundary

The prompt lives in `prompts/extract_tasks.md`. It asks the model to return only:

```json
{
  "task_candidates": []
}
```

Each candidate must match `TaskCandidate`: title, description, initiator, assignee, deadline, evidence, missing fields, resources, and confidence.

The LLM does not control state transitions, card action keys, database ids, Todo writes, or permissions. It only proposes task candidates; the existing state machine, confirmation cards, guards, and Todo Projection workflow remain the authority.
