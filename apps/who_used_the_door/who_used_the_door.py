import appdaemon.plugins.hass.hassapi as hass
import json
import time
import shelve
import voluptuous as vol
import os
from datetime import timedelta, datetime

# General

CONF_MODULE = 'module'
CONF_CLASS = 'class'
CONF_SENSOR = 'sensor'
CONF_OPEN_NAME = 'open_name'
CONF_CLOSE_NAME = 'close_name'
CONF_MESSAGE_NAME = 'message_name'
CONF_NAME = 'name'
CONF_NOTIFY = 'notify'
CONF_TITLE = 'title'
CONF_TIMESTAMP = 'timestamp'
CONF_PEOPLE_TRACKER = 'people_tracker'
CONF_LOG_LEVEL = 'log_level'

# Notification Types

CONF_AJAR = 'door_ajar'
CONF_OPEN = 'door_open'

# Notification Options

CONF_MESSAGE = 'message'
CONF_DURATION = 'duration'
CONF_QUIET_WINDOW = 'quiet_window'
CONF_COUNT = 'count'

# Door States

STATE_ON = 'on'
STATE_OFF = 'off'
STATE_OPEN = 'open'
STATE_CLOSED = 'closed'
STATE_UNKNOWN = 'unknown'

PEOPLE_TRACKER_ENTITY_ID = 'sensor.people_tracker'
DEFAULT_TIMESTAMP_FORMAT = '%-I:%M:%S %p'

DOOR_OPEN_STATES = [ STATE_OPEN, STATE_ON ]
DOOR_CLOSED_STATES = [ STATE_CLOSED, STATE_OFF ]

# logs

LOG_ERROR = 'ERROR'
LOG_DEBUG = 'DEBUG'
LOG_INFO = 'INFO'

# Attributes
ATTRIBUTE_FRIENDLY_NAME = 'friendly_name'
ATTRIBUTE_WHO = 'who'
ATTRIBUTE_DEVICE_CLASS = 'device_class'

STATE = 'state'
ATTRIBUTES = 'attributes'

INTRUDER = 'intruder'

TIMER_STATE = 'timer_state'
TIMER_OBJECT = 'timer_object'

DOMAIN ='domain'
SERVICE = 'service'

# Schemas

AJAR_SCHEMA = {
    vol.Required(CONF_NOTIFY, default=[]): [str],
    vol.Optional(CONF_DURATION, default=30): vol.All(vol.Coerce(int), vol.Range(min=1)),
    vol.Optional(CONF_TIMESTAMP, default=''): str,
    vol.Optional(CONF_TITLE, default=''): str,
    }

OPEN_SCHEMA = {
    vol.Required(CONF_NOTIFY, default=[]): [str],
    vol.Optional(CONF_QUIET_WINDOW, default=0): vol.All(vol.Coerce(int), vol.Range(min=0)),
    vol.Optional(CONF_TIMESTAMP, default=''): str,
    vol.Optional(CONF_TITLE, default=''): str,
    }

NOTIFY_SCHEMA = {
    vol.Optional(CONF_AJAR): AJAR_SCHEMA,
    vol.Optional(CONF_OPEN): OPEN_SCHEMA,
}

APP_SCHEMA = vol.Schema({
    vol.Required(CONF_MODULE): str,
    vol.Required(CONF_CLASS): str,
    vol.Required(CONF_SENSOR): str,
    vol.Required(CONF_PEOPLE_TRACKER, default=PEOPLE_TRACKER_ENTITY_ID): str,
    vol.Optional(CONF_MESSAGE_NAME): str,
    vol.Optional(CONF_OPEN_NAME): str,
    vol.Optional(CONF_CLOSE_NAME): str,
    vol.Optional(CONF_NOTIFY): NOTIFY_SCHEMA,
    vol.Optional(CONF_LOG_LEVEL, default=LOG_DEBUG): vol.Any(LOG_INFO, LOG_DEBUG),
    })

class WhoUsedTheDoor(hass.Hass):
    def initialize(self):
        args = APP_SCHEMA(self.args)\

        # Set Lazy Logging (to not have to restart appdaemon)
        self._level = args.get(CONF_LOG_LEVEL)
        self.log(args, level=self._level)
        
        pth = os.path.join(self.app_dir, self.__module__, 'states')
        self.log(f"database -> {pth}", level= self._level)
        self._database = Database(pth)

        # All valid notification services.
        self._services = [ service[SERVICE] for service in self.list_services(namespace="default") if service[DOMAIN] == CONF_NOTIFY ]
        self.log(f"Notify services {self._services}", level = self._level)

        self._listen_entity = args.get(CONF_SENSOR)
        self._people_tracker = args.get(CONF_PEOPLE_TRACKER)

        message_name = args.get(CONF_MESSAGE_NAME)

        # Setup
        listen_name = self.get_state(self._listen_entity, attribute=ATTRIBUTE_FRIENDLY_NAME)
        self._message_name = message_name if message_name else listen_name
        self._open_sensor = Sensor( 
            args.get(CONF_OPEN_NAME, f"{listen_name} Last Opened")
        )
        self._close_sensor = Sensor(
            args.get(CONF_CLOSE_NAME, f"{listen_name} Last Closed")
        )
        # update the open sensor if we have data in the json dumps
        self.update_sensor(
            self._open_sensor.entity_id, 
            **self._database.read(self._open_sensor.entity_id)
            )
        # update the close sensor if we have data in the json dumps
        self.update_sensor(
            self._close_sensor.entity_id,
            **self._database.read(self._close_sensor.entity_id)
            )

        self._timestamp_format = args.get(CONF_TIMESTAMP)
        
        notify = args.get(CONF_NOTIFY, {})
        self._ajar = AppDoorObject(notify.get(CONF_AJAR, {}), self._services)
        self._open = AppDoorObject(notify.get(CONF_OPEN, {}), self._services)

        self.handles = {}
        self.timers = {}

        self._count = 0
        self._timer = Timer()

        self.log(f"Creating '{self._listen_entity}' listener.", level = self._level)
        self.handles[self._listen_entity] = self.listen_state(self.door_callback, self._listen_entity)
        if self._ajar.enabled:
            self.handles[self._people_tracker] = self.listen_state(self.door_ajar_callback, self._people_tracker)

    def door_ajar_callback(self, entity, attribute, old, new, kwargs):
        self.log(f"door_ajar_callback {entity}.{attribute}: {old} -> {new}", level = self._level)
        # if people leave and the door is open.
        if int(new) == 0 and int(old) > 0:
            state = self.get_state(self._listen_entity)
            if state in DOOR_OPEN_STATES:
                message = f"{self._message_name} is {STATE_OPEN} and no one is home!"
                self.bulk_nofity(self._ajar, message)

    def door_callback(self, entity, attribute, old, new, kwargs):
        self.log(f"door_callback {entity}.{attribute}: {old} -> {new}", level = self._level)
        timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f+00:00")
        #timestamp = datetime.now().timestamp()

        if self._count == 0:
            self._timer.reset()

        if new in DOOR_OPEN_STATES:
            # increment the number of times the door has been opened.
            self._count += 1

            tkwargs = {TIMER_STATE:STATE_OPEN}

            # start a timer to track how long the door is open\
            self.log(f"Creating '{CONF_AJAR}' timer.", level = self._level)
            self.start_timer(self.nofity_door_open, CONF_AJAR, self._ajar, **tkwargs)
            # update the sensor with opened door information
            state = self.update_sensor_object(self._open_sensor, timestamp)

            # send door opened notification.
            if self._open.enabled:
                # start a timer for quiet window if a quiet window is enabled.
                if self._open.duration > 0:
                    self.start_timer(
                        self.reset_counter,
                        CONF_QUIET_WINDOW,
                        self._open,
                        **tkwargs,
                    )

                # if we get every message, or we are on our first message.
                if self._open.duration == 0 or (self._open.duration > 0 and self._count <= 1):
                    if state == STATE_UNKNOWN.title():
                        state = "Unknown person"

                        # Cancel unknown person listener.
                        self.cancel_listen_handle(INTRUDER)

                        # Start an unknown person listener.
                        self.log(f"Creating '{INTRUDER}' listener.", level = self._level)
                        self.handles[INTRUDER] = self.listen_state(
                            self.intruder_callback,
                            self._people_tracker,
                            attribute='all',
                            **{CONF_TIMESTAMP:timestamp}
                        )

                        # Cancel unknown person timer.
                        self.cancel_timer_handle(INTRUDER)

                        # Start unknown person timer.
                        self._start_app_timer(
                            self.notify_intruder,
                            INTRUDER,
                            90,
                            **tkwargs)

                    message = f"{state} used the {self._message_name}."
                    self.bulk_nofity(self._open, message)

        if new in DOOR_CLOSED_STATES:
            self.cancel_timer_handle(CONF_AJAR)
            self.update_sensor_object(self._close_sensor, timestamp)

    def cancel_listen_handle(self, name):
        if name in self.handles:
            self.log(f"Canceling '{name}' listen state.", level = self._level)
            self.cancel_listen_state(self.handles[name])

    def cancel_timer_handle(self, name):
        if name in self.timers:
            self.log(f"Canceling '{name}' timer.", level = self._level)
            self.cancel_timer(self.timers[name])

    def reset_counter(self, kwargs):
        if self._count >= 3: #probably shouldn't hardcode this.
            duration = self.friendly_time(self._timer.elapsed, self._open.duration < 60)
            message = f"The {self._message_name} was opened {self._count} times over the past {duration}."
            self.bulk_nofity(self._open, message)
        self._count = 0

    def intruder_callback(self, entity, attribute, old, new, kwargs):
        self.log(f"intruder_callback {entity}.{attribute}: {old} -> {new}", level = self._level)
        state = int(new[STATE])
        people = new[ATTRIBUTES]['or']
        timestamp = kwargs.get(CONF_TIMESTAMP)
        if state > 0:
            who = 'people' if state > 1 else 'person'
            message = f"The {who} who used the door was {people}"
            self.bulk_nofity(self._open, message)
            self.update_sensor_object(self._open_sensor, timestamp)
            self.cancel_listen_handle(INTRUDER)
            self.cancel_timer_handle(INTRUDER)

    def notify_intruder(self, kwargs):
        message = f"The person who used {self._message_name} is still unknown!"
        self.bulk_nofity(self._open, message)

    def update_sensor_object(self, sensor, timestamp):
        who = self.get_state(self._people_tracker, attribute='or')
        attributes = {
            ATTRIBUTE_FRIENDLY_NAME: sensor.name,
            ATTRIBUTE_WHO: who,
            ATTRIBUTE_DEVICE_CLASS: CONF_TIMESTAMP,
        }
        state = timestamp
        self.update_sensor(sensor.entity_id, state, attributes)
        self._database.write(sensor.entity_id, state, attributes)
        return who

    def update_sensor(self, entity_id, state='', attributes={}):
        if state and attributes:
            self.log(f"{entity_id} -> {state}: {attributes}", level = self._level)
            self.set_state(entity_id, state=state, attributes=attributes)
        else:
            attributes = {
                ATTRIBUTE_FRIENDLY_NAME: STATE_UNKNOWN.title(),
                ATTRIBUTE_WHO: STATE_UNKNOWN,
                ATTRIBUTE_DEVICE_CLASS: CONF_TIMESTAMP,
            }
            self.log(f"{entity_id} -> {state}: {attributes}", level = self._level)
            self.set_state(entity_id, state=STATE_UNKNOWN, attributes=attributes)

    def _start_app_timer(self, callback, timer_name, duration, **kwargs):
        self.log(f"Creating '{timer_name}' timer.", level = self._level)
        self.timers[timer_name] = self.run_in(callback, duration, **kwargs)

    def start_timer(self, callback, timer_name, appobj, **kwargs):
        if appobj.enabled:
            kwargs[TIMER_OBJECT] = appobj
            self._start_app_timer(callback, timer_name, appobj.duration, **kwargs)

    def nofity_door_open(self, kwargs):
        state = kwargs.get(TIMER_STATE)
        appobj = kwargs.get(TIMER_OBJECT)
        duration = self.friendly_time(appobj.duration, appobj.duration < 60)
        message = f"{self._message_name} has been {state} for more than {duration}."
        self.bulk_nofity(appobj, message)

    def bulk_nofity(self, appobj, message):
        for message, data in appobj.notify(message):
            self.log(f"Notifying '{data[CONF_NAME]}': '{message}'", level = self._level)
            self.notify(message, **data)

    def terminate(self):
        for name in self.handles.keys():
            self.cancel_listen_handle(name)
        for name in self.timers.keys():
            self.cancel_timer_handle(name)

    def friendly_time(self, seconds, include_seconds=True):
        def plural(v, string):
            if v > 1:
                return '{} {}s'.format(v, string)
            else:
                return string

        hours, remainder = divmod(seconds, 3600)
        minutes, seconds = divmod(remainder, 60)

        if not include_seconds:
            minutes += int(round(seconds/60))

        hours, minutes, seconds = [ int(v) for v in [ hours, minutes, seconds ] ]

        ret = []
        if hours:
            ret.append(plural(hours, 'hour'))
        if minutes:
            ret.append(plural(minutes, 'minute'))
        if seconds and include_seconds:
            ret.append(plural(seconds, 'second'))

        if len(ret) == 0:
            return None
        elif len(ret) == 1:
            return ret[0]
        else:
            return ' and '.join(ret)

class AppDoorObject(object):
    def __init__(self, data={}, services=[]):
        self.enabled = data != {}
        key = CONF_DURATION if CONF_DURATION in data else CONF_QUIET_WINDOW
        self.duration = data.get(key)
        self.timestamp = data.get(CONF_TIMESTAMP)
        self.title = data.get(CONF_TITLE)
        self._notify = []
        self.invalid = []
        for n in data.get(CONF_NOTIFY, []):
            if n.startswith(CONF_NOTIFY) and n.count('.') == 1:
                n = n.split('.')[-1]
            if n in services:
                self._notify.append(n)
            else:
                self.invalid.append(n)

    def notify(self, message):
        if self.timestamp:
            dt = datetime.now()
            message = f"[{dt.strftime(self.timestamp)}] {message}"
        for notify in self._notify:
            data = {
                CONF_NAME: notify
            }
            if self.title:
                data[CONF_TITLE]=self.title
            yield message, data

class Sensor(object):
    def __init__(self, name):
        self.name = name
        self.entity_id = f"{CONF_SENSOR}.{self.name.replace(' ','_').lower()}"

class Database(object):
    def __init__(self, filename):
        self._filename = filename
    
    def write(self, entity_id, state, attributes):
        with shelve.open(self._filename) as db:
            db[entity_id] = json.dumps({
                STATE:state,
                ATTRIBUTES:attributes,
                })

    def read(self, entity_id):
        with shelve.open(self._filename) as db:
            if entity_id in db.keys():
                return json.loads(db[entity_id])
            else:
                return {}

class Timer(object):
    def __init__(self):
        self._start = time.time()

    def reset(self):
        self._start = time.time()

    @property
    def elapsed(self):
        return time.time() - self._start
