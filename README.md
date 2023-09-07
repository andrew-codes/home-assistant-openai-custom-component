[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

# Augmented OpenAI Conversation Integration

> Note this is highly tailored to my setup.

This custom integration utilizes OpenAI's chat to accept user requests as text and respond with a JSON information regarding the intent. The intent can be one of the following:

- "set": change the state of entity (required properties in the response JSON: action, area, entities, value, comment, scheduleTimeStamp).
- "command": execute a script (required properties in the response JSON: action, area, script, comment, scheduleTimeStamp).
- "query": get state or attributes of a single entity (required properties in the response JSON: action, area, entity, attributes).
- "answer": when the request has nothing to do with the smart home. Answer these to the best of your knowledge. (required properties in the response JSON: action, comment).
- "clarify": when the action is not obvious and requires rephrasing the input from the user, ask the user to be more specific. This will be categorized into a "question" action. (required properties in the response JSON: action, comment).

The intent will then be processed by the integration to take some action or query the state of Home Assistant.

- When a command is used, then the summary of the command will the plain text response.
- When querying the state of the home, then a summary of the entities and their attributes will be provided.
