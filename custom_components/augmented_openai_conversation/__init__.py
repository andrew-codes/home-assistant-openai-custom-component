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
    CONF_TEMPERATURE,
    CONF_LOCATION,
    CONF_TOP_P,
    DEFAULT_CHAT_MODEL,
    DEFAULT_MAX_TOKENS,
    DEFAULT_TEMPERATURE,
    DEFAULT_LOCATION,
    DEFAULT_TOP_P,
    DOMAIN,
    get_prompt,
)

_LOGGER = logging.getLogger(__name__)
SERVICE_GENERATE_IMAGE = "generate_image"

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up OpenAI Conversation."""
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
        try:
            if user_input.conversation_id in self.history:
                conversation_id = user_input.conversation_id
                messages = self.history[conversation_id]
            else:
                conversation_id = ulid.ulid()
                location = self.entry.options.get(
                    CONF_LOCATION, DEFAULT_LOCATION)
                persona_prompt = get_prompt('persona')
                intent_detection_prompt = get_prompt('intent_detection').format(
                    location=location, now_formatted='%c'.format(datetime.now()))
                properties_of_home_prompt = get_prompt("properties_of_home")

                intent_prompt = persona_prompt + "\n\n" + \
                    intent_detection_prompt + "\n\n" + properties_of_home_prompt

                messages = [{"role": "system", "content": intent_prompt}]
                discover_intention_messages = messages + \
                    [{"role": "user", "content": user_input.text}]

                [intent_data, new_message] = await self.async_send_openai_messages("intent_detection", discover_intention_messages)
                self.intention = intent_data

                match self.intention:
                    case "set":
                        set_prompt = get_prompt('set')
                        entity_states_prompt = get_prompt('entity_states')
                        entity_states = self._async_generate_prompt(
                            entity_states_prompt)
                        prompt = persona_prompt + "\n\n" + set_prompt + "\n\n" + entity_states
                        messages.append({"role": "system", "content": prompt})

                    case "command":
                        command_prompt = get_prompt('command')
                        scripts_prompt = get_prompt('scripts')
                        scripts = self._async_generate_prompt(scripts_prompt)
                        prompt = persona_prompt + "\n\n" + command_prompt + "\n\n" + scripts
                        messages.append({"role": "system", "content": prompt})

                    case "query":
                        query_prompt = get_prompt('query')
                        entity_states_prompt = get_prompt('entity_states')
                        entity_states = self._async_generate_prompt(
                            entity_states_prompt)
                        prompt = persona_prompt + "\n\n" + query_prompt + "\n\n" + entity_states
                        messages.append({"role": "system", "content": prompt})

                    case "question":
                        question_prompt = get_prompt('question')
                        entity_states_prompt = get_prompt('entity_states')
                        entity_states = self._async_generate_prompt(
                            entity_states_prompt)
                        prompt = persona_prompt + "\n\n" + question_prompt + "\n\n" + entity_states
                        messages.append({"role": "system", "content": prompt})

                    case "clarify_intent":
                        raise Exception(
                            "Can you rephrase your request and try again?")
                    case _:
                        raise Exception(
                            "Can you rephrase your request and try again?")

            messages.append(
                {"role": "user", "content": user_input.text})

            [content, new_message] = await self.async_send_openai_messages(conversation_id, messages)

            match self.intention:
                case "set":
                    raise Exception("I can't directly control devices yet.")

                case "command":
                    request_data = json.loads(content)

                    if request_data["area"] == None:
                        raise Exception("What room is that in?")
                    elif request_data["script_id"] == None:
                        raise Exception(
                            "I'm not familiar with that. Can you try again?")
                    elif self.hass.states.get(request_data["script_id"]) == None:
                        raise Exception(
                            "I'm not able to complete your request in the {area}. Can you tell me what room and ask again?".format(area=request_data["area"]))

                    new_message["content"] = request_data["comment"] + "...: area, ID: {area}, {id}".format(
                        area=request_data["area"], id=request_data["script_id"])

        except error.OpenAIError as err:
            _LOGGER.error("Network error rendering prompt: %s", err)
            intent_response = intent.IntentResponse(
                language=user_input.language)
            intent_response.async_set_error(
                intent.IntentResponseErrorCode.UNKNOWN,
                f"Sorry, I I'm having trouble completing your request.",
            )
            return conversation.ConversationResult(
                response=intent_response, conversation_id=conversation_id
            )

        except json.JSONDecodeError as err:
            _LOGGER.error("Error parsing JSON: %s", err)
            intent_response = intent.IntentResponse(
                language=user_input.language)
            intent_response.async_set_error(
                intent.IntentResponseErrorCode.UNKNOWN,
                f"Sorry, I'm having trouble completing your request.",
            )
            return conversation.ConversationResult(
                response=intent_response, conversation_id=conversation_id
            )

        except TemplateError as err:
            _LOGGER.error(
                "Error rendering Home Assistant template: %s", err)
            intent_response = intent.IntentResponse(
                language=user_input.language)
            intent_response.async_set_error(
                intent.IntentResponseErrorCode.UNKNOWN,
                f"Sorry, I'm having trouble completing your request.",
            )
            return conversation.ConversationResult(
                response=intent_response, conversation_id=conversation_id
            )

        except Exception as err:
            _LOGGER.error(err)

            message = "I'm sorry."
            if hasattr(err, 'message'):
                message = message + " " + err.message
            else:
                message = message + " " + str(err)

            new_message["content"] = message
            messages.append(new_message)

            intent_response = intent.IntentResponse(
                language=user_input.language)
            intent_response.async_set_error(
                intent.IntentResponseErrorCode.UNKNOWN,
                message,
            )
            return conversation.ConversationResult(
                response=intent_response, conversation_id=conversation_id
            )

        self.history[conversation_id] = messages

        intent_response = intent.IntentResponse(
            language=user_input.language)
        intent_response.async_set_speech(new_message["content"])

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

        message = result["choices"][0]["message"]

        return [message["content"], message]

    def _async_generate_prompt(self, raw_prompt: str) -> str:
        """Generate a prompt for the user."""
        return template.Template(raw_prompt, self.hass).async_render(
            {
                "ha_name": self.hass.config.location_name,
            },
            parse_result=False,
        )
