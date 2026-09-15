# ShopfloorAgent LangGraph Functional Requirements

**Status:** Implementation baseline  
**Purpose:** Define the functional LangGraph architecture to be implemented for the ShopfloorAgent PoC.  
**Scope:** LangGraph state, nodes, routing, tool orchestration, clarification/re-entry, result hand-offs, and response preparation.  
**Deferred to supplementary requirements:** Exact response wording, exact JSON template files, prompt text, helper-class structure, detailed formatting rules, and other low-level implementation choices.

---

## 1. Authority and source basis

This document consolidates the current LangGraph architecture after the design captured in Collection Episode 13 and the Astra 6 Very High architecture audit captured in Episode 14.

Authority order for the underlying design remains:

1. This implementation-baseline document, once adopted.
2. Episode 13 consolidated requirements (M200-M209).
3. Earlier LangGraph Collection material, especially Episode 12.
4. Episode 10 for the canonical seven-tool MCP contract and client/MCP responsibility split.
5. Implemented MES/MCP Python remains the source of truth for what the existing MES and MCP tools actually do.

Episode 14 identified three small but genuine integration gaps. They are accepted here as part of the final baseline:

- explicit active tool-argument hand-off: `current_tool_arguments`
- explicit post-processing-to-response hand-off: `response_payload`
- explicit pending interaction marker: `pending_interaction`

No new LangGraph node is introduced by these corrections.

---

## 2. Design objective

The LangGraph must provide a small, understandable orchestration layer around the deterministic MES/MCP implementation.

The design must:

- accept natural-language requests from the GUI/API
- select exactly one of the seven canonical MCP tools for the current operation
- resolve and validate tool arguments
- execute the selected MCP tool deterministically
- preserve the raw tool result
- post-process the result where required
- render a user-facing response
- support controlled clarification loops across user turns
- preserve conversational focus across normal turns
- allow an unfinished interaction to be resumed or abandoned without undefined routing

The design must not introduce unnecessary autonomous planning, additional agents, or extra graph nodes merely to appear more sophisticated.

---

## 3. Out of scope for this baseline

The following are intentionally not requirements of this functional architecture document:

- deployment architecture
- authentication and authorization
- governance
- observability and production monitoring
- infrastructure hardening
- frontend robustness
- generic production error-handling policy
- exact Python helper functions or class layout
- exact LLM prompt wording
- exact deterministic response text
- exact JSON template filenames and schema details beyond the minimum hand-off contract
- broader autonomous multi-tool planning

A later supplementary LangGraph requirements document will define detailed response-template content and similar implementation-level behavior.

---

## 4. Canonical graph structure

The graph contains the following business nodes:

1. `REQUEST`
2. `SELECTOR`
3. `ARGUMENT_RESOLVER`
4. `EXECUTION`
5. `POST_PROCESSING`
6. `RESPONSE`

Normal happy path:

```text
GUI/API
   |
   v
REQUEST
   |
   v
SELECTOR
   |
   v
ARGUMENT_RESOLVER
   |
   v
EXECUTION
   |
   v
POST_PROCESSING
   |
   v
RESPONSE
   |
   v
END / API / GUI
```

LangGraph `START` and `END` are framework boundaries, not additional business nodes.

No additional node is required for the accepted Astra corrections.

---

## 5. Phase model

`phase` is an enum with the following values:

```text
RESET
WAITING_FOR_INPUT
INPUT_RECEIVED
TOOL_SELECTED
TOOL_READY
TOOL_DONE
FINISHED
FAILED
```

### 5.1 Phase semantics

- `RESET` — complete deterministic default state.
- `WAITING_FOR_INPUT` — the current graph run has ended, but the conversation contains an unfinished interaction awaiting user input.
- `INPUT_RECEIVED` — the newest user request has been received by `REQUEST`.
- `TOOL_SELECTED` — `SELECTOR` has selected a valid MCP tool.
- `TOOL_READY` — the selected tool has a complete, validated argument dictionary ready for execution.
- `TOOL_DONE` — the MCP tool executed successfully and its raw result is stored.
- `FINISHED` — the current user operation completed normally. This is not a reset.
- `FAILED` — the current graph operation has failed in a way that prevents normal completion.

---

## 6. Pending interaction model

`pending_interaction` is a dedicated enum that identifies unfinished conversational work across graph invocations.

```text
NONE
SELECTOR_CLARIFICATION
ARGUMENT_CLARIFICATION
REPAIR_PRESENTATION
```

Its only responsibility is to answer:

> What unfinished interaction, if any, is waiting for the user's next message?

It does not duplicate the data needed by that interaction. The data remains in the appropriate State fields.

### 6.1 Re-entry contract

| `pending_interaction` | Meaning | Next-user-message route |
|---|---|---|
| `NONE` | No unfinished interaction | `REQUEST -> SELECTOR` |
| `SELECTOR_CLARIFICATION` | The graph could not select a tool and asked the user to clarify | `REQUEST -> SELECTOR` |
| `ARGUMENT_CLARIFICATION` | A tool is selected but required arguments are missing/invalid | `REQUEST -> ARGUMENT_RESOLVER` |
| `REPAIR_PRESENTATION` | Repair experience has already executed and the user must choose presentation mode | `REQUEST -> POST_PROCESSING` when the reply is a valid presentation choice |

### 6.2 Abandonment of pending work

The user may replace an unfinished interaction with a clearly new request.

Example:

```text
System: Latest 3, summarize all, or show all?
User: Actually, show current status.
```

The old pending interaction must be abandoned. The new request must be treated as a fresh operation and routed through `SELECTOR`.

For `REPAIR_PRESENTATION`, only the recognized presentation choices continue directly to `POST_PROCESSING`; a clearly different request abandons the presentation interaction and routes to `SELECTOR`.

For selector or argument clarification, the receiving decision node may determine that the new user message replaces the unfinished request. In that case the old pending work is cleared and the new request proceeds through normal selection.

Exact wording/classification prompts are deferred to the supplementary implementation requirements.

---

## 7. LangGraph State

The implementation State must contain the following fields.

### 7.1 Control fields

#### `phase`

```text
RESET | WAITING_FOR_INPUT | INPUT_RECEIVED | TOOL_SELECTED |
TOOL_READY | TOOL_DONE | FINISHED | FAILED
```

#### `pending_interaction`

```text
NONE | SELECTOR_CLARIFICATION | ARGUMENT_CLARIFICATION | REPAIR_PRESENTATION
```

#### `clarification_attempts`

```text
int
```

Tracks consecutive unsuccessful clarification attempts for the active clarification stage.

---

### 7.2 Request and conversation fields

#### `current_request`

```text
str | None
```

The newest user message received by `REQUEST`.

#### `recent_history`

A list containing up to the previous two completed user/assistant turns.

Assistant prose is conversational context only. It is not the authoritative source for MES facts.

---

### 7.3 Active tool-operation fields

#### `current_tool`

```text
None |
get_status |
get_incident_details |
get_production_statistics |
list_prior_incidents |
get_resolution_instructions |
get_repair_experience |
calculate_production_impact
```

`None` is not a tool enum member; it means no active tool is selected.

#### `current_tool_arguments`

```text
dict | None
```

The active invocation dictionary for `current_tool`.

Responsibilities:

- written by `ARGUMENT_RESOLVER`
- may contain partial values while an argument clarification is pending
- must be complete and valid before `phase = TOOL_READY`
- read by `EXECUTION`
- the exact executed argument dictionary is copied into `tool_history`
- rebuilt/cleared when a different operation replaces the current one
- cleared on full `RESET`

This field is intentionally separate from persistent conversational focus. A tool invocation may contain values, such as `station_ids`, that are not persistent State focus fields.

#### `current_tool_result`

```text
dict | None
```

The raw result of the most recently executed MCP tool.

Responsibilities:

- written only after successful `EXECUTION`
- read by `POST_PROCESSING`
- remains a raw factual MCP result
- must not be overwritten with summaries or rendered user text
- may be retained while `REPAIR_PRESENTATION` is pending

#### `response_payload`

```text
dict | None
```

Structured information prepared for `RESPONSE` after selection/resolution/post-processing decisions.

Minimum conceptual structure:

```text
{
  "kind": <response/presentation kind>,
  "data": <structured or generated content>
}
```

Responsibilities:

- may be written by nodes that need `RESPONSE` to render something
- is the primary hand-off from `POST_PROCESSING` to `RESPONSE`
- may carry a generated summary, formatted result data, clarification metadata, presentation-choice metadata, incident-not-found information, reset/support information, or similar response-driving data
- does not replace `current_tool_result`
- exact `kind` values and exact template schema are deferred to the supplementary requirements

---

### 7.4 Tool history

#### `tool_history`

A list of successful tool executions.

Each entry contains:

```text
{
  "tool_name": ...,
  "arguments": ...,
  "result": ...
}
```

Only successful executions are added.

`tool_history` is historical evidence. `current_tool_result` is the active raw result for the current operation.

---

### 7.5 Conversational focus fields

#### `open_incidents`

```text
None | [] | [incident_ids]
```

Semantics:

- `None` — status has not been checked / open-incident state is unknown
- `[]` — status has been checked and there are no open incidents
- non-empty list — status has been checked and open incidents exist

`open_incidents` is authoritative only when derived from `get_status`.

#### `selected_incident_ids`

List of incident IDs representing current conversational focus.

#### `selected_line_ids`

List of selected line IDs.

#### `selected_error_ids`

List of selected error IDs.

#### `selected_date_range`

```text
None | {
  "date_from": ...,
  "date_to": ...
}
```

There is intentionally no persistent `selected_station_ids` field.

Station filters may exist in `current_tool_arguments` for individual tool calls without becoming persistent conversational focus.

---

## 8. RESET invariant

When `phase == RESET`, State must deterministically equal:

```text
phase = RESET
pending_interaction = NONE
clarification_attempts = 0

current_request = None
recent_history = []

current_tool = None
current_tool_arguments = None
current_tool_result = None
response_payload = None

tool_history = []

open_incidents = None
selected_incident_ids = []
selected_line_ids = []
selected_error_ids = []
selected_date_range = None
```

A true reset clears persistent conversational focus and history.

A normal `FINISHED` state is not a reset.

When a reset-support message must still be returned to the user, the implementation may render that terminal message as the current run's output after the persisted State has been reset. The reset-support response must not repopulate history that RESET is intended to clear.

---

## 9. State persistence and lifecycle rules

### 9.1 Persistent across normal completed turns

The following conversational-focus fields persist until explicitly changed or reset:

- `open_incidents`
- `selected_incident_ids`
- `selected_line_ids`
- `selected_error_ids`
- `selected_date_range`

Explicit user focus changes overwrite the relevant selected focus.

### 9.2 Current-operation fields

The following fields describe the active/recent operation rather than durable conversational focus:

- `current_tool`
- `current_tool_arguments`
- `current_tool_result`
- `response_payload`
- `pending_interaction`
- `clarification_attempts`

A fresh unrelated request may replace these fields as needed.

Stale `current_tool` or `current_tool_result` must never by themselves cause re-entry into an old path. Cross-turn routing is controlled by `pending_interaction`.

### 9.3 Clarification counter lifecycle

- selector clarification increments `clarification_attempts`
- after successful tool selection, the selector-stage counter resets before argument resolution
- argument clarification increments `clarification_attempts`
- after successful argument resolution, the argument-stage counter resets before execution
- valid repair-presentation choices do not increment `clarification_attempts`
- full RESET sets the counter to `0`

Selector clarification limit:

```text
3 unsuccessful attempts
```

After the third unsuccessful selector clarification:

- inform the user
- perform full RESET
- return deterministic reset/support output

Argument clarification limit:

```text
5 unsuccessful attempts
```

After the fifth unsuccessful argument clarification:

- inform the user
- perform full RESET
- return deterministic reset/support output

---

## 10. Node requirements

## 10.1 REQUEST

### Responsibility

`REQUEST` is the GUI/API entry node.

It must:

1. receive the newest user text
2. set `current_request`
3. set `phase = INPUT_RECEIVED`
4. inspect `pending_interaction` before treating the message as a completely fresh request
5. route the request according to the re-entry contract

### Normal route

When:

```text
pending_interaction = NONE
```

route:

```text
REQUEST -> SELECTOR
```

### Re-entry routes

```text
SELECTOR_CLARIFICATION -> SELECTOR
ARGUMENT_CLARIFICATION -> ARGUMENT_RESOLVER
REPAIR_PRESENTATION -> POST_PROCESSING, only for a valid presentation reply
```

A fresh replacement request abandons pending work and proceeds to `SELECTOR`.

`REQUEST` itself is not a general LLM reasoning node.

---

## 10.2 SELECTOR

### Responsibility

`SELECTOR` is the first LLM decision node.

It receives:

- `current_request`
- relevant recent conversational context
- the canonical list of seven MCP tools
- tool-selection instructions

It selects exactly one tool.

It does not resolve arguments.

### Success

On success:

```text
current_tool = selected tool
phase = TOOL_SELECTED
pending_interaction = NONE
clarification_attempts = 0
```

Then:

```text
SELECTOR -> ARGUMENT_RESOLVER
```

### Selection clarification

If a valid tool cannot be selected:

```text
clarification_attempts += 1
pending_interaction = SELECTOR_CLARIFICATION
phase = WAITING_FOR_INPUT
```

Prepare a deterministic clarification `response_payload` and route to `RESPONSE`.

If the selector succeeds on a later user reply, the normal path resumes.

After three unsuccessful selector clarification attempts, perform full reset and return reset/support output.

---

## 10.3 ARGUMENT_RESOLVER

### Responsibility

`ARGUMENT_RESOLVER` receives the selected tool and resolves its arguments from:

- `current_request`
- retained focus State
- recent conversational context
- partial `current_tool_arguments`, when continuing an argument clarification
- tool-specific argument instructions/schema

It may use an LLM/synthesizer to extract or infer user-provided arguments, but the final validation gate is deterministic.

### Active argument hand-off

All active tool arguments must be stored in:

```text
current_tool_arguments
```

This includes partial arguments retained across clarification turns.

### Deterministic validation

Before `TOOL_READY`, validate as applicable:

- required vs optional arguments
- defined defaults
- expected scalar vs list shape
- omitted filters vs empty lists
- duplicate identifiers
- malformed identifiers
- `line_ids` against known valid values where available
- `error_ids` against known valid values where available
- date format
- `date_from <= date_to`
- strictly positive intervals when required by the underlying tool contract
- invalid/future dates where those are not allowed
- required dates for tools that require them
- singular vs list conversion according to the selected tool contract

`incident_id` existence is not prevalidated. A syntactically acceptable incident ID may be executed by `get_incident_details`; `{"incident": None}` is handled later in `POST_PROCESSING`.

### Success

Only when the exact argument dictionary satisfies the selected tool contract:

```text
phase = TOOL_READY
pending_interaction = NONE
clarification_attempts = 0
```

Then:

```text
ARGUMENT_RESOLVER -> EXECUTION
```

### Missing/invalid required arguments

When required information is still missing:

- preserve already resolved values in `current_tool_arguments`
- increment `clarification_attempts`
- set `pending_interaction = ARGUMENT_CLARIFICATION`
- set `phase = WAITING_FOR_INPUT`
- prepare `response_payload` describing only the missing information that must be requested
- route to `RESPONSE`

On the next user message:

```text
REQUEST -> ARGUMENT_RESOLVER
```

The resolver continues from retained `current_tool` and partial `current_tool_arguments`.

### Special rule: `get_incident_details`

If `current_tool == get_incident_details`:

- if `incident_id` exists, keep `get_incident_details`
- if `incident_id` is missing, replace `current_tool` deterministically with `get_status`
- rebuild `current_tool_arguments` for `get_status` as the no-argument invocation
- do not ask the user for an incident ID merely because current incident details were requested without one

For historical incident detail, the user must either provide an explicit incident ID or first obtain/select one through `list_prior_incidents`.

### Special rule: `get_repair_experience`

`error_id` is required.

`line_ids` is only an optional filter.

If the user asks only for a line and no error ID is available from current context:

- retain the resolved line filter
- do not invent an error ID
- do not execute the tool
- ask specifically for the required error ID through the normal argument-clarification path

---

## 10.4 EXECUTION

### Responsibility

`EXECUTION` is deterministic and contains no LLM decision-making.

Precondition:

```text
phase = TOOL_READY
current_tool != None
current_tool_arguments is complete and valid
```

On successful execution:

1. execute `current_tool` with `current_tool_arguments`
2. store the raw dictionary in `current_tool_result`
3. append the successful execution to `tool_history`:

```text
{
  "tool_name": current_tool,
  "arguments": current_tool_arguments,
  "result": current_tool_result
}
```

4. set:

```text
phase = TOOL_DONE
```

5. route:

```text
EXECUTION -> POST_PROCESSING
```

---

## 10.5 POST_PROCESSING

### Responsibility

`POST_PROCESSING` reads `current_tool_result` and prepares the semantic/presentation result required by `RESPONSE`.

Default behavior is deterministic.

Use an LLM only where explicitly justified, currently including repair-experience summarization when the user selects summarization.

`POST_PROCESSING` must preserve `current_tool_result` as raw MCP evidence and write derived information to:

```text
response_payload
```

### Incident not found

If:

```text
current_tool == get_incident_details
current_tool_result == {"incident": None}
```

prepare a deterministic incident-not-found response payload.

### Repair-experience result handling

If `get_repair_experience` returns one to three experiences:

- prepare deterministic output
- write `response_payload`
- route to `RESPONSE`

If it returns more than three experiences:

- retain the complete raw `current_tool_result`
- prepare a deterministic presentation-choice `response_payload`
- set:

```text
pending_interaction = REPAIR_PRESENTATION
phase = WAITING_FOR_INPUT
```

- route to `RESPONSE`

The user is offered three choices:

```text
latest 3
summarize all
show all
```

When the next user message is a valid choice:

```text
REQUEST -> POST_PROCESSING
```

Bypass:

```text
SELECTOR
ARGUMENT_RESOLVER
EXECUTION
```

because the raw result already exists.

Presentation behavior:

- `latest 3` — deterministic selection/formatting
- `show all` — deterministic selection/formatting
- `summarize all` — LLM summarization of the complete retained experience set

After a valid choice is processed:

```text
pending_interaction = NONE
```

Write final `response_payload` and route to `RESPONSE`.

If the user instead clearly requests a different operation, abandon the repair-presentation interaction and route the new request through `SELECTOR`.

---

## 10.6 RESPONSE

### Responsibility

`RESPONSE` is the GUI/API exit node.

It consumes `response_payload` and produces the final user-visible text.

Routing/business logic remains in Python/LangGraph.

Deterministic response wording is stored externally in separate JSON response-template files where appropriate.

Examples of deterministic template categories include:

- selector clarification
- argument clarification
- retry messages
- reset/support messages
- incident-not-found responses
- repair-presentation choice prompts
- other fixed system responses

Dynamic content does not require a fixed JSON response body when direct structured rendering is more appropriate.

Exact template inventory, wording, placeholders, and filenames are deferred to the supplementary LangGraph response requirements.

### Completion behavior

If more user input is required:

```text
phase = WAITING_FOR_INPUT
RESPONSE -> END / API / GUI
```

The graph invocation ends while the conversational interaction remains pending.

If the operation is complete:

```text
phase = FINISHED
pending_interaction = NONE
RESPONSE -> END / API / GUI
```

`RESPONSE` has an unconditional graph exit to `END` after it has constructed the current output.

---

## 11. Canonical MCP tool contracts used by LangGraph

The graph may select only these seven tools.

### 11.1 `get_status`

```text
arguments: none
```

Used for current plant/line status and discovery of current open incidents.

When open incidents exist, the implemented tool already returns complete current open-incident details required by the current-detail workflow.

### 11.2 `get_production_statistics`

Required:

```text
date_from
date_to
line_ids
```

`line_ids` must be non-empty.

### 11.3 `list_prior_incidents`

Optional filters:

```text
date_from
date_to
line_ids
station_ids
error_ids
```

Generic incident listing requires no clarification merely because filters are omitted.

### 11.4 `get_resolution_instructions`

Optional:

```text
error_ids
```

Important distinction:

- omitted `error_ids` means derive instructions for current open incident error types
- empty `error_ids` means no requested error IDs

The resolver must preserve tool-specific omitted-vs-empty semantics.

### 11.5 `get_repair_experience`

Required:

```text
error_id
```

Optional:

```text
date_from
date_to
line_ids
```

No station filter.

Only repaired historical incidents are returned.

### 11.6 `calculate_production_impact`

Required:

```text
error_id
date_from
date_to
line_ids
```

Exactly one error ID is used for the operation.

### 11.7 `get_incident_details`

Required:

```text
incident_id
```

A nonexistent ID may validly return:

```json
{"incident": null}
```

and is handled deterministically by `POST_PROCESSING`.

---

## 12. Main routing requirements

### 12.1 Happy path

```text
REQUEST
 -> SELECTOR
 -> ARGUMENT_RESOLVER
 -> EXECUTION
 -> POST_PROCESSING
 -> RESPONSE
 -> END
```

### 12.2 Selector clarification

```text
REQUEST
 -> SELECTOR
 -> RESPONSE
 -> END

next user message:
REQUEST
 -> SELECTOR
```

Controlled by:

```text
pending_interaction = SELECTOR_CLARIFICATION
```

### 12.3 Argument clarification

```text
REQUEST
 -> SELECTOR
 -> ARGUMENT_RESOLVER
 -> RESPONSE
 -> END

next user message:
REQUEST
 -> ARGUMENT_RESOLVER
```

Controlled by:

```text
pending_interaction = ARGUMENT_CLARIFICATION
```

Retained active data:

```text
current_tool
current_tool_arguments
```

### 12.4 Repair-presentation loop

```text
EXECUTION
 -> POST_PROCESSING
 -> RESPONSE
 -> END

next user message, valid presentation choice:
REQUEST
 -> POST_PROCESSING
 -> RESPONSE
 -> END
```

Controlled by:

```text
pending_interaction = REPAIR_PRESENTATION
```

Retained active data:

```text
current_tool_result
```

### 12.5 Abandon pending interaction

```text
pending interaction exists
new user message clearly starts a different operation
 -> clear/replace pending current-operation context as applicable
 -> pending_interaction = NONE
 -> SELECTOR
```

Conversational focus fields are not globally reset merely because pending work is abandoned.

### 12.6 Explicit reset

```text
explicit reset / clarification-limit reset
 -> full RESET invariant
 -> terminal reset/support response when applicable
```

---

## 13. Information ownership and hand-off rules

The implementation must maintain these boundaries:

```text
ARGUMENT_RESOLVER
    |
    | current_tool_arguments
    v
EXECUTION
    |
    | current_tool_result
    v
POST_PROCESSING
    |
    | response_payload
    v
RESPONSE
```

Across user turns:

```text
RESPONSE / END
    |
    | pending_interaction
    v
next user message
    |
    v
REQUEST
    |
    +--> SELECTOR
    +--> ARGUMENT_RESOLVER
    +--> POST_PROCESSING
```

These four hand-off concepts must not be collapsed into one ambiguous object:

- `current_tool_arguments` — exact active invocation
- `current_tool_result` — raw MCP fact/result
- `response_payload` — processed information to render
- `pending_interaction` — cross-turn routing marker

---

## 14. Functional invariants

The implementation must satisfy all of the following:

1. `SELECTOR` selects tools; it does not resolve tool arguments.
2. `ARGUMENT_RESOLVER` resolves and validates arguments; it does not execute MCP tools.
3. `EXECUTION` performs deterministic MCP execution and does not perform LLM reasoning.
4. `POST_PROCESSING` never destroys or rewrites the raw MCP result.
5. `RESPONSE` renders; routing logic remains in LangGraph/Python.
6. `TOOL_READY` is reachable only with a complete valid `current_tool_arguments` for the selected tool.
7. `TOOL_DONE` is reachable only after successful MCP execution with a stored raw result.
8. A stale `current_tool` or `current_tool_result` alone must never force a future user message into an old path.
9. Cross-turn continuation is controlled explicitly by `pending_interaction`.
10. Full RESET clears all State to the RESET defaults.
11. Normal completion preserves conversational focus and does not imply RESET.
12. `open_incidents` is distinct from selected conversational incident focus.
13. No separate alarm State variable is required; alarm/current-open-incident meaning is derived from authoritative status information.
14. No separate intent classifier node is required.
15. No persistent `station_ids` focus field is required; station filters belong in the active argument dictionary when used.
16. Repair-experience summarization is the current explicit case where post-processing may use an LLM after deterministic MCP execution.
17. A user can abandon any pending interaction and start a fresh operation without resetting unrelated conversational focus.

---

## 15. Initial implementation acceptance journeys

The first implementation should demonstrate at least the following journeys.

### Journey A — Normal status request

```text
User -> REQUEST -> SELECTOR(get_status) -> ARGUMENT_RESOLVER -> EXECUTION
-> POST_PROCESSING -> RESPONSE -> FINISHED
```

### Journey B — Tool-selection clarification

- ambiguous request
- selector asks for clarification
- `pending_interaction = SELECTOR_CLARIFICATION`
- user clarifies
- request returns to selector
- selected tool continues through normal path

### Journey C — Argument clarification with retained partial scope

Example:

```text
User: Show repair experience for Line 2.
```

Expected:

- select `get_repair_experience`
- retain `line_ids = [2]` in `current_tool_arguments`
- identify missing `error_id`
- ask only for the missing error ID
- user supplies error ID
- resume `ARGUMENT_RESOLVER`
- combine retained line scope with new error ID
- validate and execute

### Journey D — Missing current incident ID fallback

Example:

```text
User: Tell me the details of the current incident.
```

Expected:

- selector chooses `get_incident_details`
- resolver finds no incident ID
- resolver replaces tool with `get_status`
- no incident-ID clarification loop occurs
- current incident information is obtained from status result

### Journey E — Unknown historical incident ID

- user supplies an explicit historical incident ID
- `get_incident_details` executes
- tool returns `{"incident": None}`
- post-processing creates deterministic not-found payload
- response renders it

### Journey F — Repair experience, more than three records

- execute `get_repair_experience`
- post-processing detects more than three records
- ask latest 3 / summarize all / show all
- set `pending_interaction = REPAIR_PRESENTATION`
- user selects one option
- re-enter `POST_PROCESSING` without re-executing MCP
- return requested presentation

### Journey G — Abandon repair presentation

- repair-presentation choice is pending
- user instead asks for current status
- old presentation interaction is abandoned
- new request routes through selector
- no stale tool result captures the new request

### Journey H — Selector clarification limit

- three unsuccessful selector clarification attempts
- deterministic support/reset response
- full RESET state

### Journey I — Argument clarification limit

- five unsuccessful argument clarification attempts
- deterministic support/reset response
- full RESET state

### Journey J — Focus persistence

- user selects an incident/line/error/date context
- one operation finishes
- next related request can use retained focus
- a true RESET clears that focus

---

## 16. Deferred supplementary decisions

The following should be specified after the first LangGraph implementation skeleton exists:

- exact JSON response-template inventory
- exact JSON filenames and directory layout
- exact response wording
- exact `response_payload.kind` enum/strings
- template placeholder naming
- exact selector prompt
- exact argument-resolver prompt per tool
- exact wording for clarification questions
- exact logic for recognizing an explicit replacement request in ambiguous natural language
- detailed result-formatting rules per MCP tool
- detailed relative-time interpretation such as "today" or "last hour"

If relative-time language is later supported, it must be anchored deliberately to the simulated MES time model rather than silently assuming the host wall-clock time.

---

## 17. Implementation-readiness conclusion

With the three accepted integration corrections now incorporated:

- `current_tool_arguments`
- `response_payload`
- `pending_interaction`

there is no known need for another LangGraph business node or broad architectural redesign.

The functional architecture is sufficiently defined to begin implementation of the LangGraph skeleton and the core routing/state behavior.

The next useful step is implementation, followed by a supplementary requirements pass for exact response JSONs, prompt wording, and presentation details once the concrete graph structure exists.
