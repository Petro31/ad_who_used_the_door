# Home Assistant Who Used the Door Sensor & Notifications

[![hacs_badge](https://img.shields.io/badge/HACS-Default-orange.svg?style=for-the-badge)](https://github.com/custom-components/hacs)
<br><a href="https://www.buymeacoffee.com/Petro31" target="_blank"><img src="https://cdn.buymeacoffee.com/buttons/default-black.png" width="150px" height="35px" alt="Buy Me A Coffee" style="height: 35px !important;width: 150px !important;" ></a>

_Who Used the Door app for AppDaemon._

This creates 2 sensors that peel the last opened and last closed timestamp out of a binary_sensor/sensor door.  This also will notify users of the following events:

* Who used the door with a time and date stamp.  This includes intruder tracking.  e.g. if an unknown person opens the door, a listener will be created and listen for a known person to show up.  If the known person shows up within 90 seconds, a message will be sent saying that the person who used the door is {name}.
* If the door is open for more than `{duration}`.
* How many times the door has been opened over the past {quiet_window} period. (to keep the messages down)

I'm reluctant to share this app because it can be very annoying.  This is something that I wrote many years ago and never bothered changing the functionality.  I am open to suggestions for making this less notification heavy.

## Requirements

This requires the [People Tracker](https://github.com/Petro31/ad_people_tracker) appdaemon app.

## Installation

Download the `who_used_the_door` directory from inside the `apps` directory to your local `apps` directory, then add the configuration to enable the `hacs` module.

## Example App configuration

#### Basic, No notifications
```yaml
# Creates 2 sensors sensor.main_door_last_opened, and  sensor.main_door_last_closed
main_door:
  module: who_used_the_door
  class: WhoUsedTheDoor
  sensor: sensor.main_door
  people_tracker: sensor.people_tracker
  message_name: Main Door
```

#### Advanced 
```yaml
# Creates all notifications
main_door:
  module: who_used_the_door
  class: WhoUsedTheDoor
  sensor: sensor.main_door
  people_tracker: sensor.people_tracker
  message_name: Main Door
  notify:
    door_ajar:
      timestamp: '%-I:%M:%S %p'
      duration: 120
      notify:
      - notify.petro
    door_open:
      timestamp: '%-I:%M:%S %p'
      quiet_window: 120
      notify:
      - notify.petro
```

#### App Configuration
key | optional | type | default | description
-- | -- | -- | -- | --
`module` | False | string | who_used_the_door | The module name of the app.
`class` | False | string | WhoUsedTheDoor | The name of the Class.
`sensor` | False | string | | entity_id of the door sensor.
`people_tracker` | False | string | | entity_id of the people tracker sensor.
`message_name` | True | string | `<sensor.attributes.friendly_name>` | Name of the door for your notifications.
`open_name` | True | string | `<sensor.attributes.friendly_name> Last Opened` | Name of the Last Opened sensor.
`close_name` | True | string | `<sensor.attributes.friendly_name> Last Closed` | Name of the Last Closed sensor.
`notify`| True | map | `door_ajar` &#124; `door_open` | open or ajar notification map, see below.
`log_level` | True | `'INFO'` &#124; `'DEBUG'` | `'INFO'` | Switches log level.

#### Ajar Notification Map Configuration
key | optional | type | default | description
-- | -- | -- | -- | --
`notify` | False | list | | list of notify entity_ids.
`title` | True | string | | Title of the notifications.
`timestamp` | True | string | | Timestamp format for messages.  Use `'%-I:%M:%S %p'` for 12 hr notation and `'%-H:%M:%S'` for 24 hr notation.
`duration` | True | int | 30 | If the door is open longer than this time, send a message.

#### Open Notification Map Configuration
key | optional | type | default | description
-- | -- | -- | -- | --
`notify` | False | list | | list of notify entity_ids.
`title` | True | string | | Title of the notifications.
`timestamp` | True | string | | Timestamp format for messages.  Use `'%-I:%M:%S %p'` for 12 hr notation and `'%-H:%M:%S'` for 24 hr notation.
`quiet_window` | True | int | 0 | After the first door open, a quiet window will activate.  During this window, all door open messages will be suppressed.  After the window is met, a final message will appear with a count of door opens.  0 = no quiet window.  I created this because I found that we would open the door in bursts and we didn't want 900000000 messages.
