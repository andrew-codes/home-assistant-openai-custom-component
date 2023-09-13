"""The OpenAI Conversation integration."""
from __future__ import annotations

from functools import partial
import logging
from typing import Literal

import openai
from openai import error
import voluptuous as vol

from homeassistant.components import conversation
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY, MATCH_ALL
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import (
    ConfigEntryNotReady,
    HomeAssistantError,
    TemplateError,
)
from homeassistant.helpers import config_validation as cv, intent, selector, template
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import ulid

import json
from datetime import datetime, timedelta

from .config import (
    CONF_CHAT_MODEL,
    CONF_MAX_TOKENS,
    CONF_PROMPT,
    CONF_TEMPERATURE,
    CONF_LOCATION,
    CONF_TOP_P,
    DEFAULT_CHAT_MODEL,
    DEFAULT_MAX_TOKENS,
    DEFAULT_TEMPERATURE,
    DEFAULT_LOCATION,
    DEFAULT_TOP_P,
    DOMAIN,
    get_entity_states_prompt,
    get_setup_prompt,
)

_LOGGER = logging.getLogger(__name__)
SERVICE_GENERATE_IMAGE = "generate_image"

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up OpenAI Conversation."""

    async def render_image(call: ServiceCall) -> ServiceResponse:
        """Render an image with dall-e."""
        try:
            response = await openai.Image.acreate(
                api_key=hass.data[DOMAIN][call.data["config_entry"]],
                prompt=call.data["prompt"],
                n=1,
                size=f'{call.data["size"]}x{call.data["size"]}',
            )
        except error.OpenAIError as err:
            raise HomeAssistantError(f"Error generating image: {err}") from err

        return response["data"][0]

    hass.services.async_register(
        DOMAIN,
        SERVICE_GENERATE_IMAGE,
        render_image,
        schema=vol.Schema(
            {
                vol.Required("config_entry"): selector.ConfigEntrySelector(
                    {
                        "integration": DOMAIN,
                    }
                ),
                vol.Required("prompt"): cv.string,
                vol.Optional("size", default="512"): vol.In(("256", "512", "1024")),
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up OpenAI Conversation from a config entry."""
    try:
        await hass.async_add_executor_job(
            partial(
                openai.Engine.list,
                api_key=entry.data[CONF_API_KEY],
                request_timeout=10,
            )
        )
    except error.AuthenticationError as err:
        _LOGGER.error("Invalid API key: %s", err)
        return False
    except error.OpenAIError as err:
        raise ConfigEntryNotReady(err) from err

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = entry.data[CONF_API_KEY]

    conversation.async_set_agent(hass, entry, OpenAIAgent(hass, entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload OpenAI."""
    hass.data[DOMAIN].pop(entry.entry_id)
    conversation.async_unset_agent(hass, entry)
    return True


class OpenAIAgent(conversation.AbstractConversationAgent):
    """OpenAI conversation agent."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the agent."""
        self.hass = hass
        self.entry = entry
        self.history: dict[str, list[dict]] = {}

    @property
    def supported_languages(self) -> list[str] | Literal["*"]:
        """Return a list of supported languages."""
        return MATCH_ALL

    async def async_process(
        self, user_input: conversation.ConversationInput
    ) -> conversation.ConversationResult:
        """Process a sentence."""
        if user_input.conversation_id in self.history:
            conversation_id = user_input.conversation_id
            messages = self.history[conversation_id]
        else:
            conversation_id = ulid.ulid()
            try:
                setup_prompt_template = get_setup_prompt()
                default_entity_states_template = get_entity_states_prompt()
                entity_states_prompt = self.entry.options.get(
                    CONF_PROMPT, default_entity_states_template)
                entity_states = self._async_generate_prompt(entity_states_prompt)
                location = self.entry.options.get(
                    CONF_LOCATION, DEFAULT_LOCATION)
                prompt = setup_prompt_template.format(
                    entity_states=entity_states,
                    location=location,
                    future_time_stamp='%c'.format(datetime.now() + timedelta(hours=1))
                )
            except TemplateError as err:
                _LOGGER.error("Error rendering prompt: %s", err)
                intent_response = intent.IntentResponse(
                    language=user_input.language)
                intent_response.async_set_error(
                    intent.IntentResponseErrorCode.UNKNOWN,
                    f"Sorry, I had a problem with my template: {err}",
                )
                return conversation.ConversationResult(
                    response=intent_response, conversation_id=conversation_id
                )
            messages = [{"role": "system", "content": prompt}]

        messages.append({"role": "user", "content": user_input.text})

        try:
            result = await self.async_send_openai_messages(conversation_id, messages)
        except error.OpenAIError as err:
            intent_response = intent.IntentResponse(
                language=user_input.language)
            intent_response.async_set_error(
                intent.IntentResponseErrorCode.UNKNOWN,
                f"Sorry, I had a problem talking to OpenAI: {err}",
            )
            return conversation.ConversationResult(
                response=intent_response, conversation_id=conversation_id
            )

        [response_content, new_messages] = await self.process_openai_result(
            conversation_id, result, messages, 0)

        self.history[conversation_id] = messages.concat(new_messages)

        intent_response = intent.IntentResponse(language=user_input.language)
        intent_response.async_set_speech(response_content)
        return conversation.ConversationResult(
            response=intent_response, conversation_id=conversation_id
        )

    async def async_send_openai_messages(self, conversation_id: any, messages: [] = []) -> any:
        model = self.entry.options.get(CONF_CHAT_MODEL, DEFAULT_CHAT_MODEL)
        max_tokens = self.entry.options.get(
            CONF_MAX_TOKENS, DEFAULT_MAX_TOKENS)
        top_p = self.entry.options.get(CONF_TOP_P, DEFAULT_TOP_P)
        temperature = self.entry.options.get(
            CONF_TEMPERATURE, DEFAULT_TEMPERATURE)
        _LOGGER.debug("Prompt for %s: %s", model, messages)

        result = await openai.ChatCompletion.acreate(
            api_key=self.entry.data[CONF_API_KEY],
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            top_p=top_p,
            temperature=temperature,
            user=conversation_id,
        )
        _LOGGER.info("Result for %s: %s", model, result)

        return result

    async def process_openai_result(self, conversation_id: any, result: any, messages: [] = [], recursion_index: int = 0) -> [str, any[]]:
        _LOGGER.info("""Messages: %s
produced result: %s""", messages, result)

        if (recursion_index > 1):
            _LOGGER.info('Max recursion index reached. Returning messages.')
            return messages

        response = result["choices"][0]["message"]
        try:
            response_json = json.loads(response["content"])
            if response_json["action"] == "query":
                # for entity in response_json["entities"]:
                #     _LOGGER.info(entity)
                response["content"] = response_json
            elif response_json["action"] == "command":
                if response_json["script_id"] == None:
                    raise Exception("I'm sorry, I'm not sure what to do. Can you rephrase your request?")
                elif response_json["area"] == None:
                    raise Exception("I'm sorry, I'm not sure which room to do that in. Can you let me know where in the home you want to do that?")                    
                else:
                    [domain, entity_id] = response_json["script_id"].split(".")
                    if self.hass.services.has_service(domain, entity_id) == False:
                        raise Exception(
                            "No service found for {domain} and {entity_id}.")

                    self.hass.async_create_task(
                        self.hass.services.async_call(
                            domain,
                            entity_id
                        )
                    )
                    response["content"] = response_json["comment"]
            elif response_json["action"] == "set":
                response["content"] = response_json["comment"]
            elif response_json["action"] == "clarify":
                response["content"] = response_json["question"]
            elif response_json["action"] == "answer":
                response["content"] = response_json["answer"]

        except json.JSONDecodeError as err:
            _LOGGER.error(err)
            intent_response = intent.IntentResponse(
                language=user_input.language)
            intent_response.async_set_error(
                intent.IntentResponseErrorCode.UNKNOWN,
                f"Sorry, I could not understand the response from OpenAI: {err}",
            )
            return conversation.ConversationResult(
                response=intent_response, conversation_id=conversation_id
            )

        except Exception as err:
            _LOGGER.error(err)
            intent_response = intent.IntentResponse(
                language=user_input.language)
            if hasattr(err, 'message'):
                message = err.messagee
            else:
                message = "I'm sorry. I didn't understand that. Try rephrasing your request and try again."
            intent_response.async_set_error(
                intent.IntentResponseErrorCode.UNKNOWN,
                message,
            )
            return conversation.ConversationResult(
                response=intent_response, conversation_id=conversation_id
            )

        return [response["content"], [response]]

    def _async_generate_prompt(self, raw_prompt: str) -> str:
        """Generate a prompt for the user."""
        return template.Template(raw_prompt, self.hass).async_render(
            {
                "ha_name": self.hass.config.location_name,
            },
            parse_result=False,
        )
