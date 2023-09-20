"""Configuration for the OpenAI Conversation integration."""

DOMAIN = "augmented_openai_conversation"

CONF_SET_PROMPT = "set_prompt"
CONF_COMMAND_PROMPT = "command_prompt"
CONF_QUERY_PROMPT = "query_prompt"
CONF_HELP_PROMPT = "help_prompt"

CONF_CHAT_MODEL = "chat_model"
DEFAULT_CHAT_MODEL = "gpt-3.5-turbo-16k"

CONF_MAX_TOKENS = "max_tokens"
DEFAULT_MAX_TOKENS = 500

CONF_TOP_P = "top_p"
DEFAULT_TOP_P = 1

CONF_TEMPERATURE = "temperature"
DEFAULT_TEMPERATURE = 0.5
