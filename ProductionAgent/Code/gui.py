from __future__ import annotations

import html

import streamlit as st

from app_logging.agent_logger import LOGGER
from orchestrator import ProductionAgentOrchestrator


MEMORY_KEY = "production_agent_memory"
PROMPT_KEY = "production_agent_prompt"
ORCHESTRATOR_KEY = "production_agent_orchestrator"

# Added on 16.09.2026: UI-only welcome episode. It is never sent to LangGraph conversational context.
INITIAL_MEMORY_RECORD = {
    "request": "Welcome to ShopfloorAgent",
    "response": (
        "Ask me about the shopfloor using one of the supported capabilities:\n\n"
        "- Current production status and active incidents\n"
        "- Production statistics for a selected time period\n"
        "- Prior incident history\n"
        "- Official resolution instructions\n"
        "- Historical repair experience\n"
        "- Production impact for selected incidents\n"
        "- Detailed information for one incident\n\n"
        "Example: **Show me the current open incidents.**"
    ),
}


COLOR_PRIMARY = "#004643"
COLOR_SECONDARY = "#afcecc"
COLOR_FIELD_BACKGROUND = "#DCE7EE"
COLOR_LOG_BACKGROUND = "#E4F0EE"
COLOR_RESPONSE_BACKGROUND = "#edeae3"
COLOR_PANEL = "#ffffff"
COLOR_BORDER = "#000000"
COLOR_TEXT = "#000000"
COLOR_TEXT_MUTED = "#6B7280"
COLOR_TEXT_INVERSE = "#ffffff"


CSS = f"""
@import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&display=swap');

html,
body,
.stApp,
button,
input,
textarea,
[class*="css"] {{
    font-family: "Manrope", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif !important;
}}

header,
header[data-testid="stHeader"],
div[data-testid="stHeader"] {{
    display: none !important;
    height: 0 !important;
}}

.stApp {{
    background-color: {COLOR_PANEL};
    color: {COLOR_TEXT};
}}

.block-container {{
    max-width: 1480px;
    padding-top: 1.25rem;
    padding-bottom: 1.25rem;
    padding-left: 2rem;
    padding-right: 2rem;
}}

.shopfloor-title {{
    font-size: 2.15rem;
    font-weight: 800;
    letter-spacing: -0.025em;
    color: {COLOR_PRIMARY};
    line-height: 1.10;
    margin: 0.10rem 0 0.20rem 0;
}}

.shopfloor-subtitle {{
    font-size: 0.92rem;
    color: {COLOR_TEXT_MUTED};
    margin-bottom: 0.80rem;
}}

.panel-title {{
    font-size: 1.08rem;
    font-weight: 700;
    color: {COLOR_TEXT};
    margin: 0.15rem 0 0.35rem 0;
}}

.memory-content-shell {{
    border-radius: 0.55rem;
    padding: 0.10rem 0.10rem 0.20rem 0.10rem;
    margin-bottom: 0.55rem;
}}

.memory-request-box {{
    border: none;
    border-radius: 0.45rem;
    padding: 0.35rem 0.25rem 0.45rem 0.25rem;
    background-color: {COLOR_PANEL};
    font-size: 1.00rem;
    line-height: 1.36;
    white-space: normal;
    word-break: break-word;
}}

.memory-response-box {{
    border-radius: 0.45rem;
    padding: 0.55rem 0.70rem;
    border: 1.5px solid {COLOR_BORDER};
    background-color: {COLOR_RESPONSE_BACKGROUND};
    font-size: 1.00rem;
    line-height: 1.36;
    white-space: normal;
    word-break: break-word;
}}

.memory-label {{
    font-size: 0.92rem;
    font-weight: 800;
    margin-bottom: 0.25rem;
    color: {COLOR_PRIMARY};
    letter-spacing: 0.02em;
}}

.memory-plain-text {{
    white-space: pre-wrap;
    font-size: 1.00rem;
    line-height: 1.36;
    margin: 0;
    color: {COLOR_TEXT};
}}

.memory-empty {{
    color: {COLOR_TEXT_MUTED};
    text-align: center;
    padding: 2rem 0;
}}

.log-sink {{
    min-height: 185px;
    background-color: {COLOR_LOG_BACKGROUND};
    border-radius: 0.45rem;
    padding: 0.65rem 0.75rem;
    color: {COLOR_TEXT};
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    font-size: 0.76rem;
    line-height: 1.35;
    white-space: pre-wrap;
    word-break: break-word;
}}

.log-empty {{
    color: {COLOR_TEXT_MUTED};
    font-family: "Manrope", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}}

div[data-testid="stTextArea"] div[data-baseweb="textarea"] {{
    background-color: {COLOR_FIELD_BACKGROUND} !important;
    border: 1.5px solid {COLOR_BORDER} !important;
    border-radius: 0.45rem !important;
    box-shadow: none !important;
}}

div[data-testid="stTextArea"] div[data-baseweb="textarea"]:focus-within {{
    border-color: {COLOR_PRIMARY} !important;
    box-shadow: 0 0 0 1px {COLOR_SECONDARY} !important;
}}

div[data-testid="stTextArea"] textarea {{
    background-color: {COLOR_FIELD_BACKGROUND} !important;
    color: {COLOR_TEXT} !important;
}}

div[data-testid="stButton"] > button {{
    border-radius: 0.35rem !important;
    border: 1.5px solid {COLOR_BORDER} !important;
    font-weight: 800 !important;
}}

div[data-testid="stButton"] > button[kind="primary"] {{
    background-color: {COLOR_PRIMARY} !important;
    border-color: {COLOR_BORDER} !important;
    color: {COLOR_TEXT_INVERSE} !important;
}}

div[data-testid="stButton"] > button[kind="primary"] p {{
    color: {COLOR_TEXT_INVERSE} !important;
    font-weight: 800 !important;
}}
"""


def _ensure_session_state() -> None:
    if MEMORY_KEY not in st.session_state:
        st.session_state[MEMORY_KEY] = [dict(INITIAL_MEMORY_RECORD)]

    if PROMPT_KEY not in st.session_state:
        st.session_state[PROMPT_KEY] = ""

    # One orchestrator per Streamlit session keeps LangGraph State alive
    # across reruns and clarification turns.
    if ORCHESTRATOR_KEY not in st.session_state:
        st.session_state[ORCHESTRATOR_KEY] = ProductionAgentOrchestrator()


def _submit_prompt() -> None:
    prompt = str(st.session_state.get(PROMPT_KEY, "") or "").strip()
    if not prompt:
        return

    orchestrator: ProductionAgentOrchestrator = st.session_state[ORCHESTRATOR_KEY]
    response = orchestrator.run(prompt)

    st.session_state[MEMORY_KEY].append(
        {
            "request": prompt,
            "response": response,
        }
    )
    st.session_state[PROMPT_KEY] = ""


def _render_memory_record(request: str, response: str) -> None:
    """Render the request plainly and let Streamlit render response Markdown."""
    request_html = html.escape(request).replace("\n", "<br>")

    st.markdown(
        '<div class="memory-content-shell">'
        '<div class="memory-request-box">'
        '<div class="memory-label">REQUEST</div>'
        f'<div class="memory-plain-text">{request_html}</div>'
        '</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    with st.container(border=True):
        st.markdown('<div class="memory-label">RESPONSE</div>', unsafe_allow_html=True)
        st.markdown(response)


def _render_memory() -> None:
    st.markdown('<div class="panel-title">Memory</div>', unsafe_allow_html=True)

    with st.container(height=760, border=True, autoscroll=True):
        records = st.session_state[MEMORY_KEY]

        if not records:
            # Added on 16.09.2026: never show an unfinished empty-memory placeholder.
            _render_memory_record(
                request=INITIAL_MEMORY_RECORD["request"],
                response=INITIAL_MEMORY_RECORD["response"],
            )
            return

        for record in records:
            _render_memory_record(
                request=str(record.get("request", "")),
                response=str(record.get("response", "")),
            )


def _render_prompt() -> None:
    st.markdown('<div class="panel-title">Prompt</div>', unsafe_allow_html=True)

    st.text_area(
        "Prompt",
        key=PROMPT_KEY,
        height=220,
        placeholder="Write your request here...",
        label_visibility="collapsed",
    )
    st.button(
        "Send",
        type="primary",
        use_container_width=True,
        on_click=_submit_prompt,
    )


def _render_log_sink(channel: str, max_lines: int) -> None:
    log_text = LOGGER.read_tail(channel, max_lines=max_lines)
    if not log_text:
        log_text = "No log entries yet."
        css_class = "log-sink log-empty"
    else:
        css_class = "log-sink"

    rendered = html.escape(log_text)
    with st.container(height=225, border=True, autoscroll=True):
        st.markdown(
            f'<div class="{css_class}">{rendered}</div>',
            unsafe_allow_html=True,
        )


def _render_logs() -> None:
    st.markdown('<div class="panel-title">Logs</div>', unsafe_allow_html=True)
    normal_tab, developer_tab = st.tabs(["Normal", "Developer"])

    with normal_tab:
        _render_log_sink("normal", max_lines=60)

    with developer_tab:
        _render_log_sink("developer", max_lines=180)


def run_gui() -> None:
    _ensure_session_state()

    st.markdown(f"<style>{CSS}</style>", unsafe_allow_html=True)

    controls_column, memory_column = st.columns([0.30, 0.70], gap="large")

    with controls_column:
        st.markdown(
            '<div class="shopfloor-title">ShopfloorAgent</div>'
            '<div class="shopfloor-subtitle">ProductionAgent</div>',
            unsafe_allow_html=True,
        )
        st.markdown('<div style="height:1.10rem"></div>', unsafe_allow_html=True)
        _render_prompt()
        st.markdown('<div style="height:0.75rem"></div>', unsafe_allow_html=True)
        _render_logs()

    with memory_column:
        _render_memory()
