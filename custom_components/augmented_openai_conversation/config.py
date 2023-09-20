"""Configuration for the OpenAI Conversation integration."""

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
