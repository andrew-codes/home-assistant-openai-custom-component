"""Configuration for the OpenAI Conversation integration."""

import pkgutil

DOMAIN = "augmented_openai_conversation"
CONF_PROMPT = "prompt"

CONF_LOCATION = "location"
DEFAULT_LOCATION = "US"

CONF_CHAT_MODEL = "chat_model"
DEFAULT_CHAT_MODEL = "gpt-3.5-turbo"

CONF_MAX_TOKENS = "max_tokens"
DEFAULT_MAX_TOKENS = 150

CONF_TOP_P = "top_p"
DEFAULT_TOP_P = 1

CONF_TEMPERATURE = "temperature"
DEFAULT_TEMPERATURE = 0.5


def get_setup_prompt() -> str:
    return pkgutil.get_data(__name__, "prompts/setup_prompt.md.j2").decode("utf-8")


def get_user_request_prompt() -> str:
    return pkgutil.get_data(__name__, "prompts/user_request_prompt.md.j2").decode("utf-8")


def get_entity_states_prompt() -> str:
    return pkgutil.get_data(__name__, "prompts/entity_states_prompt.md.j2").decode("utf-8")
