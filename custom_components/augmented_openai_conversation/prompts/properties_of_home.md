## Properties of Home

The home is located in {location}. The current time stamp is: {now_formatted}. The home consists of areas, entities, and scripts.

### Areas

An area is a room containing a collection of entities and scripts. An entity and script can only be in a single area.

### Entities

There are seven types of entities in the home:

- "light"
- "switch"
- "media_player"
- "climate"
- "lock"
- "sensor"
- "binary_sensor"

#### light

- has a "state". It can have a value of "on" or "off".
- has attribute "brightness" that defines the current brightness of the light. It can have a value between 0 and 100.

#### switch

- has a "state". It can have a value of "on" or "off".

#### media_player

- has a "state". It can have a value of "playing", "paused", "idle", "suspended", "unknown", "unavailable", "off", or "standby".
- has attribute "volume_level" defines the current volume of the media player. It can have a value between 0.0 and 1.0.
- has attribute "is_volume_muted" that defines if the media player is muted. It can have a value of "on" or "off"
- has attribute "sound_mode" that defines the current sound mode of the media player.
- has attribute "source" that defines the current source of the media player.

#### climate

- has a "state". It can have a value of "off", "heat", "cool", "auto", "dry", or "fan_only".
- has attribute "temperature" that defines the temperature the user set the thermostat to.
- has an attribute "current_temperature" that defines the current temperature in house. It can have a number value.
- can set the "temperature" to "up", "down", or set it to a number.

#### lock

- has a "state". It can have a value of "locked" or "unlocked".

#### sensor

- has a "state". It cannot be set.

#### binary_sensor

- has a "state". It cannot be set.

### Scripts

Scripts perform an action for the user.
