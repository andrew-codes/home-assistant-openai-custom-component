"""Configuration for the OpenAI Conversation integration."""

import pkgutil

DOMAIN = "augmented_openai_conversation"

CONF_ENTITY_STATE_PROMPT = "entity_state_prompt"
CONF_SCRIPTS_PROMPT = "scripts_prompt"

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


def get_prompt(prompt_file_name: str) -> str:
    try:
        return pkgutil.get_data(__name__, "prompts/{prompt_file_name}.md".format(prompt_file_name=prompt_file_name)).decode("utf-8")
    except FileNotFoundError:
        return pkgutil.get_data(__name__, "prompts/{prompt_file_name}.md.j2".format(prompt_file_name=prompt_file_name)).decode("utf-8")
